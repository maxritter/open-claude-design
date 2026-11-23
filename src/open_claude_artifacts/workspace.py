"""Symlink-safe local workspace I/O, capability redaction, and browser helpers."""

from __future__ import annotations

import contextlib
import difflib
import errno
import fcntl
import hashlib
import json
import os
import re
import secrets
import shutil
import stat
import subprocess
import sys
import unicodedata
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urlparse

from open_claude_artifacts.config import (
    ARTIFACT_CONTENT_HOST_SUFFIX,
    ARTIFACT_MAX_FILE_BYTES,
    ARTIFACT_MAX_INLINE_FILE_BYTES,
    ARTIFACT_MAX_STDIN_BYTES,
    ARTIFACT_RESOURCE_HOSTS,
    WORKSPACE_STATE_DIR,
)
from open_claude_artifacts.errors import ArtifactProtocolError, ArtifactSafetyError

_CAPABILITY_TOKEN_RE = re.compile(r"([?&](?:__frame_t|token|access_token|assetToken)=)[^&\s\"']+", re.IGNORECASE)


def has_unsafe_text_character(value: str) -> bool:
    return any(unicodedata.category(ch) in {"Cc", "Cf", "Zl", "Zp"} for ch in value)


def _repository_root(start: Path) -> Path | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=start,
            capture_output=True,
            text=True,
            shell=False,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode == 0 and result.stdout.strip():
        return Path(result.stdout.strip())
    return None


def workspace_root(override: Path | None = None) -> Path:
    """Return the enclosing worktree root, falling back to the current directory."""
    root = override if override is not None else _repository_root(Path.cwd()) or Path.cwd()
    try:
        resolved = root.expanduser().resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise ArtifactSafetyError("Could not resolve the current local workspace.") from error
    if not resolved.is_dir():
        raise ArtifactSafetyError(f"The local workspace is not a directory: {resolved}")
    return resolved


def _absolute_local_path(raw_path: str) -> Path:
    try:
        expanded = Path(raw_path).expanduser()
        candidate = expanded if expanded.is_absolute() else Path.cwd() / expanded
        return Path(os.path.abspath(candidate))
    except (OSError, RuntimeError) as error:
        raise ArtifactSafetyError("Could not resolve the requested local path.") from error


def resolve_local_path(
    raw_path: str,
    *,
    workspace_root: Path,
    authorized_external_paths: list[str],
    require_file: bool,
) -> Path:
    """Resolve a local operand without allowing an implicit workspace escape."""
    candidate = _absolute_local_path(raw_path)

    inside_workspace = candidate.is_relative_to(workspace_root)
    authorized = {_absolute_local_path(path) for path in authorized_external_paths}
    if not inside_workspace and candidate not in authorized:
        raise ArtifactSafetyError(
            f"Local path is outside the current workspace: {candidate}. "
            "Pass --allow-external-local-path with that exact path only when the user explicitly authorized it."
        )

    symlink_base = workspace_root if inside_workspace else Path(candidate.anchor)
    current = symlink_base
    for part in candidate.relative_to(symlink_base).parts:
        current /= part
        if current.is_symlink():
            raise ArtifactSafetyError(f"Local paths may not contain symlinks: {candidate}")

    if require_file and not candidate.is_file():
        raise ValueError(f"Local file not found: {candidate}")
    return candidate


def _safe_directory_flags() -> int:
    nofollow = getattr(os, "O_NOFOLLOW", None)
    directory = getattr(os, "O_DIRECTORY", None)
    if nofollow is None or directory is None or os.open not in os.supports_dir_fd:
        raise ArtifactSafetyError("Symlink-safe local file access is unavailable on this platform.")
    return os.O_RDONLY | nofollow | directory | getattr(os, "O_CLOEXEC", 0)


def _raise_safe_path_error(path: Path, error: OSError) -> None:
    if error.errno in {errno.ELOOP, errno.ENOTDIR}:
        raise ArtifactSafetyError(f"Local paths may not contain symlinks: {path}") from error
    if error.errno == errno.ENOENT:
        raise ValueError(f"Local path not found: {path}") from error
    raise error


def _open_local_parent(
    path: Path,
    *,
    workspace_root: Path,
    authorized_external_paths: list[str],
    create_parents: bool,
) -> tuple[int, str, Path]:
    path = resolve_local_path(
        str(path),
        workspace_root=workspace_root,
        authorized_external_paths=authorized_external_paths,
        require_file=False,
    )
    base = workspace_root if path.is_relative_to(workspace_root) else Path(path.anchor)
    relative = path.relative_to(base)
    if not relative.parts:
        raise ArtifactSafetyError("A local path must name a file.")

    flags = _safe_directory_flags()
    try:
        directory_fd = os.open(base, flags)
    except OSError as error:
        _raise_safe_path_error(path, error)
        raise AssertionError("unreachable") from error

    try:
        for part in relative.parts[:-1]:
            try:
                next_fd = os.open(part, flags, dir_fd=directory_fd)
            except FileNotFoundError:
                if not create_parents:
                    raise ValueError(f"Local path not found: {path}") from None
                try:
                    os.mkdir(part, mode=0o755, dir_fd=directory_fd)
                    next_fd = os.open(part, flags, dir_fd=directory_fd)
                except OSError as error:
                    _raise_safe_path_error(path, error)
                    raise AssertionError("unreachable") from error
            except OSError as error:
                _raise_safe_path_error(path, error)
                raise AssertionError("unreachable") from error
            os.close(directory_fd)
            directory_fd = next_fd
        return directory_fd, relative.parts[-1], path
    except Exception:
        os.close(directory_fd)
        raise


def read_local_file(
    path: str,
    *,
    workspace_root: Path,
    authorized_external_paths: list[str],
    maximum_bytes: int = ARTIFACT_MAX_INLINE_FILE_BYTES,
) -> tuple[Path, bytes]:
    """Read one regular file through pinned directory descriptors with a hard cap."""
    resolved = resolve_local_path(
        path,
        workspace_root=workspace_root,
        authorized_external_paths=authorized_external_paths,
        require_file=True,
    )
    directory_fd, name, resolved = _open_local_parent(
        resolved,
        workspace_root=workspace_root,
        authorized_external_paths=authorized_external_paths,
        create_parents=False,
    )
    file_fd: int | None = None
    try:
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
        try:
            file_fd = os.open(name, flags, dir_fd=directory_fd)
        except OSError as error:
            _raise_safe_path_error(resolved, error)
            raise AssertionError("unreachable") from error
        if not stat.S_ISREG(os.fstat(file_fd).st_mode):
            raise ValueError(f"Local file is not a regular file: {resolved}")
        chunks: list[bytes] = []
        remaining = maximum_bytes + 1
        while remaining > 0:
            chunk = os.read(file_fd, min(64 * 1024, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        data = b"".join(chunks)
        if len(data) > maximum_bytes:
            raise ArtifactSafetyError(
                f"Local file exceeds Open Claude Artifacts' {maximum_bytes} byte safety cap: {resolved}."
            )
        return resolved, data
    finally:
        if file_fd is not None:
            os.close(file_fd)
        os.close(directory_fd)


def atomic_write_local(
    path: Path,
    data: bytes,
    *,
    force: bool,
    workspace_root: Path,
    authorized_external_paths: list[str],
) -> None:
    """Atomically write bytes to a non-symlink local file."""
    directory_fd, name, path = _open_local_parent(
        path,
        workspace_root=workspace_root,
        authorized_external_paths=authorized_external_paths,
        create_parents=True,
    )
    temporary_name: str | None = None
    try:
        try:
            destination = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        except FileNotFoundError:
            destination = None
        if destination is not None and stat.S_ISLNK(destination.st_mode):
            raise ArtifactSafetyError(f"Local paths may not contain symlinks: {path}")
        if destination is not None and not force:
            raise ArtifactSafetyError(f"Local output already exists: {path}. Pass --force to replace it.")

        for _attempt in range(10):
            temporary_name = f".{name}.{secrets.token_hex(8)}"
            try:
                temporary_fd = os.open(
                    temporary_name,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
                    0o600,
                    dir_fd=directory_fd,
                )
                break
            except FileExistsError:
                temporary_name = None
        else:
            raise ArtifactSafetyError(f"Could not create an atomic local output beside: {path}")

        try:
            view = memoryview(data)
            while view:
                written = os.write(temporary_fd, view)
                if written <= 0:
                    raise OSError("Could not complete the atomic local write.")
                view = view[written:]
            os.fsync(temporary_fd)
        finally:
            os.close(temporary_fd)

        try:
            destination = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        except FileNotFoundError:
            destination = None
        if destination is not None and stat.S_ISLNK(destination.st_mode):
            raise ArtifactSafetyError(f"Local paths may not contain symlinks: {path}")
        if destination is not None and not force:
            raise ArtifactSafetyError(f"Local output already exists: {path}. Pass --force to replace it.")
        os.replace(temporary_name, name, src_dir_fd=directory_fd, dst_dir_fd=directory_fd)
        temporary_name = None
    finally:
        if temporary_name is not None:
            with contextlib.suppress(FileNotFoundError):
                os.unlink(temporary_name, dir_fd=directory_fd)
        os.close(directory_fd)


def ensure_state_ignored(root: Path) -> None:
    """Keep generated local state out of Git status without editing tracked ignore files."""
    marker = root / WORKSPACE_STATE_DIR / ".git-exclude-ready"
    if marker.is_file() and not marker.is_symlink():
        return
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--git-path", "info/exclude"],
            cwd=root,
            capture_output=True,
            text=True,
            shell=False,
            timeout=5,
            check=False,
        )
        if result.returncode == 0 and result.stdout.strip():
            raw_path = Path(result.stdout.strip())
            exclude_path = raw_path if raw_path.is_absolute() else root / raw_path
            exclude_path = exclude_path.resolve(strict=False)
            if not exclude_path.parent.is_dir() or exclude_path.parent.is_symlink():
                raise OSError("Git's local exclude directory is unavailable or unsafe.")
            flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
            descriptor = os.open(exclude_path, flags, 0o644)
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX)
                existing = os.read(descriptor, ARTIFACT_MAX_STDIN_BYTES + 1)
                if len(existing) > ARTIFACT_MAX_STDIN_BYTES:
                    raise OSError("Git's local exclude file exceeds the safety limit.")
                rule = f"{WORKSPACE_STATE_DIR}/".encode("ascii")
                if rule not in {line.strip() for line in existing.splitlines()}:
                    suffix = b"" if not existing or existing.endswith(b"\n") else b"\n"
                    os.lseek(descriptor, 0, os.SEEK_END)
                    pending = memoryview(suffix + rule + b"\n")
                    while pending:
                        written = os.write(descriptor, pending)
                        if written <= 0:
                            raise OSError("Could not update Git's local exclude file.")
                        pending = pending[written:]
                    os.fsync(descriptor)
            finally:
                os.close(descriptor)
    except (OSError, RuntimeError, subprocess.SubprocessError):
        pass
    atomic_write_local(
        marker,
        b"ready\n",
        force=marker.exists(),
        workspace_root=root,
        authorized_external_paths=[],
    )


def redact_capabilities(value: Any) -> Any:
    """Strip short-lived capability tokens and frame content URLs before printing."""
    if isinstance(value, str):
        if ARTIFACT_CONTENT_HOST_SUFFIX in value:
            return "[redacted-capability-url]"
        return _CAPABILITY_TOKEN_RE.sub(r"\1[redacted]", value)
    if isinstance(value, list):
        return [redact_capabilities(item) for item in value]
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            if key in {"assetToken", "asset_token", "accessToken", "refreshToken", "serve_url"}:
                result[key] = "[redacted]"
            else:
                result[key] = redact_capabilities(item)
        return result
    return value


def print_result(payload: dict[str, Any], *, json_mode: bool) -> None:
    safe_payload = redact_capabilities(payload)
    if json_mode:
        print(json.dumps(safe_payload, ensure_ascii=True))
    else:
        print(json.dumps(safe_payload, ensure_ascii=True, indent=2))


def open_durable_url(url: str) -> None:
    """Open a durable claude.ai artifact link in the system browser."""
    parsed = urlparse(url)
    hostname = (parsed.hostname or "").lower()
    if (
        parsed.scheme != "https"
        or hostname not in ARTIFACT_RESOURCE_HOSTS
        or parsed.username
        or parsed.password
        or parsed.port is not None
    ):
        raise ArtifactProtocolError("Refusing to open a non-durable artifact URL.")
    if sys.platform == "darwin":
        opener = "/usr/bin/open"
    else:
        opener = shutil.which("wslview") or shutil.which("xdg-open")
    if not opener:
        raise ArtifactSafetyError("No supported system browser opener is available.")
    try:
        result = subprocess.run(
            [opener, url],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            shell=False,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise ArtifactSafetyError("Could not open the artifact link in the system browser.") from error
    if result.returncode != 0:
        raise ArtifactSafetyError("Could not open the artifact link in the system browser.")


def validate_local_relative_path(path: object) -> str:
    if (
        not isinstance(path, str)
        or not path
        or path.startswith("/")
        or "\\" in path
        or any(part in {"", ".", ".."} for part in path.split("/"))
        or PurePosixPath(path).as_posix() != path
        or has_unsafe_text_character(path)
    ):
        raise ValueError("A sync local path must be canonical and workspace-relative.")
    return path


def read_json(root: Path, path: Path) -> dict[str, Any]:
    _source, data = read_local_file(str(path), workspace_root=root, authorized_external_paths=[])
    rel = path.relative_to(root).as_posix()
    try:
        value = json.loads(data)
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as error:
        raise ValueError(f"Sync metadata is not valid JSON: {rel}") from error
    if not isinstance(value, dict):
        raise ValueError(f"Sync metadata is not an object: {rel}")
    return value


def write_json(root: Path, path: Path, payload: dict[str, Any], *, force: bool) -> None:
    encoded = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")
    if len(encoded) > ARTIFACT_MAX_INLINE_FILE_BYTES:
        raise ArtifactSafetyError("Sync metadata exceeds the local safety limit.")
    atomic_write_local(path, encoded, force=force, workspace_root=root, authorized_external_paths=[])


def read_optional_local(root: Path, raw_path: str) -> tuple[str, bool, bytes]:
    operand = Path(raw_path).expanduser()
    if not operand.is_absolute():
        operand = root / operand
    candidate = resolve_local_path(str(operand), workspace_root=root, authorized_external_paths=[], require_file=False)
    local_path = candidate.relative_to(root).as_posix()
    if not candidate.exists():
        return local_path, False, b""
    _source, data = read_local_file(
        str(candidate),
        workspace_root=root,
        authorized_external_paths=[],
        maximum_bytes=ARTIFACT_MAX_FILE_BYTES,
    )
    return local_path, True, data


def read_snapshot(root: Path, relative_path: str) -> bytes:
    _source, data = read_local_file(
        str(root / relative_path),
        workspace_root=root,
        authorized_external_paths=[],
        maximum_bytes=ARTIFACT_MAX_FILE_BYTES,
    )
    return data


def diff_bytes(old: bytes, new: bytes, *, old_label: str, new_label: str) -> bytes:
    if old == new:
        return f"--- {old_label}\n+++ {new_label}\n(no byte changes)\n".encode()
    if b"\0" in old or b"\0" in new:
        old_sha = hashlib.sha256(old).hexdigest()
        new_sha = hashlib.sha256(new).hexdigest()
        return f"--- {old_label}\n+++ {new_label}\nbinary revisions differ: {old_sha} -> {new_sha}\n".encode()
    try:
        old_text = old.decode("utf-8").splitlines(keepends=True)
        new_text = new.decode("utf-8").splitlines(keepends=True)
    except UnicodeDecodeError:
        old_sha = hashlib.sha256(old).hexdigest()
        new_sha = hashlib.sha256(new).hexdigest()
        return f"--- {old_label}\n+++ {new_label}\nbinary revisions differ: {old_sha} -> {new_sha}\n".encode()
    rendered = "".join(difflib.unified_diff(old_text, new_text, fromfile=old_label, tofile=new_label))
    return rendered.encode("utf-8")
