"""Cross-platform Claude Design MCP compatibility bridge."""

from __future__ import annotations

import argparse
import base64
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
import time
import unicodedata
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import ParseResult, urlparse

from open_claude_design.auth import DesignAuthError, load_standalone_credential
from open_claude_design.config import (
    CLAUDE_CONFIG_DIRNAME,
    CLAUDE_CONFIG_ENV,
    CLAUDE_DESIGN_AUTHORING_CACHE_PARTS,
    CLAUDE_DESIGN_AUTHORING_CACHE_TTL_SECONDS,
    CLAUDE_DESIGN_CREDENTIAL_MAX_BYTES,
    CLAUDE_DESIGN_DURABLE_PREVIEW_HOSTS,
    CLAUDE_DESIGN_ENDPOINT,
    CLAUDE_DESIGN_HTTP_TIMEOUT_SECONDS,
    CLAUDE_DESIGN_KEYCHAIN_SERVICE,
    CLAUDE_DESIGN_KNOWN_DESTRUCTIVE_TOOLS,
    CLAUDE_DESIGN_KNOWN_MUTATING_TOOLS,
    CLAUDE_DESIGN_KNOWN_READ_ONLY_TOOLS,
    CLAUDE_DESIGN_MAX_BATCH_BYTES,
    CLAUDE_DESIGN_MAX_BATCH_FILES,
    CLAUDE_DESIGN_MAX_INLINE_FILE_BYTES,
    CLAUDE_DESIGN_MAX_PLAN_TOKEN_BYTES,
    CLAUDE_DESIGN_MAX_RESPONSE_BYTES,
    CLAUDE_DESIGN_MAX_SSE_EVENTS,
    CLAUDE_DESIGN_MAX_STDIN_BYTES,
    CLAUDE_DESIGN_MAX_SYNC_DIFF_BYTES,
    CLAUDE_DESIGN_MAX_TOOL_PAGES,
    CLAUDE_DESIGN_MAX_TOOLS,
    CLAUDE_DESIGN_MIN_WRITE_CREDENTIAL_SECONDS,
    CLAUDE_DESIGN_MUTATION_SUCCESS_KEYS,
    CLAUDE_DESIGN_NON_MUTATING_GUARDED_TOOLS,
    CLAUDE_DESIGN_PROTOCOL_VERSION,
    CLAUDE_DESIGN_SERVE_PREVIEW_HOST_SUFFIX,
    CLAUDE_DESIGN_SPECIALIZED_ONLY_TOOLS,
    CLAUDE_DESIGN_SYNC_PARTS,
    CLAUDE_DESIGN_SYNC_SCHEMA_VERSION,
    CLAUDE_DESIGN_SYNC_STALE_EXIT_CODE,
    CLAUDE_DESIGN_SYNC_UNKNOWN_EXIT_CODE,
    DEFAULT_FILE_LIST_DEPTH,
    VERSION,
)
from open_claude_design.sync import (
    REVIEW_ID_PATTERN,
    SyncPair,
    aggregate_classification,
    canonical_digest,
    classify_pair,
    content_sha256,
    parse_pairs,
    seal_receipt,
    validate_receipt,
)


class _RejectAuthenticatedRedirects(urllib.request.HTTPRedirectHandler):
    """Never forward the Design bearer token through an HTTP redirect."""

    def redirect_request(self, *_args: Any, **_kwargs: Any) -> None:
        return None


_CLAUDE_DESIGN_OPENER = urllib.request.build_opener(_RejectAuthenticatedRedirects())


def _open_claude_design(request: urllib.request.Request, *, timeout: int) -> Any:
    return _CLAUDE_DESIGN_OPENER.open(request, timeout=timeout)


class ClaudeDesignError(RuntimeError):
    """Base error for actionable Claude Design bridge failures."""


class ClaudeDesignAuthError(ClaudeDesignError):
    """Claude Design authentication is unavailable or expired."""


class ClaudeDesignProtocolError(ClaudeDesignError):
    """Claude Design returned an invalid or failed MCP response."""


class ClaudeDesignSafetyError(ClaudeDesignError):
    """A mutating tool call lacked the explicit write opt-in."""


def _has_unsafe_text_character(value: str) -> bool:
    return any(unicodedata.category(character) in {"Cc", "Cf", "Zl", "Zp"} for character in value)


def _safe_terminal_text(value: str) -> str:
    return "".join(
        character if unicodedata.category(character) not in {"Cc", "Cf", "Zl", "Zp"} else f"\\u{ord(character):04x}"
        for character in value
    )


@dataclass(frozen=True)
class ClaudeDesignCredential:
    """Minimum credential fields needed by the bridge."""

    access_token: str
    expires_at_ms: int
    scopes: tuple[str, ...]


def _parse_design_credential(payload: object, *, source: str, now_ms: int | None) -> ClaudeDesignCredential:
    """Extract only the scoped Design fields from a Claude Code credential payload."""
    design_oauth = payload.get("designOauth") if isinstance(payload, dict) else None
    if not isinstance(design_oauth, dict):
        raise ClaudeDesignAuthError(
            f"No designOauth credential is available in {source}. Run open-claude-design login and try again."
        )

    access_token = design_oauth.get("accessToken")
    expires_at_raw = design_oauth.get("expiresAt")
    if not isinstance(access_token, str) or not access_token:
        raise ClaudeDesignAuthError(
            f"No Design access token is available in {source}. Run open-claude-design login and try again."
        )
    if not isinstance(expires_at_raw, int | float):
        raise ClaudeDesignAuthError(
            f"The Design credential in {source} has no valid expiry. Run open-claude-design login and try again."
        )

    expires_at_ms = int(expires_at_raw)
    if expires_at_ms < 1_000_000_000_000:
        expires_at_ms *= 1000
    current_ms = int(time.time() * 1000) if now_ms is None else now_ms
    if expires_at_ms <= current_ms:
        raise ClaudeDesignAuthError("The Design credential expired. Run open-claude-design login and try again.")

    raw_scopes = design_oauth.get("scopes", [])
    scopes = tuple(scope for scope in raw_scopes if isinstance(scope, str)) if isinstance(raw_scopes, list) else ()
    return ClaudeDesignCredential(access_token=access_token, expires_at_ms=expires_at_ms, scopes=scopes)


def _read_secure_linux_credential_file(path: Path) -> object:
    """Read Claude Code's 0600 Linux credential file without following symlinks."""
    absolute = Path(os.path.abspath(path))
    if not absolute.is_absolute() or not absolute.name:
        raise ClaudeDesignAuthError("Claude Code's credential path is invalid.")

    directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    file_flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    directory_fd = os.open(absolute.anchor, directory_flags)
    try:
        for component in absolute.parts[1:-1]:
            next_fd = os.open(component, directory_flags, dir_fd=directory_fd)
            os.close(directory_fd)
            directory_fd = next_fd
        credential_fd = os.open(absolute.name, file_flags, dir_fd=directory_fd)
    except OSError as error:
        raise ClaudeDesignAuthError(
            f"Claude Code has no safely readable Design credential at {absolute}. "
            "Run open-claude-design login and try again."
        ) from error
    finally:
        os.close(directory_fd)

    try:
        metadata = os.fstat(credential_fd)
        if not stat.S_ISREG(metadata.st_mode):
            raise ClaudeDesignAuthError("Claude Code's credential path is not a regular file.")
        if hasattr(os, "getuid") and metadata.st_uid != os.getuid():
            raise ClaudeDesignAuthError("Claude Code's credential file is not owned by the current user.")
        if stat.S_IMODE(metadata.st_mode) & 0o077:
            raise ClaudeDesignAuthError("Claude Code's credential file permissions are too broad; expected mode 0600.")
        if metadata.st_size > CLAUDE_DESIGN_CREDENTIAL_MAX_BYTES:
            raise ClaudeDesignAuthError("Claude Code's credential file is unexpectedly large.")
        with os.fdopen(credential_fd, "r", encoding="utf-8", closefd=False) as handle:
            return json.load(handle)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ClaudeDesignAuthError("Claude Code's credential file is not valid JSON.") from error
    finally:
        os.close(credential_fd)


def read_design_credential(
    *,
    platform: str = sys.platform,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    now_ms: int | None = None,
    config_dir: Path | None = None,
    standalone_home: Path | None = None,
    standalone_reader: Callable[..., dict[str, object] | None] = load_standalone_credential,
) -> ClaudeDesignCredential:
    """Read Open Claude Design's credential, with Claude Code as a legacy fallback."""
    try:
        standalone = standalone_reader(
            platform=platform,
            home=standalone_home,
            runner=runner,
            now_ms=now_ms,
        )
    except DesignAuthError as error:
        raise ClaudeDesignAuthError(str(error)) from error
    if standalone is not None:
        return _parse_design_credential(standalone, source="Open Claude Design's credential store", now_ms=now_ms)

    if platform.startswith("linux"):
        claude_dir = config_dir
        if claude_dir is None:
            configured = os.environ.get(CLAUDE_CONFIG_ENV)
            claude_dir = Path(configured).expanduser() if configured else Path.home() / CLAUDE_CONFIG_DIRNAME
        payload = _read_secure_linux_credential_file(claude_dir / ".credentials.json")
        return _parse_design_credential(payload, source="Claude Code's credential file", now_ms=now_ms)

    if platform != "darwin":
        raise ClaudeDesignAuthError(
            "The Claude Design bridge supports macOS, Linux, and WSL2. "
            "Run open-claude-design login on one of those platforms and try again."
        )

    try:
        result = runner(
            [
                "/usr/bin/security",
                "find-generic-password",
                "-s",
                CLAUDE_DESIGN_KEYCHAIN_SERVICE,
                "-w",
            ],
            capture_output=True,
            text=True,
            shell=False,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise ClaudeDesignAuthError(
            "Could not read Claude Code credentials from macOS Keychain. Run open-claude-design login and try again."
        ) from error

    if result.returncode != 0:
        raise ClaudeDesignAuthError("No Design credential is available. Run open-claude-design login and try again.")

    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise ClaudeDesignAuthError("Claude Code's Keychain credential is not valid JSON.") from error

    return _parse_design_credential(payload, source="macOS Keychain", now_ms=now_ms)


def _validate_mcp_envelope(value: object, expected_id: int | None) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ClaudeDesignProtocolError("Claude Design returned a non-object JSON response.")
    if value.get("jsonrpc") != "2.0":
        raise ClaudeDesignProtocolError("Claude Design returned an invalid JSON-RPC version.")
    if expected_id is not None and value.get("id") != expected_id:
        raise ClaudeDesignProtocolError("Claude Design returned a response for a different request.")
    return value


def parse_mcp_response(
    body: bytes,
    content_type: str,
    *,
    expected_id: int | None = None,
) -> dict[str, Any] | None:
    """Parse a JSON or Server-Sent Events MCP response."""
    if not body:
        return None
    text = body.decode("utf-8")
    if "text/event-stream" not in content_type:
        return _validate_mcp_envelope(json.loads(text), expected_id)

    matching_event: dict[str, Any] | None = None
    event_count = 0
    data_lines: list[str] = []
    for line in text.splitlines() + [""]:
        if line.startswith("data:"):
            data_lines.append(line[5:].lstrip())
            continue
        if line == "" and data_lines:
            event_count += 1
            if event_count > CLAUDE_DESIGN_MAX_SSE_EVENTS:
                raise ClaudeDesignProtocolError("Claude Design returned too many server-sent events.")
            value = json.loads("\n".join(data_lines))
            if isinstance(value, dict) and (expected_id is None or value.get("id") == expected_id):
                if matching_event is not None and expected_id is not None:
                    raise ClaudeDesignProtocolError("Claude Design returned duplicate responses for one request.")
                matching_event = _validate_mcp_envelope(value, expected_id)
            data_lines = []
    if matching_event is None:
        raise ClaudeDesignProtocolError("Claude Design returned no matching event-stream response.")
    return matching_event


def _read_bounded_response(response: Any) -> bytes:
    content_length = response.headers.get("Content-Length")
    if content_length:
        try:
            if int(content_length) > CLAUDE_DESIGN_MAX_RESPONSE_BYTES:
                raise ClaudeDesignProtocolError("Claude Design response exceeds the local safety limit.")
        except ValueError as error:
            raise ClaudeDesignProtocolError("Claude Design returned an invalid Content-Length.") from error
    body = response.read(CLAUDE_DESIGN_MAX_RESPONSE_BYTES + 1)
    if len(body) > CLAUDE_DESIGN_MAX_RESPONSE_BYTES:
        raise ClaudeDesignProtocolError("Claude Design response exceeds the local safety limit.")
    return body


class ClaudeDesignClient:
    """Small MCP client using a scoped Claude Design credential."""

    def __init__(
        self,
        *,
        token_reader: Callable[[], str] | None = None,
        credential_reader: Callable[[], ClaudeDesignCredential] = read_design_credential,
        opener: Callable[..., Any] = _open_claude_design,
        timeout: int = CLAUDE_DESIGN_HTTP_TIMEOUT_SECONDS,
    ) -> None:
        self._token_reader = token_reader
        self._credential_reader = credential_reader
        self._credential: ClaudeDesignCredential | None = None
        self._opener = opener
        self._timeout = timeout
        self._session_id: str | None = None
        self._initialize_result: dict[str, Any] | None = None
        self._next_id = 1

    def _token(self) -> str:
        if self._token_reader is not None:
            return self._token_reader()
        if self._credential is None:
            self._credential = self._credential_reader()
        return self._credential.access_token

    def _send(self, method: str, params: dict[str, Any] | None = None, *, notification: bool = False) -> Any:
        request_body: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            request_body["params"] = params
        if not notification:
            request_body["id"] = self._next_id
            self._next_id += 1
        expected_id = request_body.get("id") if isinstance(request_body.get("id"), int) else None

        headers = {
            "Authorization": f"Bearer {self._token()}",
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
        }
        if self._session_id:
            headers["Mcp-Session-Id"] = self._session_id
        request = urllib.request.Request(
            CLAUDE_DESIGN_ENDPOINT,
            data=json.dumps(request_body).encode("utf-8"),
            headers=headers,
            method="POST",
        )

        try:
            with self._opener(request, timeout=self._timeout) as response:
                body = _read_bounded_response(response)
                session_id = response.headers.get("Mcp-Session-Id")
                if session_id:
                    self._session_id = session_id
                parsed = parse_mcp_response(
                    body,
                    response.headers.get("Content-Type", ""),
                    expected_id=expected_id,
                )
        except urllib.error.HTTPError as error:
            if error.code in {401, 403}:
                raise ClaudeDesignAuthError(
                    "Claude Design rejected the credential. Run open-claude-design login and try again."
                ) from error
            raise ClaudeDesignProtocolError(
                f"Claude Design HTTP {error.code}: {error.reason or 'request failed'}"
            ) from error
        except urllib.error.URLError as error:
            raise ClaudeDesignProtocolError(f"Could not reach Claude Design: {error.reason}") from error
        except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as error:
            raise ClaudeDesignProtocolError("Claude Design returned an unreadable MCP response.") from error

        if parsed is None:
            return None
        if "error" in parsed:
            error = parsed["error"]
            message = error.get("message", "Unknown MCP error") if isinstance(error, dict) else str(error)
            raise ClaudeDesignProtocolError(_safe_terminal_text(str(message))[:500])
        return parsed.get("result")

    def _initialize(self) -> dict[str, Any]:
        if self._initialize_result is None:
            result = self._send(
                "initialize",
                {
                    "protocolVersion": CLAUDE_DESIGN_PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": {
                        "name": "Open Claude Design",
                        "version": VERSION,
                    },
                },
            )
            if not isinstance(result, dict):
                raise ClaudeDesignProtocolError("Claude Design initialization returned no result.")
            self._initialize_result = result
            self._send("notifications/initialized", notification=True)
        return self._initialize_result

    def status(self) -> dict[str, Any]:
        """Verify authentication and return server/protocol metadata."""
        initialized = self._initialize()
        result: dict[str, Any] = {
            "authenticated": True,
            "endpoint": CLAUDE_DESIGN_ENDPOINT,
            "server": initialized.get("serverInfo"),
            "protocolVersion": initialized.get("protocolVersion"),
        }
        if self._credential is not None:
            remaining_seconds = max(0, int(self._credential.expires_at_ms / 1000 - time.time()))
            result["expiresAt"] = datetime.fromtimestamp(
                self._credential.expires_at_ms / 1000,
                tz=UTC,
            ).isoformat()
            result["expiresInSeconds"] = remaining_seconds
            result["scopes"] = list(self._credential.scopes)
        return result

    def require_write_window(
        self,
        *,
        minimum_seconds: int = CLAUDE_DESIGN_MIN_WRITE_CREDENTIAL_SECONDS,
        now_ms: int | None = None,
    ) -> None:
        """Refuse to start a remote mutation on a nearly expired credential."""
        if self._token_reader is not None:
            return
        if self._credential is None:
            self._credential = self._credential_reader()
        current_ms = int(time.time() * 1000) if now_ms is None else now_ms
        remaining_ms = self._credential.expires_at_ms - current_ms
        if remaining_ms < minimum_seconds * 1000:
            remaining_seconds = max(0, remaining_ms // 1000)
            raise ClaudeDesignAuthError(
                "The Design credential expires too soon to start a remote write "
                f"({remaining_seconds}s remaining). Run open-claude-design login, then re-read "
                "the remote files and etags before retrying."
            )

    def list_tools(self) -> list[dict[str, Any]]:
        """List the live Claude Design tool catalog."""
        self._initialize()
        tools: list[dict[str, Any]] = []
        cursor: str | None = None
        seen_cursors: set[str] = set()
        pages = 0
        while True:
            pages += 1
            if pages > CLAUDE_DESIGN_MAX_TOOL_PAGES:
                raise ClaudeDesignProtocolError("Claude Design returned too many tool pages.")
            params = {"cursor": cursor} if cursor else {}
            result = self._send("tools/list", params)
            if not isinstance(result, dict) or not isinstance(result.get("tools"), list):
                raise ClaudeDesignProtocolError("Claude Design returned an invalid tools/list result.")
            tools.extend(tool for tool in result["tools"] if isinstance(tool, dict))
            if len(tools) > CLAUDE_DESIGN_MAX_TOOLS:
                raise ClaudeDesignProtocolError("Claude Design returned too many tools.")
            next_cursor = result.get("nextCursor")
            if not isinstance(next_cursor, str) or not next_cursor:
                return tools
            if next_cursor in seen_cursors:
                raise ClaudeDesignProtocolError("Claude Design repeated a tool pagination cursor.")
            seen_cursors.add(next_cursor)
            cursor = next_cursor

    def call_tool(self, name: str, arguments: dict[str, object]) -> dict[str, Any]:
        """Call one Claude Design tool after the CLI safety gate."""
        self._initialize()
        result = self._send("tools/call", {"name": name, "arguments": arguments})
        if not isinstance(result, dict):
            raise ClaudeDesignProtocolError(f"Claude Design tool {name} returned no result.")
        return result


def _tool_by_name(tools: list[dict[str, Any]], name: str) -> dict[str, Any]:
    for tool in tools:
        if tool.get("name") == name:
            return tool
    raise ValueError(f"Claude Design tool not found: {name}")


def _compact_tool(tool: dict[str, Any]) -> dict[str, Any]:
    description = tool.get("description")
    summary = str(description).split("\n", 1)[0][:300] if description else ""
    return {
        "name": tool.get("name"),
        "description": summary,
        "annotations": tool.get("annotations", {}),
    }


def _parse_tool_arguments(raw: str | None) -> dict[str, object]:
    value = sys.stdin.read(CLAUDE_DESIGN_MAX_STDIN_BYTES + 1) if raw == "-" else (raw or "{}")
    if len(value.encode("utf-8")) > CLAUDE_DESIGN_MAX_STDIN_BYTES:
        raise ClaudeDesignSafetyError("Claude Design tool arguments exceed the local stdin safety limit.")
    try:
        parsed = json.loads(value)
    except RecursionError as error:
        raise ValueError("Claude Design tool arguments are nested too deeply.") from error
    if not isinstance(parsed, dict):
        raise ValueError("Claude Design tool arguments must be a JSON object.")
    return parsed


def _decode_read_file_result(result: dict[str, Any]) -> tuple[str, str]:
    if result.get("isError") is True:
        raise ClaudeDesignProtocolError("Claude Design read_file returned an error.")
    content = result.get("content")
    if not isinstance(content, list):
        raise ClaudeDesignProtocolError("Claude Design read_file returned no content.")
    text = next(
        (
            block.get("text")
            for block in content
            if isinstance(block, dict) and block.get("type") == "text" and isinstance(block.get("text"), str)
        ),
        None,
    )
    if text is None:
        raise ClaudeDesignProtocolError("Claude Design read_file returned no text body.")
    wrapper = re.search(
        r"<untrusted-project-content\b([^>]*)>\n?([\s\S]*?)</untrusted-project-content>",
        text,
    )
    if wrapper is None:
        raise ClaudeDesignProtocolError(
            "Claude Design did not return a complete file wrapper; the file may exceed the read cap."
        )
    etag_match = re.search(r'\betag="([^"]+)"', wrapper.group(1))
    if etag_match is None:
        raise ClaudeDesignProtocolError("Claude Design read_file returned no etag.")
    decoded = wrapper.group(2).replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")
    if len(decoded.encode("utf-8")) > CLAUDE_DESIGN_MAX_INLINE_FILE_BYTES:
        raise ClaudeDesignProtocolError("Claude Design file exceeds the 256 KiB local transfer limit.")
    return decoded, etag_match.group(1)


def _repository_root(path: Path) -> Path | None:
    """Return the enclosing Git worktree without invoking a shell."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=path,
            capture_output=True,
            text=True,
            shell=False,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    value = result.stdout.strip()
    return Path(value) if value else None


def _design_workspace_root(override: Path | None = None) -> Path:
    """Return the enclosing worktree root, falling back to the current directory."""
    root = override if override is not None else _repository_root(Path.cwd()) or Path.cwd()
    try:
        resolved = root.expanduser().resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise ClaudeDesignSafetyError("Could not resolve the current local workspace.") from error
    if not resolved.is_dir():
        raise ClaudeDesignSafetyError(f"The local workspace is not a directory: {resolved}")
    return resolved


def _absolute_local_path(raw_path: str) -> Path:
    """Normalize a local operand lexically without following symlinks."""
    try:
        expanded = Path(raw_path).expanduser()
        candidate = expanded if expanded.is_absolute() else Path.cwd() / expanded
        return Path(os.path.abspath(candidate))
    except (OSError, RuntimeError) as error:
        raise ClaudeDesignSafetyError("Could not resolve the requested local path.") from error


def _resolve_local_path(
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
        raise ClaudeDesignSafetyError(
            f"Local path is outside the current workspace: {candidate}. "
            "Pass --allow-external-local-path with that exact path only when the user explicitly authorized it."
        )

    symlink_base = workspace_root if inside_workspace else Path(candidate.anchor)
    current = symlink_base
    for part in candidate.relative_to(symlink_base).parts:
        current /= part
        if current.is_symlink():
            raise ClaudeDesignSafetyError(f"Local paths may not contain symlinks: {candidate}")

    if require_file and not candidate.is_file():
        raise ValueError(f"Local design file not found: {candidate}")
    return candidate


def _validate_plan_token_source(source: str | None) -> None:
    """Reject argv plan tokens before any client or filesystem work begins."""
    if source not in {None, "-"}:
        raise ClaudeDesignSafetyError("Existing plan tokens must be read from stdin with --plan-token -.")


def _read_supplied_plan_token(source: str | None) -> str | None:
    """Read a supplied plan token only from stdin so it never enters argv."""
    _validate_plan_token_source(source)
    if source is None:
        return None
    token = sys.stdin.read(CLAUDE_DESIGN_MAX_PLAN_TOKEN_BYTES + 1).strip()
    if len(token.encode("utf-8")) > CLAUDE_DESIGN_MAX_PLAN_TOKEN_BYTES:
        raise ClaudeDesignSafetyError("The supplied plan token exceeds the local safety limit.")
    if not token:
        raise ClaudeDesignSafetyError("No plan token was provided on stdin.")
    return token


def _safe_directory_flags() -> int:
    """Return flags that pin a directory without following its final component."""
    nofollow = getattr(os, "O_NOFOLLOW", None)
    directory = getattr(os, "O_DIRECTORY", None)
    if nofollow is None or directory is None or os.open not in os.supports_dir_fd:
        raise ClaudeDesignSafetyError("Symlink-safe local Design file access is unavailable on this platform.")
    return os.O_RDONLY | nofollow | directory | getattr(os, "O_CLOEXEC", 0)


def _raise_safe_path_error(path: Path, error: OSError) -> None:
    if error.errno in {errno.ELOOP, errno.ENOTDIR}:
        raise ClaudeDesignSafetyError(f"Local paths may not contain symlinks: {path}") from error
    if error.errno == errno.ENOENT:
        raise ValueError(f"Local design path not found: {path}") from error
    raise error


def _open_local_parent(
    path: Path,
    *,
    workspace_root: Path,
    authorized_external_paths: list[str],
    create_parents: bool,
) -> tuple[int, str, Path]:
    """Open and pin a local parent directory one non-symlink component at a time."""
    path = _resolve_local_path(
        str(path),
        workspace_root=workspace_root,
        authorized_external_paths=authorized_external_paths,
        require_file=False,
    )
    base = workspace_root if path.is_relative_to(workspace_root) else Path(path.anchor)
    relative = path.relative_to(base)
    if not relative.parts:
        raise ClaudeDesignSafetyError("A local Design file path must name a file.")

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
                    raise ValueError(f"Local design path not found: {path}") from None
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


def _read_local_file(
    path: str,
    *,
    workspace_root: Path,
    authorized_external_paths: list[str],
) -> tuple[Path, bytes]:
    """Read one regular file through pinned directory descriptors with a hard cap."""
    resolved = _resolve_local_path(
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
            raise ValueError(f"Local design file is not a regular file: {resolved}")
        chunks: list[bytes] = []
        remaining = CLAUDE_DESIGN_MAX_INLINE_FILE_BYTES + 1
        while remaining > 0:
            chunk = os.read(file_fd, min(64 * 1024, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        data = b"".join(chunks)
        if len(data) > CLAUDE_DESIGN_MAX_INLINE_FILE_BYTES:
            raise ClaudeDesignSafetyError(
                f"Local file exceeds Open Claude Design's 256 KiB inline safety cap: {resolved}. "
                "Use a server-side copy or the native Claude Design transfer path."
            )
        return resolved, data
    finally:
        if file_fd is not None:
            os.close(file_fd)
        os.close(directory_fd)


def _atomic_write_local(
    path: Path,
    data: bytes,
    *,
    force: bool,
    workspace_root: Path,
    authorized_external_paths: list[str],
) -> None:
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
            raise ClaudeDesignSafetyError(f"Local paths may not contain symlinks: {path}")
        if destination is not None and not force:
            raise ClaudeDesignSafetyError(f"Local output already exists: {path}. Pass --force to replace it.")

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
            raise ClaudeDesignSafetyError(f"Could not create an atomic local output beside: {path}")

        try:
            view = memoryview(data)
            while view:
                written = os.write(temporary_fd, view)
                if written <= 0:
                    raise OSError("Could not complete the atomic local Design file write.")
                view = view[written:]
            os.fsync(temporary_fd)
        finally:
            os.close(temporary_fd)

        try:
            destination = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        except FileNotFoundError:
            destination = None
        if destination is not None and stat.S_ISLNK(destination.st_mode):
            raise ClaudeDesignSafetyError(f"Local paths may not contain symlinks: {path}")
        if destination is not None and not force:
            raise ClaudeDesignSafetyError(f"Local output already exists: {path}. Pass --force to replace it.")
        os.replace(temporary_name, name, src_dir_fd=directory_fd, dst_dir_fd=directory_fd)
        temporary_name = None
    finally:
        if temporary_name is not None:
            with contextlib.suppress(FileNotFoundError):
                os.unlink(temporary_name, dir_fd=directory_fd)
        os.close(directory_fd)


def _parse_mappings(values: list[str], *, option: str) -> dict[str, str]:
    mappings: dict[str, str] = {}
    for value in values:
        if "=" not in value:
            raise ValueError(f"{option} expects REMOTE_PATH=VALUE, got: {value}")
        remote_path, mapped = value.split("=", 1)
        if not remote_path or not mapped:
            raise ValueError(f"{option} expects non-empty REMOTE_PATH=VALUE, got: {value}")
        if remote_path in mappings:
            raise ValueError(f"Duplicate remote path for {option}: {remote_path}")
        mappings[remote_path] = mapped
    return mappings


def _validate_remote_path(path: str) -> str:
    parts = path.split("/")
    if (
        not path
        or path.startswith("/")
        or "\\" in path
        or any(part in {"", ".", ".."} for part in parts)
        or PurePosixPath(path).as_posix() != path
        or _has_unsafe_text_character(path)
    ):
        raise ValueError(f"Claude Design paths must be canonical non-empty project-relative paths: {path}")
    return path


def _tool_result_value(result: dict[str, Any], *, tool: str) -> Any:
    if result.get("isError") is True:
        raise ClaudeDesignProtocolError(f"Claude Design {tool} returned an error.")
    structured = result.get("structuredContent")
    if isinstance(structured, dict | list):
        return structured
    content = result.get("content")
    if isinstance(content, list):
        for block in content:
            if not isinstance(block, dict) or block.get("type") != "text" or not isinstance(block.get("text"), str):
                continue
            text = block["text"].lstrip()
            try:
                parsed, _end = json.JSONDecoder().raw_decode(text)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict | list):
                return parsed
    if any(key in result for key in ("plan_token", "base_etags", "status", "etags", "paths")):
        return result
    raise ClaudeDesignProtocolError(f"Claude Design {tool} returned no structured result.")


def _tool_result_object(result: dict[str, Any], *, tool: str) -> dict[str, Any]:
    value = _tool_result_value(result, tool=tool)
    if not isinstance(value, dict):
        raise ClaudeDesignProtocolError(f"Claude Design {tool} returned a non-object result.")
    return value


def _tool_result_text(result: dict[str, Any], *, tool: str) -> str:
    if result.get("isError") is True:
        raise ClaudeDesignProtocolError(f"Claude Design {tool} returned an error.")
    content = result.get("content")
    if not isinstance(content, list):
        raise ClaudeDesignProtocolError(f"Claude Design {tool} returned no text content.")
    text = next(
        (
            block.get("text")
            for block in content
            if isinstance(block, dict) and block.get("type") == "text" and isinstance(block.get("text"), str)
        ),
        None,
    )
    if not isinstance(text, str) or not text:
        raise ClaudeDesignProtocolError(f"Claude Design {tool} returned no text content.")
    return text


def _authoring_cache_payload(
    *,
    root: Path,
    project_id: str,
    design_system_id: str | None,
    skill: str,
    fetched_at: int,
    prompt_path: Path,
    prompt_data: bytes,
    skill_path: Path,
    skill_data: bytes,
    cached: bool,
) -> dict[str, object]:
    return {
        "cached": cached,
        "project_id": project_id,
        "design_system_id": design_system_id,
        "authoring_skill": skill,
        "fetched_at": fetched_at,
        "expires_at": fetched_at + CLAUDE_DESIGN_AUTHORING_CACHE_TTL_SECONDS,
        "prompt": {
            "path": prompt_path.relative_to(root).as_posix(),
            "sha256": hashlib.sha256(prompt_data).hexdigest(),
            "bytes": len(prompt_data),
        },
        "skill": {
            "path": skill_path.relative_to(root).as_posix(),
            "sha256": hashlib.sha256(skill_data).hexdigest(),
            "bytes": len(skill_data),
        },
    }


def _read_authoring_cache(
    *,
    root: Path,
    metadata_path: Path,
    project_id: str,
    design_system_id: str | None,
    skill: str,
    now: int,
) -> dict[str, object] | None:
    if not metadata_path.is_file():
        return None
    try:
        _metadata_file, metadata_data = _read_local_file(
            str(metadata_path), workspace_root=root, authorized_external_paths=[]
        )
        metadata = json.loads(metadata_data)
        if not isinstance(metadata, dict):
            return None
        if (
            metadata.get("project_id") != project_id
            or metadata.get("design_system_id") != design_system_id
            or metadata.get("authoring_skill") != skill
            or not isinstance(metadata.get("fetched_at"), int)
            or not isinstance(metadata.get("expires_at"), int)
            or metadata["expires_at"] <= now
        ):
            return None
        prompt = metadata.get("prompt")
        skill_entry = metadata.get("skill")
        if not isinstance(prompt, dict) or not isinstance(skill_entry, dict):
            return None
        prompt_path = root / str(prompt.get("path", ""))
        skill_path = root / str(skill_entry.get("path", ""))
        _prompt_file, prompt_data = _read_local_file(
            str(prompt_path), workspace_root=root, authorized_external_paths=[]
        )
        _skill_file, skill_data = _read_local_file(str(skill_path), workspace_root=root, authorized_external_paths=[])
        if hashlib.sha256(prompt_data).hexdigest() != prompt.get("sha256") or hashlib.sha256(
            skill_data
        ).hexdigest() != skill_entry.get("sha256"):
            return None
        return _authoring_cache_payload(
            root=root,
            project_id=project_id,
            design_system_id=design_system_id,
            skill=skill,
            fetched_at=metadata["fetched_at"],
            prompt_path=prompt_path,
            prompt_data=prompt_data,
            skill_path=skill_path,
            skill_data=skill_data,
            cached=True,
        )
    except (ClaudeDesignError, OSError, ValueError, json.JSONDecodeError):
        return None


def _authoring_context_payload(args: argparse.Namespace, client: Any, *, root: Path) -> dict[str, object]:
    for label, value in (("project id", args.project_id), ("authoring skill", args.skill)):
        if not isinstance(value, str) or not value or len(value) > 256 or _has_unsafe_text_character(value):
            raise ValueError(f"Claude Design {label} is invalid.")
    if args.design_system_id is not None and (
        not isinstance(args.design_system_id, str)
        or not args.design_system_id
        or len(args.design_system_id) > 256
        or _has_unsafe_text_character(args.design_system_id)
    ):
        raise ValueError("Claude Design design system id is invalid.")
    if re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", args.skill) is None:
        raise ValueError("Claude Design authoring skill must be a lowercase hyphenated name.")

    owned_cache_root = root / CLAUDE_DESIGN_AUTHORING_CACHE_PARTS[0]
    ignore_path = owned_cache_root / ".gitignore"
    if ignore_path.exists():
        _ignore_file, ignore_data = _read_local_file(
            str(ignore_path), workspace_root=root, authorized_external_paths=[]
        )
        if "*" not in ignore_data.decode("utf-8").splitlines():
            raise ClaudeDesignSafetyError(
                f"The Open Claude Design cache ignore rule is missing from {ignore_path}; "
                "refusing to cache project context."
            )
    else:
        _atomic_write_local(ignore_path, b"*\n", force=False, workspace_root=root, authorized_external_paths=[])

    design_system_id = args.design_system_id or ""
    key = hashlib.sha256(f"{args.project_id}\0{design_system_id}\0{args.skill}".encode()).hexdigest()[:24]
    cache_root = root.joinpath(*CLAUDE_DESIGN_AUTHORING_CACHE_PARTS, key)
    prompt_path = cache_root / "prompt.md"
    skill_path = cache_root / f"{args.skill}.md"
    metadata_path = cache_root / "metadata.json"
    now = int(time.time())
    if not args.refresh:
        cached = _read_authoring_cache(
            root=root,
            metadata_path=metadata_path,
            project_id=args.project_id,
            design_system_id=args.design_system_id,
            skill=args.skill,
            now=now,
        )
        if cached is not None:
            return cached

    prompt_arguments: dict[str, object] = {"project_id": args.project_id}
    if args.design_system_id is not None:
        prompt_arguments["design_system_id"] = args.design_system_id
    prompt_text = _tool_result_text(
        client.call_tool("get_claude_design_prompt", prompt_arguments),
        tool="get_claude_design_prompt",
    )
    skill_text = _tool_result_text(
        client.call_tool("read_design_skill", {"skill": args.skill}),
        tool="read_design_skill",
    )
    prompt_data = prompt_text.encode("utf-8")
    skill_data = skill_text.encode("utf-8")
    payload = _authoring_cache_payload(
        root=root,
        project_id=args.project_id,
        design_system_id=args.design_system_id,
        skill=args.skill,
        fetched_at=now,
        prompt_path=prompt_path,
        prompt_data=prompt_data,
        skill_path=skill_path,
        skill_data=skill_data,
        cached=False,
    )
    _atomic_write_local(prompt_path, prompt_data, force=True, workspace_root=root, authorized_external_paths=[])
    _atomic_write_local(skill_path, skill_data, force=True, workspace_root=root, authorized_external_paths=[])
    _atomic_write_local(
        metadata_path,
        json.dumps(payload, ensure_ascii=True, sort_keys=True).encode("utf-8"),
        force=True,
        workspace_root=root,
        authorized_external_paths=[],
    )
    return payload


def _local_write_payload(
    args: argparse.Namespace,
    client: Any,
    *,
    workspace_root: Path,
) -> dict[str, object]:
    plan_token = _read_supplied_plan_token(getattr(args, "plan_token", None))
    file_paths = _parse_mappings(args.files, option="--file")
    etags = _parse_mappings(args.if_matches, option="--if-match")
    if len(file_paths) > CLAUDE_DESIGN_MAX_BATCH_FILES:
        raise ClaudeDesignSafetyError("A push batch contains too many files.")
    if set(file_paths) != set(etags):
        missing = sorted(set(file_paths) - set(etags))
        extra = sorted(set(etags) - set(file_paths))
        raise ClaudeDesignSafetyError(
            f"Every pushed path needs exactly one current etag. Missing: {missing or 'none'}; extra: {extra or 'none'}."
        )
    files: list[dict[str, object]] = []
    total_bytes = 0
    for remote_path, local_path in file_paths.items():
        _validate_remote_path(remote_path)
        source, data = _read_local_file(
            local_path,
            workspace_root=workspace_root,
            authorized_external_paths=getattr(args, "external_local_paths", []),
        )
        total_bytes += len(data)
        if total_bytes > CLAUDE_DESIGN_MAX_BATCH_BYTES:
            raise ClaudeDesignSafetyError("A push batch exceeds the aggregate local byte limit.")
        file_payload: dict[str, object] = {"path": remote_path, "if_match": etags[remote_path]}
        try:
            file_payload["data"] = data.decode("utf-8")
        except UnicodeDecodeError:
            file_payload["data"] = base64.b64encode(data).decode("ascii")
            file_payload["encoding"] = "base64"
        files.append(file_payload)

    if plan_token is None:
        planned = _tool_result_object(
            client.call_tool(
                "finalize_plan",
                {
                    "project_id": args.project_id,
                    "scope": "paths",
                    "writes": list(file_paths),
                    "deletes": [],
                },
            ),
            tool="finalize_plan",
        )
        plan_token = planned.get("plan_token")
        base_etags = planned.get("base_etags")
        if not isinstance(plan_token, str) or not plan_token:
            raise ClaudeDesignProtocolError("Claude Design finalize_plan returned no plan token.")
        if not isinstance(base_etags, dict):
            raise ClaudeDesignProtocolError("Claude Design finalize_plan returned no base etags.")
        conflicts = [
            path
            for path, expected in etags.items()
            if not isinstance(base_etags.get(path), str) or base_etags.get(path) != expected
        ]
        if conflicts:
            raise ClaudeDesignSafetyError(
                "Claude Design changed after the supplied etags were read. Pull and reconcile first: "
                + ", ".join(conflicts)
            )
    return {"project_id": args.project_id, "plan_token": plan_token, "files": files}


def _local_delete_payload(
    args: argparse.Namespace,
    client: Any,
    *,
    workspace_root: Path,
) -> tuple[dict[str, object], list[str]]:
    paths = list(args.paths)
    if len(paths) > CLAUDE_DESIGN_MAX_BATCH_FILES:
        raise ClaudeDesignSafetyError("A delete batch contains too many files.")
    if len(paths) != len(set(paths)):
        raise ClaudeDesignSafetyError("Every --path may appear only once in a delete batch.")
    confirmations = list(args.confirm_deletes)
    if len(confirmations) != len(set(confirmations)) or set(confirmations) != set(paths):
        raise ClaudeDesignSafetyError(
            "Every --path requires one matching --confirm-delete assertion based on the user's exact authorization."
        )
    etags = _parse_mappings(args.if_matches, option="--if-match")
    if set(paths) != set(etags):
        missing = sorted(set(paths) - set(etags))
        extra = sorted(set(etags) - set(paths))
        raise ClaudeDesignSafetyError(
            f"Every deleted path needs exactly one current etag. Missing: {missing or 'none'}; "
            f"extra: {extra or 'none'}."
        )
    for path in paths:
        _validate_remote_path(path)
        if etags[path] == "0":
            raise ClaudeDesignSafetyError(f"A delete etag cannot be 0 because the path must exist: {path}")

    backup_operand = Path(args.backup_dir).expanduser()
    if not backup_operand.is_absolute():
        backup_operand = workspace_root / backup_operand
    backup_root = _resolve_local_path(
        str(backup_operand),
        workspace_root=workspace_root,
        authorized_external_paths=[],
        require_file=False,
    )
    safe_project = re.sub(r"[^A-Za-z0-9._-]", "_", args.project_id)
    backups: list[str] = []
    total_backup_bytes = 0
    for path in paths:
        read_result = client.call_tool("read_file", {"project_id": args.project_id, "path": path})
        decoded, current_etag = _decode_read_file_result(read_result)
        if current_etag != etags[path]:
            raise ClaudeDesignSafetyError(
                f"Claude Design changed before the delete backup was created: {path}. Re-read and reconcile first."
            )
        etag_key = hashlib.sha256(current_etag.encode("utf-8")).hexdigest()[:12]
        target = backup_root / safe_project / etag_key / Path(*path.split("/"))
        encoded = decoded.encode("utf-8")
        total_backup_bytes += len(encoded)
        if total_backup_bytes > CLAUDE_DESIGN_MAX_BATCH_BYTES:
            raise ClaudeDesignSafetyError("Delete recovery backups exceed the aggregate local byte limit.")
        if target.exists():
            _existing_path, existing = _read_local_file(
                str(target),
                workspace_root=workspace_root,
                authorized_external_paths=[],
            )
            if existing != encoded:
                raise ClaudeDesignSafetyError(f"A different delete backup already exists: {target}")
        else:
            _atomic_write_local(
                target,
                encoded,
                force=False,
                workspace_root=workspace_root,
                authorized_external_paths=[],
            )
        backups.append(str(target))

    planned = _tool_result_object(
        client.call_tool(
            "finalize_plan",
            {
                "project_id": args.project_id,
                "scope": "paths",
                "writes": [],
                "deletes": paths,
            },
        ),
        tool="finalize_plan",
    )
    plan_token = planned.get("plan_token")
    if not isinstance(plan_token, str) or not plan_token:
        raise ClaudeDesignProtocolError("Claude Design finalize_plan returned no plan token.")
    return (
        {
            "project_id": args.project_id,
            "plan_token": plan_token,
            "files": [{"path": path, "if_match": etags[path]} for path in paths],
        },
        backups,
    )


def _redact_capabilities(value: Any) -> Any:
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            normalized = re.sub(r"[^a-z0-9]", "", str(key).lower())
            if normalized in {
                "accesstoken",
                "authorizationcode",
                "bearertoken",
                "plantoken",
                "refreshtoken",
                "serveurl",
            }:
                redacted[str(key)] = "<redacted>"
            else:
                redacted[str(key)] = _redact_capabilities(item)
        return redacted
    if isinstance(value, list):
        return [_redact_capabilities(item) for item in value]
    if isinstance(value, str) and value.lstrip().startswith(("{", "[")):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return value
        return json.dumps(_redact_capabilities(parsed), ensure_ascii=False)
    return value


def _print_design_result(payload: dict[str, Any], *, json_mode: bool) -> None:
    safe_payload = _redact_capabilities(payload)
    if json_mode:
        print(json.dumps(safe_payload, ensure_ascii=True))
    else:
        print(json.dumps(safe_payload, ensure_ascii=True, indent=2))


def _require_write_window(client: Any) -> None:
    preflight = getattr(client, "require_write_window", None)
    if callable(preflight):
        preflight()


def _paths_from_mutation_value(value: dict[str, Any]) -> set[str]:
    paths: set[str] = set()
    direct_path = value.get("path")
    if isinstance(direct_path, str):
        paths.add(direct_path)
    for key in ("paths", "writes", "deletes"):
        items = value.get(key)
        if isinstance(items, list):
            paths.update(item for item in items if isinstance(item, str))
    files = value.get("files")
    if isinstance(files, list):
        paths.update(item["path"] for item in files if isinstance(item, dict) and isinstance(item.get("path"), str))
    etags = value.get("etags")
    if isinstance(etags, dict):
        paths.update(path for path in etags if isinstance(path, str))
    return paths


def _mutation_result_matches_request(
    value: dict[str, Any],
    *,
    tool: str,
    arguments: dict[str, object] | None,
) -> bool:
    status = value.get("status")
    if any(value.get(key) for key in ("error", "errors", "failed", "failure", "refused")):
        return False
    successful_status = isinstance(status, str) and status.lower() in {
        "complete",
        "completed",
        "created",
        "deleted",
        "ok",
        "success",
        "succeeded",
        "updated",
        "written",
    }
    if isinstance(status, str) and status.lower() in {"conflict", "error", "failed", "failure"}:
        return False
    if status is not None and not successful_status:
        return False
    if arguments is None:
        return successful_status

    expected_project = arguments.get("project_id")
    returned_project = value.get("project_id", value.get("projectId"))
    if expected_project is not None and returned_project is not None and returned_project != expected_project:
        return False

    expected_paths = _paths_from_mutation_value(arguments)
    returned_paths = _paths_from_mutation_value(value)
    if returned_paths and returned_paths != expected_paths:
        return False
    if tool in {"write_files", "delete_files"} and expected_paths and returned_paths != expected_paths:
        return False
    named_evidence = CLAUDE_DESIGN_MUTATION_SUCCESS_KEYS.get(tool, frozenset())
    return bool(
        successful_status
        or returned_paths
        or returned_project is not None
        or any(key in value for key in named_evidence)
    )


def _tool_exit_code(
    result: dict[str, Any],
    *,
    tool: str,
    mutation: bool = False,
    arguments: dict[str, object] | None = None,
) -> int:
    if result.get("isError") is True:
        return 2
    try:
        value = _tool_result_value(result, tool=tool)
    except ClaudeDesignProtocolError:
        return 2 if mutation else 0
    if mutation and (not isinstance(value, dict) or not value):
        return 2
    if (
        mutation
        and isinstance(value, dict)
        and not _mutation_result_matches_request(
            value,
            tool=tool,
            arguments=arguments,
        )
    ):
        return 2
    return 0


def _verify_deleted_paths(client: Any, project_id: str, paths: list[str]) -> dict[str, object]:
    remaining: list[str] = []
    checked_parents: list[str] = []
    for parent in sorted({PurePosixPath(path).parent.as_posix() for path in paths}):
        remote_parent = "" if parent == "." else parent
        listed = client.call_tool(
            "list_files",
            {"project_id": project_id, "path": remote_parent, "depth": 1},
        )
        entries = _tool_result_value(listed, tool="list_files")
        if not isinstance(entries, list):
            raise ClaudeDesignProtocolError("Claude Design list_files returned no array after deletion.")
        checked_parents.append(remote_parent)
        present: set[str] = set()
        for item in entries:
            if not isinstance(item, dict) or item.get("type") != "file" or not isinstance(item.get("path"), str):
                continue
            try:
                present.add(_validate_remote_path(item["path"]))
            except ValueError as error:
                raise ClaudeDesignProtocolError(
                    "Claude Design list_files returned a noncanonical path after deletion."
                ) from error
        remaining.extend(path for path in paths if PurePosixPath(path).parent.as_posix() == parent and path in present)
    return {
        "verifiedAbsent": not remaining,
        "checkedParents": checked_parents,
        "remainingPaths": sorted(remaining),
    }


def _validate_durable_preview_url(url: str) -> None:
    parsed = _strict_https_preview_url(url)
    if parsed.hostname not in CLAUDE_DESIGN_DURABLE_PREVIEW_HOSTS:
        raise ClaudeDesignProtocolError("Claude Design returned an invalid durable preview URL.")


def _strict_https_preview_url(url: str) -> ParseResult:
    if "\\" in url or _has_unsafe_text_character(url):
        raise ClaudeDesignProtocolError("Claude Design returned an invalid preview URL.")
    parsed = urlparse(url)
    if (
        parsed.scheme != "https"
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
        or re.fullmatch(r"[A-Za-z0-9.-]+(?::443)?", parsed.netloc) is None
    ):
        raise ClaudeDesignProtocolError("Claude Design returned an invalid preview URL.")
    try:
        port = parsed.port
    except ValueError as error:
        raise ClaudeDesignProtocolError("Claude Design returned an invalid preview URL.") from error
    if port not in {None, 443}:
        raise ClaudeDesignProtocolError("Claude Design returned an invalid preview URL.")
    return parsed


def _validate_serve_preview_url(url: str) -> None:
    parsed = _strict_https_preview_url(url)
    hostname = parsed.hostname or ""
    if not (
        hostname == CLAUDE_DESIGN_SERVE_PREVIEW_HOST_SUFFIX
        or hostname.endswith(f".{CLAUDE_DESIGN_SERVE_PREVIEW_HOST_SUFFIX}")
    ):
        raise ClaudeDesignProtocolError("Claude Design returned an invalid short-lived preview URL.")


def _open_preview_url(url: str) -> None:
    _validate_serve_preview_url(url)
    if sys.platform == "darwin":
        opener = "/usr/bin/open"
    else:
        opener = shutil.which("wslview") or shutil.which("xdg-open")
    if not opener:
        raise ClaudeDesignSafetyError("No supported system browser opener is available.")
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
        raise ClaudeDesignSafetyError("Could not open the durable Claude Design preview.") from error
    if result.returncode != 0:
        raise ClaudeDesignSafetyError("Could not open the durable Claude Design preview.")


def _planned_call_payload(args: argparse.Namespace, client: Any) -> dict[str, object]:
    if args.tool not in {"copy_files", "create_support_js"}:
        raise ClaudeDesignSafetyError(
            "planned-call supports copy_files and create_support_js; use push or delete for file mutations."
        )
    arguments = _parse_tool_arguments(args.args)
    if "plan_token" in arguments:
        raise ClaudeDesignSafetyError("planned-call creates and consumes its plan token internally.")
    supplied_project = arguments.get("project_id")
    if supplied_project not in {None, args.project_id}:
        raise ClaudeDesignSafetyError("The planned-call project_id does not match the positional project.")
    arguments["project_id"] = args.project_id

    writes = list(args.writes)
    if len(writes) != len(set(writes)) or len(writes) > CLAUDE_DESIGN_MAX_BATCH_FILES:
        raise ClaudeDesignSafetyError("planned-call write paths must be unique and within the batch limit.")
    for path in writes:
        _validate_remote_path(path)

    expected_etags: dict[str, str] = {}
    if args.tool == "create_support_js":
        path = arguments.get("path")
        if not isinstance(path, str) or {path} != set(writes):
            raise ClaudeDesignSafetyError("create_support_js requires one matching --write path.")
        if_match = arguments.get("if_match")
        if not isinstance(if_match, str) or not if_match:
            raise ClaudeDesignSafetyError("create_support_js requires a current if_match value in --args.")
        expected_etags[path] = if_match
    else:
        files = arguments.get("files")
        if not isinstance(files, list) or not files or not all(isinstance(item, dict) for item in files):
            raise ClaudeDesignSafetyError("copy_files requires a non-empty files array in --args.")
        destinations: set[str] = set()
        for item in files:
            destination = item.get("dest")
            if not isinstance(destination, str):
                raise ClaudeDesignSafetyError("Every copy_files item requires a destination path.")
            _validate_remote_path(destination)
            destinations.add(destination)
            if_match = item.get("if_match")
            leaf_if_match = item.get("leaf_if_match")
            if isinstance(if_match, str) and if_match:
                expected_etags[destination] = if_match
            elif not isinstance(leaf_if_match, dict) or not leaf_if_match:
                raise ClaudeDesignSafetyError(
                    "Every copy_files item requires if_match or a non-empty leaf_if_match map."
                )
        if destinations != set(writes):
            raise ClaudeDesignSafetyError("Every copy destination needs one matching --write declaration.")

    planned = _tool_result_object(
        client.call_tool(
            "finalize_plan",
            {
                "project_id": args.project_id,
                "scope": "paths",
                "writes": writes,
                "deletes": [],
            },
        ),
        tool="finalize_plan",
    )
    plan_token = planned.get("plan_token")
    base_etags = planned.get("base_etags")
    if not isinstance(plan_token, str) or not plan_token or not isinstance(base_etags, dict):
        raise ClaudeDesignProtocolError("Claude Design finalize_plan returned an incomplete write plan.")
    conflicts = [path for path, etag in expected_etags.items() if base_etags.get(path) != etag]
    if conflicts:
        raise ClaudeDesignSafetyError(
            "Claude Design changed after the supplied etags were read. Pull and reconcile first: "
            + ", ".join(sorted(conflicts))
        )
    arguments["plan_token"] = plan_token
    return arguments


def _run_files_command(args: argparse.Namespace, client: Any) -> int:
    """Render normalized list_files output without returning file bodies."""
    result = client.call_tool(
        "list_files",
        {"project_id": args.project_id, "path": args.path, "depth": args.depth},
    )
    files = _tool_result_value(result, tool="list_files")
    if not isinstance(files, list) or not all(isinstance(item, dict) for item in files):
        raise ClaudeDesignProtocolError("Claude Design list_files returned a non-array result.")
    if args.tsv:
        for item in files:
            if item.get("type") != "file":
                continue
            path = item.get("path")
            etag = item.get("etag")
            size = item.get("size")
            if not isinstance(path, str) or not isinstance(etag, str) or not isinstance(size, int | float):
                raise ClaudeDesignProtocolError("Claude Design list_files returned an incomplete file entry.")
            try:
                _validate_remote_path(path)
            except ValueError as error:
                raise ClaudeDesignProtocolError(
                    "Claude Design list_files returned a path unsafe for TSV output."
                ) from error
            if _has_unsafe_text_character(path) or _has_unsafe_text_character(etag):
                raise ClaudeDesignProtocolError("Claude Design list_files returned a path unsafe for TSV output.")
            print(f"{path}\t{etag}\t{int(size)}")
    else:
        _print_design_result({"files": files}, json_mode=args.json)
    return 0


def _sync_root(root: Path) -> Path:
    return root.joinpath(*CLAUDE_DESIGN_SYNC_PARTS)


def _ensure_sync_state_ignored(root: Path) -> None:
    """Keep generated sync state out of Git status without editing tracked ignore files."""
    marker = _sync_root(root) / ".git-exclude-ready"
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
                existing = os.read(descriptor, CLAUDE_DESIGN_MAX_STDIN_BYTES + 1)
                if len(existing) > CLAUDE_DESIGN_MAX_STDIN_BYTES:
                    raise OSError("Git's local exclude file exceeds the safety limit.")
                rule = b".open-claude-design/"
                if rule not in {line.strip() for line in existing.splitlines()}:
                    suffix = b"" if not existing or existing.endswith(b"\n") else b"\n"
                    os.lseek(descriptor, 0, os.SEEK_END)
                    pending = memoryview(suffix + rule + b"\n")
                    while pending:
                        written = os.write(descriptor, pending)
                        if written <= 0:
                            raise OSError("Could not update Git's local exclude file for sync state.")
                        pending = pending[written:]
                    os.fsync(descriptor)
            finally:
                os.close(descriptor)
    except (OSError, RuntimeError, subprocess.SubprocessError):
        pass
    _atomic_write_local(
        marker,
        b"ready\n",
        force=marker.exists(),
        workspace_root=root,
        authorized_external_paths=[],
    )


def _sync_review_root(root: Path, review_id: str) -> Path:
    if REVIEW_ID_PATTERN.fullmatch(review_id) is None:
        raise ValueError("A sync review id must be exactly 32 lowercase hexadecimal characters.")
    return _sync_root(root) / "reviews" / review_id


def _sync_receipt_path(root: Path, review_id: str) -> Path:
    return _sync_review_root(root, review_id) / "receipt.json"


def _sync_relative(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def _sync_validate_local_relative_path(path: object) -> str:
    if (
        not isinstance(path, str)
        or not path
        or path.startswith("/")
        or "\\" in path
        or any(part in {"", ".", ".."} for part in path.split("/"))
        or PurePosixPath(path).as_posix() != path
        or _has_unsafe_text_character(path)
    ):
        raise ValueError("A sync local path must be canonical and workspace-relative.")
    return path


def _sync_read_json(root: Path, path: Path) -> dict[str, Any]:
    _source, data = _read_local_file(
        str(path),
        workspace_root=root,
        authorized_external_paths=[],
    )
    try:
        value = json.loads(data)
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as error:
        raise ValueError(f"Open Claude Design sync metadata is not valid JSON: {_sync_relative(root, path)}") from error
    if not isinstance(value, dict):
        raise ValueError(f"Open Claude Design sync metadata is not an object: {_sync_relative(root, path)}")
    return value


def _sync_write_json(root: Path, path: Path, payload: dict[str, Any], *, force: bool) -> None:
    encoded = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")
    if len(encoded) > CLAUDE_DESIGN_MAX_INLINE_FILE_BYTES:
        raise ClaudeDesignSafetyError("Open Claude Design sync metadata exceeds the local safety limit.")
    _atomic_write_local(
        path,
        encoded,
        force=force,
        workspace_root=root,
        authorized_external_paths=[],
    )


def _sync_load_receipt(root: Path, review_id: str) -> dict[str, Any]:
    path = _sync_receipt_path(root, review_id)
    if not path.exists():
        raise ValueError(f"Sync review not found: {review_id}")
    receipt = validate_receipt(_sync_read_json(root, path), review_id=review_id)
    project_id = receipt.get("project_id")
    classification = receipt.get("classification")
    if not isinstance(project_id, str) or not project_id or _has_unsafe_text_character(project_id):
        raise ValueError("The sync review receipt has an invalid project id.")
    if classification not in {"unchanged", "remote-only", "local-only", "both-changed", "unknown"}:
        raise ValueError("The sync review receipt has an invalid classification.")
    active = receipt["state"] != "complete"
    snapshot_prefix = f"{_sync_relative(root, _sync_review_root(root, review_id))}/snapshots/"
    for pair in receipt["pairs"]:
        remote_path = pair.get("remote_path")
        local_path = pair.get("local_path")
        if not isinstance(remote_path, str):
            raise ValueError("The sync review receipt has an invalid remote path.")
        _validate_remote_path(remote_path)
        _sync_validate_local_relative_path(local_path)
        for exists_key, hash_key in (("remote_exists", "remote_sha256"), ("local_exists", "local_sha256")):
            exists = pair.get(exists_key)
            digest = pair.get(hash_key)
            if not isinstance(exists, bool):
                raise ValueError("The sync review receipt has an invalid file-existence revision.")
            if exists and (not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None):
                raise ValueError("The sync review receipt has an invalid content revision.")
            if not exists and digest is not None:
                raise ValueError("The sync review receipt has an invalid missing-file revision.")
        etag = pair.get("remote_etag")
        if not isinstance(etag, str) or not etag or _has_unsafe_text_character(etag):
            raise ValueError("The sync review receipt has an invalid remote etag.")
        if active:
            for snapshot_key in ("remote_snapshot", "local_snapshot"):
                snapshot = pair.get(snapshot_key)
                if not isinstance(snapshot, str):
                    raise ValueError("The sync review receipt has an invalid snapshot path.")
                _sync_validate_local_relative_path(snapshot)
                if not snapshot.startswith(snapshot_prefix) or PurePosixPath(snapshot).parent.as_posix() != (
                    snapshot_prefix.removesuffix("/")
                ):
                    raise ValueError("The sync review receipt has an invalid snapshot path.")
    return receipt


def _sync_save_receipt(root: Path, receipt: dict[str, Any]) -> dict[str, Any]:
    review_id = str(receipt["review_id"])
    sealed = seal_receipt(receipt)
    receipt_path = _sync_receipt_path(root, review_id)
    _sync_write_json(root, receipt_path, sealed, force=receipt_path.exists())
    return sealed


def _sync_ledger_path(root: Path, *, project_id: str, remote_path: str, local_path: str) -> Path:
    key = hashlib.sha256(f"{project_id}\0{remote_path}\0{local_path}".encode()).hexdigest()[:32]
    return _sync_root(root) / "ledger" / f"{key}.json"


def _sync_load_ledger(
    root: Path,
    *,
    project_id: str,
    remote_path: str,
    local_path: str,
) -> dict[str, Any] | None:
    path = _sync_ledger_path(root, project_id=project_id, remote_path=remote_path, local_path=local_path)
    if not path.exists():
        return None
    payload = _sync_read_json(root, path)
    digest = payload.get("review_digest")
    if not isinstance(digest, str) or digest != canonical_digest(payload):
        raise ValueError(f"The sync ledger changed unexpectedly: {_sync_relative(root, path)}")
    if (
        payload.get("project_id") != project_id
        or payload.get("remote_path") != remote_path
        or payload.get("local_path") != local_path
    ):
        raise ValueError(f"The sync ledger identity changed unexpectedly: {_sync_relative(root, path)}")
    return payload


def _sync_save_ledger(root: Path, payload: dict[str, Any]) -> None:
    path = _sync_ledger_path(
        root,
        project_id=str(payload["project_id"]),
        remote_path=str(payload["remote_path"]),
        local_path=str(payload["local_path"]),
    )
    sealed = seal_receipt(payload)
    _sync_write_json(root, path, sealed, force=path.exists())


def _sync_optional_local(root: Path, raw_path: str) -> tuple[str, bool, bytes]:
    operand = Path(raw_path).expanduser()
    if not operand.is_absolute():
        operand = root / operand
    candidate = _resolve_local_path(
        str(operand),
        workspace_root=root,
        authorized_external_paths=[],
        require_file=False,
    )
    local_path = _sync_relative(root, candidate)
    if not candidate.exists():
        return local_path, False, b""
    _source, data = _read_local_file(
        str(candidate),
        workspace_root=root,
        authorized_external_paths=[],
    )
    return local_path, True, data


def _sync_remote_metadata(client: Any, project_id: str, remote_paths: set[str]) -> dict[str, dict[str, Any]]:
    metadata = {path: {"exists": False, "etag": "0"} for path in remote_paths}
    parents = {
        "" if PurePosixPath(path).parent.as_posix() == "." else PurePosixPath(path).parent.as_posix()
        for path in remote_paths
    }
    for parent in sorted(parents):
        result = client.call_tool(
            "list_files",
            {"project_id": project_id, "path": parent, "depth": 1},
        )
        entries = _tool_result_value(result, tool="list_files")
        if not isinstance(entries, list):
            raise ClaudeDesignProtocolError("Claude Design list_files returned no array during sync review.")
        for entry in entries:
            if not isinstance(entry, dict) or entry.get("type") != "file":
                continue
            path = entry.get("path")
            etag = entry.get("etag")
            if not isinstance(path, str) or path not in remote_paths:
                continue
            if not isinstance(etag, str) or not etag or _has_unsafe_text_character(etag):
                raise ClaudeDesignProtocolError("Claude Design returned incomplete sync file metadata.")
            metadata[path] = {"exists": True, "etag": etag}
    return metadata


def _sync_remote_contents(
    client: Any,
    project_id: str,
    metadata: dict[str, dict[str, Any]],
) -> dict[str, bytes]:
    contents: dict[str, bytes] = {}
    for path, revision in sorted(metadata.items()):
        if revision["exists"] is not True:
            contents[path] = b""
            continue
        result = client.call_tool("read_file", {"project_id": project_id, "path": path})
        decoded, etag = _decode_read_file_result(result)
        if etag != revision["etag"]:
            raise ClaudeDesignSafetyError(
                f"Claude Design changed while the sync review was being prepared: {path}. Review again."
            )
        contents[path] = decoded.encode("utf-8")
    return contents


def _sync_snapshot_path(root: Path, review_id: str, index: int, side: str) -> Path:
    return _sync_review_root(root, review_id) / "snapshots" / f"{index:03d}-{side}.bin"


def _sync_diff_bytes(old: bytes, new: bytes, *, old_label: str, new_label: str) -> bytes:
    if old == new:
        return f"--- {old_label}\n+++ {new_label}\n(no byte changes)\n".encode()
    if b"\0" in old or b"\0" in new:
        return (
            f"--- {old_label}\n+++ {new_label}\n"
            f"binary revisions differ: {content_sha256(old)} -> {content_sha256(new)}\n"
        ).encode()
    try:
        old_text = old.decode("utf-8").splitlines(keepends=True)
        new_text = new.decode("utf-8").splitlines(keepends=True)
    except UnicodeDecodeError:
        return (
            f"--- {old_label}\n+++ {new_label}\n"
            f"binary revisions differ: {content_sha256(old)} -> {content_sha256(new)}\n"
        ).encode()
    rendered = "".join(
        difflib.unified_diff(
            old_text,
            new_text,
            fromfile=old_label,
            tofile=new_label,
        )
    )
    return rendered.encode("utf-8")


def _sync_write_diff(root: Path, review_id: str, sections: list[bytes], *, force: bool) -> str:
    data = b"\n".join(sections)
    if len(data) > CLAUDE_DESIGN_MAX_SYNC_DIFF_BYTES:
        raise ClaudeDesignSafetyError("The synchronization diff is too large; review a smaller mapped batch.")
    path = _sync_review_root(root, review_id) / "diff.patch"
    _atomic_write_local(
        path,
        data,
        force=force,
        workspace_root=root,
        authorized_external_paths=[],
    )
    return _sync_relative(root, path)


def _sync_read_snapshot(root: Path, relative_path: str) -> bytes:
    _source, data = _read_local_file(
        str(root / relative_path),
        workspace_root=root,
        authorized_external_paths=[],
    )
    return data


def _sync_public_receipt(receipt: dict[str, Any]) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "review_id": receipt["review_id"],
        "state": receipt["state"],
        "direction": receipt["direction"],
        "classification": receipt["classification"],
        "mutated": receipt.get("mutated", False),
    }
    if isinstance(receipt.get("diff_path"), str):
        payload["diff_path"] = receipt["diff_path"]
    return payload


def _sync_review(args: argparse.Namespace, client: Any, root: Path) -> int:
    pairs = parse_pairs(list(args.pairs))
    if args.direction not in {"to-design", "to-code"}:
        raise ValueError("A sync review direction must be to-design or to-code.")
    if not isinstance(args.project_id, str) or not args.project_id or _has_unsafe_text_character(args.project_id):
        raise ValueError("A sync review requires a valid Claude Design project id.")
    if len(pairs) > CLAUDE_DESIGN_MAX_BATCH_FILES:
        raise ClaudeDesignSafetyError("A sync review contains too many mapped pairs.")
    if args.direction == "to-design" and len({pair.remote_path for pair in pairs}) != len(pairs):
        raise ValueError("A to-design sync needs exactly one local source for every remote path.")
    for pair in pairs:
        _validate_remote_path(pair.remote_path)

    local_cache: dict[str, tuple[bool, bytes]] = {}
    normalized_pairs: list[SyncPair] = []
    total_bytes = 0
    for pair in pairs:
        local_path, exists, data = _sync_optional_local(root, pair.local_path)
        _sync_validate_local_relative_path(local_path)
        if args.direction == "to-design" and not exists:
            raise ValueError(f"A to-design local source does not exist: {local_path}")
        normalized_pairs.append(SyncPair(pair.remote_path, local_path))
        if local_path not in local_cache:
            local_cache[local_path] = (exists, data)
            total_bytes += len(data)
    if total_bytes > CLAUDE_DESIGN_MAX_BATCH_BYTES:
        raise ClaudeDesignSafetyError("The mapped local sync files exceed the aggregate safety limit.")

    remote_paths = {pair.remote_path for pair in normalized_pairs}
    remote_metadata = _sync_remote_metadata(client, args.project_id, remote_paths)
    pair_revisions: list[dict[str, Any]] = []
    classifications = []
    for pair in normalized_pairs:
        local_exists, local_data = local_cache[pair.local_path]
        remote_revision = remote_metadata[pair.remote_path]
        baseline = _sync_load_ledger(
            root,
            project_id=args.project_id,
            remote_path=pair.remote_path,
            local_path=pair.local_path,
        )
        classification = classify_pair(
            baseline,
            remote_exists=bool(remote_revision["exists"]),
            remote_etag=str(remote_revision["etag"]),
            local_exists=local_exists,
            local_sha256=content_sha256(local_data) if local_exists else None,
        )
        classifications.append(classification)
        pair_revisions.append(
            {
                "remote_path": pair.remote_path,
                "local_path": pair.local_path,
                "remote_exists": bool(remote_revision["exists"]),
                "remote_etag": str(remote_revision["etag"]),
                "local_exists": local_exists,
                "local_sha256": content_sha256(local_data) if local_exists else None,
                "classification": classification,
            }
        )

    classification = aggregate_classification(classifications)
    if classification == "unchanged":
        _print_design_result(
            {
                "state": "in_sync",
                "classification": "unchanged",
                "requires_approval": False,
                "mutated": False,
            },
            json_mode=args.json,
        )
        return 0

    _ensure_sync_state_ignored(root)
    remote_contents = _sync_remote_contents(client, args.project_id, remote_metadata)
    if args.direction == "to-code":
        missing_remote = sorted(path for path, metadata in remote_metadata.items() if metadata["exists"] is not True)
        if missing_remote:
            raise ValueError("A to-code sync cannot use missing remote designs: " + ", ".join(missing_remote))
    total_bytes += sum(len(data) for data in remote_contents.values())
    if total_bytes > CLAUDE_DESIGN_MAX_BATCH_BYTES:
        raise ClaudeDesignSafetyError("The mapped sync revisions exceed the aggregate safety limit.")

    review_id = secrets.token_hex(16)
    diff_sections: list[bytes] = []
    remote_snapshots: dict[str, Path] = {}
    local_snapshots: dict[str, Path] = {}
    for pair_revision in pair_revisions:
        remote_path = str(pair_revision["remote_path"])
        local_path = str(pair_revision["local_path"])
        remote_data = remote_contents[remote_path]
        local_data = local_cache[local_path][1]
        if remote_path not in remote_snapshots:
            remote_snapshot = _sync_snapshot_path(root, review_id, len(remote_snapshots), "remote")
            _atomic_write_local(
                remote_snapshot,
                remote_data,
                force=False,
                workspace_root=root,
                authorized_external_paths=[],
            )
            remote_snapshots[remote_path] = remote_snapshot
        if local_path not in local_snapshots:
            local_snapshot = _sync_snapshot_path(root, review_id, len(local_snapshots), "local")
            _atomic_write_local(
                local_snapshot,
                local_data,
                force=False,
                workspace_root=root,
                authorized_external_paths=[],
            )
            local_snapshots[local_path] = local_snapshot
        pair_revision["remote_sha256"] = content_sha256(remote_data) if pair_revision["remote_exists"] else None
        pair_revision["remote_snapshot"] = _sync_relative(root, remote_snapshots[remote_path])
        pair_revision["local_snapshot"] = _sync_relative(root, local_snapshots[local_path])
        if args.direction == "to-design":
            old_data, new_data = remote_data, local_data
            old_label, new_label = f"design/{remote_path}", f"code/{local_path}"
        else:
            old_data, new_data = local_data, remote_data
            old_label, new_label = f"code/{local_path}", f"design/{remote_path}"
        diff_sections.append(_sync_diff_bytes(old_data, new_data, old_label=old_label, new_label=new_label))
    diff_path = _sync_write_diff(root, review_id, diff_sections, force=False)
    receipt = _sync_save_receipt(
        root,
        {
            "schema_version": CLAUDE_DESIGN_SYNC_SCHEMA_VERSION,
            "review_id": review_id,
            "state": "reviewed",
            "direction": args.direction,
            "project_id": args.project_id,
            "classification": classification,
            "requires_reconciliation": classification == "both-changed",
            "created_at": int(time.time()),
            "updated_at": int(time.time()),
            "diff_path": diff_path,
            "pairs": pair_revisions,
            "mutated": False,
        },
    )
    _print_design_result(
        {
            "review_id": review_id,
            "state": "reviewed",
            "classification": classification,
            "requires_approval": True,
            "requires_reconciliation": receipt["requires_reconciliation"],
            "mutated": False,
            "receipt_path": _sync_relative(root, _sync_receipt_path(root, review_id)),
            "diff_path": diff_path,
        },
        json_mode=args.json,
    )
    return 0


def _sync_current_locals(root: Path, receipt: dict[str, Any]) -> dict[str, tuple[bool, bytes]]:
    current: dict[str, tuple[bool, bytes]] = {}
    for pair in receipt["pairs"]:
        local_path = str(pair["local_path"])
        if local_path in current:
            continue
        _normalized, exists, data = _sync_optional_local(root, local_path)
        current[local_path] = (exists, data)
    return current


def _sync_local_changes(
    receipt: dict[str, Any],
    current: dict[str, tuple[bool, bytes]],
) -> list[dict[str, str]]:
    changed: list[dict[str, str]] = []
    seen: set[str] = set()
    for pair in receipt["pairs"]:
        local_path = str(pair["local_path"])
        exists, data = current[local_path]
        expected_hash = pair.get("local_sha256")
        changed_revision = pair.get("local_exists") is not exists or expected_hash != (
            content_sha256(data) if exists else None
        )
        if changed_revision and local_path not in seen:
            changed.append({"side": "local", "path": local_path})
            seen.add(local_path)
    return changed


def _sync_mark_stale(
    root: Path,
    receipt: dict[str, Any],
    *,
    changed: list[dict[str, str]],
    current_locals: dict[str, tuple[bool, bytes]] | None = None,
    current_remote: dict[str, bytes] | None = None,
    json_mode: bool,
) -> int:
    sections: list[bytes] = []
    for item in changed:
        side = item["side"]
        path = item["path"]
        pair = next(
            pair
            for pair in receipt["pairs"]
            if (side == "local" and pair["local_path"] == path) or (side == "remote" and pair["remote_path"] == path)
        )
        if side == "local" and current_locals is not None:
            approved = _sync_read_snapshot(root, str(pair["local_snapshot"]))
            current = current_locals[path][1]
            sections.append(
                _sync_diff_bytes(
                    approved,
                    current,
                    old_label=f"approved-code/{path}",
                    new_label=f"current-code/{path}",
                )
            )
        elif side == "remote" and current_remote is not None:
            approved = _sync_read_snapshot(root, str(pair["remote_snapshot"]))
            current = current_remote.get(path, b"")
            sections.append(
                _sync_diff_bytes(
                    approved,
                    current,
                    old_label=f"approved-design/{path}",
                    new_label=f"current-design/{path}",
                )
            )
    if sections:
        receipt["diff_path"] = _sync_write_diff(
            root,
            str(receipt["review_id"]),
            sections,
            force=True,
        )
    receipt["state"] = "stale"
    receipt["updated_at"] = int(time.time())
    receipt["mutated"] = False
    receipt = _sync_save_receipt(root, receipt)
    _print_design_result(
        {
            "review_id": receipt["review_id"],
            "state": "stale",
            "requires_reapproval": True,
            "mutated": False,
            "changed": changed,
            "diff_path": receipt["diff_path"],
        },
        json_mode=json_mode,
    )
    return CLAUDE_DESIGN_SYNC_STALE_EXIT_CODE


def _sync_mark_unknown(root: Path, receipt: dict[str, Any], *, message: str, json_mode: bool) -> int:
    receipt["state"] = "unknown"
    receipt["updated_at"] = int(time.time())
    receipt = _sync_save_receipt(root, receipt)
    _print_design_result(
        {
            "review_id": receipt["review_id"],
            "state": "unknown",
            "mutated": receipt.get("mutated", False),
            "error": message,
        },
        json_mode=json_mode,
    )
    return CLAUDE_DESIGN_SYNC_UNKNOWN_EXIT_CODE


def _sync_apply_to_design(
    args: argparse.Namespace,
    client: Any,
    root: Path,
    receipt: dict[str, Any],
    current_locals: dict[str, tuple[bool, bytes]],
) -> int:
    _require_write_window(client)
    expected_etags = {str(pair["remote_path"]): str(pair["remote_etag"]) for pair in receipt["pairs"]}
    planned = _tool_result_object(
        client.call_tool(
            "finalize_plan",
            {
                "project_id": receipt["project_id"],
                "scope": "paths",
                "writes": sorted(expected_etags),
                "deletes": [],
            },
        ),
        tool="finalize_plan",
    )
    plan_token = planned.get("plan_token")
    base_etags = planned.get("base_etags")
    if not isinstance(plan_token, str) or not plan_token or not isinstance(base_etags, dict):
        raise ClaudeDesignProtocolError("Claude Design finalize_plan returned an incomplete sync plan.")
    remote_changed = sorted(path for path, etag in expected_etags.items() if base_etags.get(path) != etag)
    if remote_changed:
        metadata = _sync_remote_metadata(client, str(receipt["project_id"]), set(remote_changed))
        contents = _sync_remote_contents(client, str(receipt["project_id"]), metadata)
        return _sync_mark_stale(
            root,
            receipt,
            changed=[{"side": "remote", "path": path} for path in remote_changed],
            current_remote=contents,
            json_mode=args.json,
        )

    files: list[dict[str, object]] = []
    expected_bytes: dict[str, bytes] = {}
    for pair in receipt["pairs"]:
        remote_path = str(pair["remote_path"])
        local_path = str(pair["local_path"])
        data = current_locals[local_path][1]
        expected_bytes[remote_path] = data
        file_payload: dict[str, object] = {"path": remote_path, "if_match": expected_etags[remote_path]}
        try:
            file_payload["data"] = data.decode("utf-8")
        except UnicodeDecodeError:
            file_payload["data"] = base64.b64encode(data).decode("ascii")
            file_payload["encoding"] = "base64"
        files.append(file_payload)
    payload = {
        "project_id": receipt["project_id"],
        "plan_token": plan_token,
        "files": files,
    }
    receipt["state"] = "applying"
    receipt["updated_at"] = int(time.time())
    receipt = _sync_save_receipt(root, receipt)
    try:
        result = client.call_tool("write_files", payload)
    except ClaudeDesignError as error:
        receipt["mutated"] = True
        return _sync_mark_unknown(root, receipt, message=str(error), json_mode=args.json)
    try:
        write_value = _tool_result_object(result, tool="write_files")
    except ClaudeDesignProtocolError:
        write_value = {}
    if write_value.get("status") == "conflict":
        metadata = _sync_remote_metadata(client, str(receipt["project_id"]), set(expected_etags))
        contents = _sync_remote_contents(client, str(receipt["project_id"]), metadata)
        return _sync_mark_stale(
            root,
            receipt,
            changed=[{"side": "remote", "path": path} for path in sorted(expected_etags)],
            current_remote=contents,
            json_mode=args.json,
        )
    receipt["mutated"] = True
    if _tool_exit_code(result, tool="write_files", mutation=True, arguments=payload) != 0:
        return _sync_mark_unknown(
            root,
            receipt,
            message="Claude Design did not return complete evidence for the approved sync write.",
            json_mode=args.json,
        )

    applied_remote: list[dict[str, Any]] = []
    open_urls: list[str] = []
    try:
        for remote_path, expected in sorted(expected_bytes.items()):
            readback = client.call_tool(
                "read_file",
                {"project_id": receipt["project_id"], "path": remote_path},
            )
            decoded, etag = _decode_read_file_result(readback)
            data = decoded.encode("utf-8")
            if data != expected:
                return _sync_mark_unknown(
                    root,
                    receipt,
                    message=f"Claude Design readback did not match the approved bytes: {remote_path}",
                    json_mode=args.json,
                )
            applied_remote.append(
                {"remote_path": remote_path, "remote_etag": etag, "remote_sha256": content_sha256(data)}
            )
            if remote_path.endswith((".html", ".dc.html")):
                preview = _tool_result_object(
                    client.call_tool(
                        "render_preview",
                        {"project_id": receipt["project_id"], "path": remote_path},
                    ),
                    tool="render_preview",
                )
                open_url = preview.get("open_url")
                if not isinstance(open_url, str) or not open_url:
                    return _sync_mark_unknown(
                        root,
                        receipt,
                        message=f"Claude Design returned no durable preview after syncing: {remote_path}",
                        json_mode=args.json,
                    )
                _validate_durable_preview_url(open_url)
                open_urls.append(open_url)
    except (ClaudeDesignError, ValueError) as error:
        return _sync_mark_unknown(root, receipt, message=str(error), json_mode=args.json)
    receipt["state"] = "awaiting_verification"
    receipt["updated_at"] = int(time.time())
    receipt["applied_remote"] = applied_remote
    receipt = _sync_save_receipt(root, receipt)
    _print_design_result(
        {
            "review_id": receipt["review_id"],
            "state": "awaiting_verification",
            "mutated": True,
            "open_urls": open_urls,
        },
        json_mode=args.json,
    )
    return 0


def _sync_apply_to_code(
    args: argparse.Namespace,
    client: Any,
    root: Path,
    receipt: dict[str, Any],
) -> int:
    remote_cache: dict[str, tuple[str, bytes]] = {}
    changed: list[dict[str, str]] = []
    for pair in receipt["pairs"]:
        remote_path = str(pair["remote_path"])
        if remote_path not in remote_cache:
            try:
                result = client.call_tool(
                    "read_file",
                    {
                        "project_id": receipt["project_id"],
                        "path": remote_path,
                        "if_none_match": pair["remote_etag"],
                    },
                )
                try:
                    conditional = _tool_result_object(result, tool="read_file")
                except ClaudeDesignProtocolError:
                    conditional = {}
                if conditional.get("unchanged") is True:
                    etag = conditional.get("etag")
                    path = conditional.get("path")
                    if etag != pair["remote_etag"] or path != remote_path:
                        raise ClaudeDesignProtocolError(
                            "Claude Design returned invalid conditional-read metadata during sync apply."
                        )
                    remote_cache[remote_path] = (str(etag), _sync_read_snapshot(root, str(pair["remote_snapshot"])))
                else:
                    decoded, etag = _decode_read_file_result(result)
                    remote_cache[remote_path] = (etag, decoded.encode("utf-8"))
            except ClaudeDesignProtocolError:
                metadata = _sync_remote_metadata(client, str(receipt["project_id"]), {remote_path})
                if metadata[remote_path]["exists"] is True:
                    raise
                remote_cache[remote_path] = ("0", b"")
        etag, data = remote_cache[remote_path]
        changed_revision = etag != pair["remote_etag"] or content_sha256(data) != pair["remote_sha256"]
        if changed_revision and {"side": "remote", "path": remote_path} not in changed:
            changed.append({"side": "remote", "path": remote_path})
    if changed:
        return _sync_mark_stale(
            root,
            receipt,
            changed=changed,
            current_remote={path: data for path, (_etag, data) in remote_cache.items()},
            json_mode=args.json,
        )
    receipt["state"] = "awaiting_verification"
    receipt["updated_at"] = int(time.time())
    receipt["mutated"] = False
    receipt = _sync_save_receipt(root, receipt)
    handoff_paths = sorted({str(pair["remote_snapshot"]) for pair in receipt["pairs"]})
    _print_design_result(
        {
            "review_id": receipt["review_id"],
            "state": "awaiting_verification",
            "mutated": False,
            "handoff_paths": handoff_paths,
        },
        json_mode=args.json,
    )
    return 0


def _sync_apply(args: argparse.Namespace, client: Any, root: Path) -> int:
    if not args.allow_write:
        raise ClaudeDesignSafetyError(
            "sync apply requires --allow-write only after the user approved the exact recorded review."
        )
    receipt = _sync_load_receipt(root, args.review_id)
    if receipt["state"] != "reviewed":
        raise ValueError(f"Sync review {args.review_id} state is {receipt['state']}; it cannot be applied.")
    current_locals = _sync_current_locals(root, receipt)
    local_changes = _sync_local_changes(receipt, current_locals)
    if local_changes:
        return _sync_mark_stale(
            root,
            receipt,
            changed=local_changes,
            current_locals=current_locals,
            json_mode=args.json,
        )
    if receipt["direction"] == "to-design":
        return _sync_apply_to_design(args, client, root, receipt, current_locals)
    return _sync_apply_to_code(args, client, root, receipt)


def _sync_cleanup_artifacts(root: Path, receipt: dict[str, Any]) -> None:
    review_root = _sync_review_root(root, str(receipt["review_id"]))
    for target in (review_root / "snapshots", review_root / "diff.patch"):
        resolved = _resolve_local_path(
            str(target),
            workspace_root=root,
            authorized_external_paths=[],
            require_file=False,
        )
        if not resolved.exists():
            continue
        if resolved.is_dir():
            shutil.rmtree(resolved)
        else:
            resolved.unlink()
    receipt.pop("diff_path", None)
    for pair in receipt["pairs"]:
        pair.pop("remote_snapshot", None)
        pair.pop("local_snapshot", None)


def _sync_finish(args: argparse.Namespace, client: Any, root: Path) -> int:
    receipt = _sync_load_receipt(root, args.review_id)
    if receipt["state"] != "awaiting_verification":
        raise ValueError(f"Sync review {args.review_id} state is {receipt['state']}; it is not awaiting verification.")
    remote_paths = {str(pair["remote_path"]) for pair in receipt["pairs"]}
    metadata = _sync_remote_metadata(client, str(receipt["project_id"]), remote_paths)
    if receipt["direction"] == "to-design":
        applied = {
            str(item["remote_path"]): item for item in receipt.get("applied_remote", []) if isinstance(item, dict)
        }
        expected_etags = {path: str(applied[path]["remote_etag"]) for path in remote_paths if path in applied}
    else:
        expected_etags = {str(pair["remote_path"]): str(pair["remote_etag"]) for pair in receipt["pairs"]}
    remote_changes = sorted(
        path
        for path in remote_paths
        if metadata[path]["exists"] is not True or metadata[path]["etag"] != expected_etags.get(path)
    )
    if remote_changes:
        receipt["mutated"] = receipt["direction"] == "to-design"
        return _sync_mark_unknown(
            root,
            receipt,
            message="Claude Design changed before synchronization verification completed: " + ", ".join(remote_changes),
            json_mode=args.json,
        )

    current_locals = _sync_current_locals(root, receipt)
    if receipt["direction"] == "to-design":
        local_changes = _sync_local_changes(receipt, current_locals)
        if local_changes:
            receipt["mutated"] = True
            return _sync_mark_unknown(
                root,
                receipt,
                message="Local code changed after the approved remote write but before verification completed.",
                json_mode=args.json,
            )

    applied = {str(item["remote_path"]): item for item in receipt.get("applied_remote", []) if isinstance(item, dict)}
    verified_at = int(time.time())
    for pair in receipt["pairs"]:
        remote_path = str(pair["remote_path"])
        local_path = str(pair["local_path"])
        local_exists, local_data = current_locals[local_path]
        remote_sha256 = (
            applied[remote_path]["remote_sha256"] if receipt["direction"] == "to-design" else pair["remote_sha256"]
        )
        _sync_save_ledger(
            root,
            {
                "schema_version": CLAUDE_DESIGN_SYNC_SCHEMA_VERSION,
                "project_id": receipt["project_id"],
                "remote_path": remote_path,
                "local_path": local_path,
                "remote_exists": True,
                "remote_etag": expected_etags[remote_path],
                "remote_sha256": remote_sha256,
                "local_exists": local_exists,
                "local_sha256": content_sha256(local_data) if local_exists else None,
                "verified_at": verified_at,
            },
        )
    receipt["state"] = "complete"
    receipt["updated_at"] = verified_at
    receipt["mutated"] = receipt["direction"] == "to-design"
    receipt = _sync_save_receipt(root, receipt)
    _sync_cleanup_artifacts(root, receipt)
    receipt = _sync_save_receipt(root, receipt)
    _print_design_result(
        {
            "review_id": receipt["review_id"],
            "state": "complete",
            "mutated": False,
        },
        json_mode=args.json,
    )
    return 0


def _sync_status(args: argparse.Namespace, root: Path) -> int:
    if args.review_id is not None:
        receipt = _sync_load_receipt(root, args.review_id)
        _print_design_result(_sync_public_receipt(receipt), json_mode=args.json)
        return 0
    reviews_root = _resolve_local_path(
        str(_sync_root(root) / "reviews"),
        workspace_root=root,
        authorized_external_paths=[],
        require_file=False,
    )
    if not reviews_root.exists():
        _print_design_result({"reviews": []}, json_mode=args.json)
        return 0
    reviews: list[dict[str, Any]] = []
    for path in sorted(reviews_root.iterdir()):
        if not path.is_dir() or REVIEW_ID_PATTERN.fullmatch(path.name) is None:
            continue
        reviews.append(_sync_public_receipt(_sync_load_receipt(root, path.name)))
    _print_design_result({"reviews": reviews}, json_mode=args.json)
    return 0


def _run_sync_command(
    args: argparse.Namespace,
    *,
    client_factory: Callable[[], Any],
    workspace_root: Path | None,
) -> int:
    root = _design_workspace_root(workspace_root)
    if args.sync_command == "status":
        return _sync_status(args, root)
    client = client_factory()
    if args.sync_command == "review":
        return _sync_review(args, client, root)
    if args.sync_command == "apply":
        return _sync_apply(args, client, root)
    if args.sync_command == "finish":
        return _sync_finish(args, client, root)
    raise ValueError("Choose sync review, apply, finish, or status.")


def run_design_command(
    args: argparse.Namespace,
    *,
    client_factory: Callable[[], Any] = ClaudeDesignClient,
    workspace_root: Path | None = None,
) -> int:
    """Execute a parsed `open-claude-design` bridge command."""
    command = args.design_command
    if command == "sync":
        return _run_sync_command(
            args,
            client_factory=client_factory,
            workspace_root=workspace_root,
        )
    if command == "delete":
        if not args.allow_write:
            raise ClaudeDesignSafetyError(
                "open-claude-design delete changes remote files. "
                "Pass --allow-write only after explicit user authorization."
            )
        root = _design_workspace_root(workspace_root)
        client = client_factory()
        _require_write_window(client)
        payload, backups = _local_delete_payload(args, client, workspace_root=root)
        result = client.call_tool("delete_files", payload)
        exit_code = _tool_exit_code(result, tool="delete_files", mutation=True, arguments=payload)
        if exit_code == 0:
            try:
                verification = _verify_deleted_paths(client, args.project_id, list(args.paths))
            except ClaudeDesignError as error:
                verification = {
                    "verifiedAbsent": False,
                    "remainingPaths": [],
                    "error": str(error),
                }
                exit_code = 2
            if verification.get("verifiedAbsent") is not True:
                exit_code = 2
        else:
            verification = {
                "verifiedAbsent": False,
                "remainingPaths": list(args.paths),
                "error": "Delete did not report success; remote absence was not assumed.",
            }
        _print_design_result(
            {
                "tool": "delete_files",
                "paths": list(args.paths),
                "backups": backups,
                "verification": verification,
                "result": result,
            },
            json_mode=args.json,
        )
        return exit_code

    if command == "push":
        if not args.allow_write:
            raise ClaudeDesignSafetyError(
                "open-claude-design push changes remote files. "
                "Pass --allow-write only after explicit user authorization."
            )
        _validate_plan_token_source(getattr(args, "plan_token", None))
        root = _design_workspace_root(workspace_root)
        client = client_factory()
        _require_write_window(client)
        payload = _local_write_payload(args, client, workspace_root=root)
        result = client.call_tool("write_files", payload)
        _print_design_result({"tool": "write_files", "result": result}, json_mode=args.json)
        return _tool_exit_code(result, tool="write_files", mutation=True, arguments=payload)

    if command == "preview":
        _validate_remote_path(args.remote_path)
        client = client_factory()
        result = client.call_tool(
            "render_preview",
            {"project_id": args.project_id, "path": args.remote_path},
        )
        preview = _tool_result_object(result, tool="render_preview")
        open_url = preview.get("open_url")
        if not isinstance(open_url, str) or not open_url:
            raise ClaudeDesignProtocolError("Claude Design render_preview returned no durable open_url.")
        _validate_durable_preview_url(open_url)
        if args.open_browser:
            serve_url = preview.get("serve_url")
            if not isinstance(serve_url, str) or not serve_url:
                raise ClaudeDesignProtocolError("Claude Design render_preview returned no short-lived render URL.")
            _open_preview_url(serve_url)
        _print_design_result(
            {"tool": "render_preview", "open_url": open_url, "opened": args.open_browser},
            json_mode=args.json,
        )
        return 0

    if command == "pull":
        _validate_remote_path(args.remote_path)
        root = _design_workspace_root(workspace_root)
        external_paths = getattr(args, "external_local_paths", [])
        target = _resolve_local_path(
            args.output,
            workspace_root=root,
            authorized_external_paths=external_paths,
            require_file=False,
        )
        if target.exists() and not args.force:
            raise ClaudeDesignSafetyError(f"Local output already exists: {target}. Pass --force to replace it.")
        client = client_factory()
        result = client.call_tool("read_file", {"project_id": args.project_id, "path": args.remote_path})
        decoded, etag = _decode_read_file_result(result)
        encoded = decoded.encode("utf-8")
        _atomic_write_local(
            target,
            encoded,
            force=args.force,
            workspace_root=root,
            authorized_external_paths=external_paths,
        )
        _print_design_result(
            {"projectPath": args.remote_path, "output": str(target), "etag": etag, "bytes": len(encoded)},
            json_mode=args.json,
        )
        return 0

    if command == "authoring-context":
        root = _design_workspace_root(workspace_root)
        payload = _authoring_context_payload(args, client_factory(), root=root)
        _print_design_result(
            {
                "cached": payload["cached"],
                "expires_at": payload["expires_at"],
                "prompt": payload["prompt"],
                "skill": payload["skill"],
            },
            json_mode=args.json,
        )
        return 0

    client = client_factory()
    if command == "status":
        _print_design_result(client.status(), json_mode=args.json)
        return 0

    if command == "files":
        return _run_files_command(args, client)

    tools = client.list_tools()
    if command == "tools":
        _print_design_result({"tools": [_compact_tool(tool) for tool in tools]}, json_mode=args.json)
        return 0
    if command == "describe":
        _print_design_result({"tool": _tool_by_name(tools, args.tool)}, json_mode=args.json)
        return 0
    if command == "planned-call":
        tool = _tool_by_name(tools, args.tool)
        annotations = tool.get("annotations")
        destructive = args.tool in CLAUDE_DESIGN_KNOWN_DESTRUCTIVE_TOOLS or (
            isinstance(annotations, dict) and annotations.get("destructiveHint") is True
        )
        if not args.allow_write:
            raise ClaudeDesignSafetyError("planned-call requires exact user-authorized --allow-write.")
        if destructive and not args.allow_destructive:
            raise ClaudeDesignSafetyError(
                f"Claude Design tool '{args.tool}' is destructive and requires --allow-destructive."
            )
        _require_write_window(client)
        payload = _planned_call_payload(args, client)
        result = client.call_tool(args.tool, payload)
        _print_design_result({"tool": args.tool, "result": result}, json_mode=args.json)
        return _tool_exit_code(result, tool=args.tool, mutation=True, arguments=payload)
    if command != "call":
        raise ValueError("Choose status, tools, describe, call, or planned-call.")

    tool = _tool_by_name(tools, args.tool)
    annotations = tool.get("annotations")
    server_read_only = isinstance(annotations, dict) and annotations.get("readOnlyHint") is True
    known_read_only = args.tool in CLAUDE_DESIGN_KNOWN_READ_ONLY_TOOLS
    known_mutating = args.tool in CLAUDE_DESIGN_KNOWN_MUTATING_TOOLS
    read_only = known_read_only and server_read_only
    destructive = args.tool in CLAUDE_DESIGN_KNOWN_DESTRUCTIVE_TOOLS or (
        not known_read_only and isinstance(annotations, dict) and annotations.get("destructiveHint") is True
    )
    guarded_non_mutating = args.tool in CLAUDE_DESIGN_NON_MUTATING_GUARDED_TOOLS or (
        known_read_only and not server_read_only
    )
    if args.tool in CLAUDE_DESIGN_SPECIALIZED_ONLY_TOOLS:
        replacement = {
            "copy_files": "planned-call",
            "create_support_js": "planned-call",
            "delete_files": "delete",
            "finalize_plan": "push, delete, or planned-call",
            "render_preview": "preview",
            "write_files": "push",
        }[args.tool]
        raise ClaudeDesignSafetyError(
            f"Generic {args.tool} calls are disabled. Use {replacement} so signed capabilities, etags, backups, "
            "and verification remain inside one guarded process."
        )
    if not read_only and guarded_non_mutating and not args.allow_guarded:
        raise ClaudeDesignSafetyError(
            f"Claude Design tool '{args.tool}' is locally known to be non-mutating, but its live annotation does "
            "not confirm that classification. Pass --allow-guarded for this call."
        )
    if not read_only and not guarded_non_mutating and not args.allow_write:
        raise ClaudeDesignSafetyError(
            f"Claude Design tool '{args.tool}' is not marked read-only. "
            "Pass --allow-write only when the user explicitly authorized that design mutation."
        )
    if destructive and (not args.allow_write or not getattr(args, "allow_destructive", False)):
        raise ClaudeDesignSafetyError(
            f"Claude Design tool '{args.tool}' is marked destructive. Pass --allow-destructive together with "
            "--allow-write only after the user explicitly authorized that exact destructive operation."
        )
    mutation = known_mutating or destructive or (not read_only and not guarded_non_mutating)
    if mutation:
        _require_write_window(client)
    tool_arguments = _parse_tool_arguments(args.args)
    result = client.call_tool(args.tool, tool_arguments)
    _print_design_result({"tool": args.tool, "result": result}, json_mode=args.json)
    return _tool_exit_code(result, tool=args.tool, mutation=mutation, arguments=tool_arguments)


def cmd_design(args: argparse.Namespace) -> int:
    """CLI wrapper with clean JSON/human errors and no credential output."""
    try:
        return run_design_command(args)
    except (ClaudeDesignError, ValueError, json.JSONDecodeError, OSError) as error:
        if getattr(args, "json", False):
            print(json.dumps({"error": str(error)}, ensure_ascii=True))
        else:
            print(f"✗ {_safe_terminal_text(str(error))}", file=sys.stderr)
        return 1


def _stdin_plan_token_marker(value: str) -> str:
    """Accept only the stdin marker without echoing a rejected token value."""
    if value != "-":
        raise argparse.ArgumentTypeError("must be '-' so the plan token is read from stdin")
    return value


def build_parser() -> argparse.ArgumentParser:
    """Build the standalone bridge CLI parser."""
    parser = argparse.ArgumentParser(prog="open-claude-design")
    subparsers = parser.add_subparsers(dest="design_command", required=True)

    status_parser = subparsers.add_parser("status", help="Verify authentication and connectivity.")
    status_parser.add_argument("--json", action="store_true", help="Output compact JSON.")

    context_parser = subparsers.add_parser(
        "authoring-context",
        help="Fetch or reuse one project prompt and one live authoring skill without printing their contents.",
    )
    context_parser.add_argument("project_id", help="Claude Design project UUID.")
    context_parser.add_argument(
        "--design-system",
        dest="design_system_id",
        help="Optional bound Claude Design design-system UUID.",
    )
    context_parser.add_argument(
        "--skill",
        required=True,
        help="One live authoring skill, such as hifi-design or frontend-design.",
    )
    context_parser.add_argument(
        "--refresh",
        action="store_true",
        help="Ignore a fresh local cache after the design system or host guidance changed.",
    )
    context_parser.add_argument("--json", action="store_true", help="Output compact cache metadata.")

    tools_parser = subparsers.add_parser("tools", help="List compact live tool summaries.")
    tools_parser.add_argument("--json", action="store_true", help="Output compact JSON.")

    describe_parser = subparsers.add_parser("describe", help="Show one live tool schema.")
    describe_parser.add_argument("tool", help="Exact Claude Design tool name.")
    describe_parser.add_argument("--json", action="store_true", help="Output compact JSON.")

    call_parser = subparsers.add_parser("call", help="Call one Claude Design tool.")
    call_parser.add_argument("tool", help="Exact Claude Design tool name.")
    call_parser.add_argument("--args", default="{}", help="JSON object, or '-' to read JSON from stdin.")
    call_parser.add_argument("--allow-write", action="store_true", help="Allow an explicitly authorized write tool.")
    call_parser.add_argument(
        "--allow-destructive",
        action="store_true",
        help="Acknowledge an exact user-authorized destructive tool in addition to --allow-write.",
    )
    call_parser.add_argument(
        "--allow-guarded",
        action="store_true",
        help="Allow a locally reviewed read-only tool whose live annotation is conservative.",
    )
    call_parser.add_argument("--json", action="store_true", help="Output compact JSON.")

    planned_parser = subparsers.add_parser(
        "planned-call",
        help="Run copy_files or create_support_js while keeping the signed plan token in-process.",
    )
    planned_parser.add_argument("tool", choices=("copy_files", "create_support_js"))
    planned_parser.add_argument("project_id", help="Claude Design project UUID.")
    planned_parser.add_argument("--args", default="{}", help="Tool arguments without project_id or plan_token.")
    planned_parser.add_argument(
        "--write",
        dest="writes",
        action="append",
        required=True,
        help="Exact destination path; repeat for every declared write.",
    )
    planned_parser.add_argument("--allow-write", action="store_true", help="Required write acknowledgement.")
    planned_parser.add_argument(
        "--allow-destructive",
        action="store_true",
        help="Required for copy_files because existing destinations may be replaced.",
    )
    planned_parser.add_argument("--json", action="store_true", help="Output compact JSON.")

    preview_parser = subparsers.add_parser(
        "preview",
        help="Create a preview while exposing only the durable Claude Design URL.",
    )
    preview_parser.add_argument("project_id", help="Claude Design project UUID.")
    preview_parser.add_argument("remote_path", help="Project-relative renderable file path.")
    preview_parser.add_argument(
        "--open",
        dest="open_browser",
        action="store_true",
        help="Open the isolated render locally while returning only its durable Claude Design URL.",
    )
    preview_parser.add_argument("--json", action="store_true", help="Output compact JSON.")

    files_parser = subparsers.add_parser("files", help="List project file metadata without file bodies.")
    files_parser.add_argument("project_id", help="Claude Design project UUID.")
    files_parser.add_argument("--path", default="", help="Project-relative directory.")
    files_parser.add_argument(
        "--depth",
        type=int,
        default=DEFAULT_FILE_LIST_DEPTH,
        help="Listing depth; use -1 for the full tree.",
    )
    files_output = files_parser.add_mutually_exclusive_group()
    files_output.add_argument("--json", action="store_true", help="Output compact JSON.")
    files_output.add_argument("--tsv", action="store_true", help="Output path, etag, and size as TSV.")

    pull_parser = subparsers.add_parser("pull", help="Read one text file directly to local disk.")
    pull_parser.add_argument("project_id", help="Claude Design project UUID.")
    pull_parser.add_argument("remote_path", help="Project-relative remote file path.")
    pull_parser.add_argument("--output", required=True, help="Local output path.")
    pull_parser.add_argument("--force", action="store_true", help="Replace an existing local output file.")
    pull_parser.add_argument(
        "--allow-external-local-path",
        dest="external_local_paths",
        action="append",
        default=[],
        metavar="LOCAL_PATH",
        help="Authorize this exact output outside the current worktree; repeat per operand.",
    )
    pull_parser.add_argument("--json", action="store_true", help="Output compact JSON metadata.")

    push_parser = subparsers.add_parser("push", help="Write local files into an authorized remote path plan.")
    push_parser.add_argument("project_id", help="Claude Design project UUID.")
    push_parser.add_argument(
        "--file",
        dest="files",
        action="append",
        required=True,
        help="REMOTE_PATH=LOCAL_PATH; repeat per file.",
    )
    push_parser.add_argument(
        "--if-match",
        dest="if_matches",
        action="append",
        required=True,
        help="REMOTE_PATH=ETAG; exactly one current etag per file.",
    )
    push_parser.add_argument(
        "--plan-token",
        default=None,
        type=_stdin_plan_token_marker,
        metavar="-",
        help="Read an existing exact-path plan token from stdin.",
    )
    push_parser.add_argument(
        "--allow-external-local-path",
        dest="external_local_paths",
        action="append",
        default=[],
        metavar="LOCAL_PATH",
        help="Authorize this exact source outside the current worktree; repeat per operand.",
    )
    push_parser.add_argument("--allow-write", action="store_true", help="Required remote-write acknowledgement.")
    push_parser.add_argument("--json", action="store_true", help="Output compact JSON metadata.")

    sync_parser = subparsers.add_parser(
        "sync",
        help="Review, apply, and verify revision-bound code and Claude Design synchronization.",
    )
    sync_commands = sync_parser.add_subparsers(dest="sync_command", required=True)

    sync_review = sync_commands.add_parser(
        "review",
        help="Record the exact local hashes and remote etags shown for approval.",
    )
    sync_review.add_argument("project_id", help="Claude Design project UUID.")
    sync_review.add_argument("--direction", required=True, choices=("to-design", "to-code"))
    sync_review.add_argument(
        "--pair",
        dest="pairs",
        action="append",
        required=True,
        help="REMOTE_PATH=LOCAL_PATH; repeat for every affected relationship.",
    )
    sync_review.add_argument("--json", action="store_true", help="Output compact revision metadata.")

    sync_apply = sync_commands.add_parser(
        "apply",
        help="Revalidate and apply one user-approved sync review.",
    )
    sync_apply.add_argument("review_id", help="Exact review id previously shown to the user.")
    sync_apply.add_argument(
        "--allow-write",
        action="store_true",
        help="Required after the user approved this exact review.",
    )
    sync_apply.add_argument("--json", action="store_true", help="Output compact revision metadata.")

    sync_finish = sync_commands.add_parser(
        "finish",
        help="Advance the verified sync ledger after implementation and preview checks pass.",
    )
    sync_finish.add_argument("review_id", help="Applied review awaiting verification.")
    sync_finish.add_argument("--json", action="store_true", help="Output compact revision metadata.")

    sync_status = sync_commands.add_parser("status", help="Inspect local sync receipt state without remote access.")
    sync_status.add_argument("review_id", nargs="?", help="Optional exact review id.")
    sync_status.add_argument("--json", action="store_true", help="Output compact revision metadata.")

    delete_parser = subparsers.add_parser(
        "delete",
        help="Delete exact remote paths with current etags while keeping the signed plan token in-process.",
    )
    delete_parser.add_argument("project_id", help="Claude Design project UUID.")
    delete_parser.add_argument(
        "--path",
        dest="paths",
        action="append",
        required=True,
        help="Project-relative remote path; repeat for each file.",
    )
    delete_parser.add_argument(
        "--if-match",
        dest="if_matches",
        action="append",
        required=True,
        help="REMOTE_PATH=ETAG; exactly one current etag per --path.",
    )
    delete_parser.add_argument(
        "--confirm-delete",
        dest="confirm_deletes",
        action="append",
        required=True,
        metavar="REMOTE_PATH",
        help="Affirm the user's exact authorization for this path; repeat once per --path.",
    )
    delete_parser.add_argument(
        "--backup-dir",
        default=".open-claude-design/delete-backups",
        help="Worktree-local recovery directory written before any remote delete.",
    )
    delete_parser.add_argument(
        "--allow-write",
        action="store_true",
        help="Required remote-delete acknowledgement; use only after explicit user authorization.",
    )
    delete_parser.add_argument("--json", action="store_true", help="Output compact JSON metadata.")
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the standalone bridge CLI."""
    return cmd_design(build_parser().parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
