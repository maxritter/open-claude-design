"""Standalone Claude Design OAuth and credential storage."""

from __future__ import annotations

import base64
import contextlib
import fcntl
import getpass
import hashlib
import json
import os
import secrets
import shutil
import stat
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, Protocol, cast
from urllib.parse import parse_qs, urlencode, urlparse

from open_claude_design.config import (
    CLAUDE_DESIGN_BROWSER_LOGIN_ENV,
    CLAUDE_DESIGN_CREDENTIAL_MAX_BYTES,
    CLAUDE_DESIGN_OAUTH_AUTHORIZE_URL,
    CLAUDE_DESIGN_OAUTH_CLIENT_ID,
    CLAUDE_DESIGN_OAUTH_MANUAL_REDIRECT_URL,
    CLAUDE_DESIGN_OAUTH_REFRESH_MARGIN_SECONDS,
    CLAUDE_DESIGN_OAUTH_RESPONSE_MAX_BYTES,
    CLAUDE_DESIGN_OAUTH_SCOPES,
    CLAUDE_DESIGN_OAUTH_SUCCESS_URL,
    CLAUDE_DESIGN_OAUTH_TIMEOUT_SECONDS,
    CLAUDE_DESIGN_OAUTH_TOKEN_URL,
    CLAUDE_DESIGN_STANDALONE_CREDENTIAL_PARTS,
    CLAUDE_DESIGN_STANDALONE_KEYCHAIN_ACCOUNT,
    CLAUDE_DESIGN_STANDALONE_KEYCHAIN_SERVICE,
    CLAUDE_DESIGN_USER_AGENT,
)


class DesignAuthError(RuntimeError):
    """Standalone Claude Design authorization failed safely."""


class _Response(Protocol):
    headers: Any

    def read(self, amount: int | None = None) -> bytes: ...

    def __enter__(self) -> _Response: ...

    def __exit__(self, *_args: object) -> None: ...


class _RejectRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *_args: Any, **_kwargs: Any) -> None:
        return None


_TOKEN_OPENER = urllib.request.build_opener(_RejectRedirects())


def _base64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _credential_file(home: Path | None = None) -> Path:
    return (home or Path.home()).joinpath(*CLAUDE_DESIGN_STANDALONE_CREDENTIAL_PARTS)


def _open_secure_parent(path: Path, *, create: bool) -> int | None:
    absolute = Path(os.path.abspath(path))
    if not absolute.is_absolute() or not absolute.name:
        raise DesignAuthError("Open Claude Design's credential path is invalid.")
    directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        directory_fd = os.open(absolute.anchor, directory_flags)
    except OSError as error:
        raise DesignAuthError(f"Credential root is not safely readable: {absolute.anchor}") from error
    transferred = False
    try:
        for component in absolute.parts[1:-1]:
            try:
                next_fd = os.open(component, directory_flags, dir_fd=directory_fd)
            except FileNotFoundError:
                if not create:
                    return None
                os.mkdir(component, 0o700, dir_fd=directory_fd)
                next_fd = os.open(component, directory_flags, dir_fd=directory_fd)
            os.close(directory_fd)
            directory_fd = next_fd
        transferred = True
        return directory_fd
    except OSError as error:
        raise DesignAuthError("Refusing a symlinked or unsafe credential directory.") from error
    finally:
        if not transferred:
            os.close(directory_fd)


def _read_secure_json_file(path: Path) -> dict[str, object] | None:
    absolute = Path(os.path.abspath(path))
    file_flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    directory_fd = _open_secure_parent(absolute, create=False)
    if directory_fd is None:
        return None
    try:
        try:
            credential_fd = os.open(absolute.name, file_flags, dir_fd=directory_fd)
        except FileNotFoundError:
            return None
    finally:
        os.close(directory_fd)

    try:
        metadata = os.fstat(credential_fd)
        if not stat.S_ISREG(metadata.st_mode):
            raise DesignAuthError("Open Claude Design's credential path is not a regular file.")
        if hasattr(os, "getuid") and metadata.st_uid != os.getuid():
            raise DesignAuthError("Open Claude Design's credential file is not owned by the current user.")
        if stat.S_IMODE(metadata.st_mode) & 0o077:
            raise DesignAuthError("Open Claude Design's credential file permissions are too broad; expected 0600.")
        if metadata.st_size > CLAUDE_DESIGN_CREDENTIAL_MAX_BYTES:
            raise DesignAuthError("Open Claude Design's credential file is unexpectedly large.")
        with os.fdopen(credential_fd, "r", encoding="utf-8", closefd=False) as handle:
            payload = json.load(handle)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise DesignAuthError("Open Claude Design's credential file is not valid JSON.") from error
    finally:
        os.close(credential_fd)
    if not isinstance(payload, dict):
        raise DesignAuthError("Open Claude Design's credential file must contain a JSON object.")
    return payload


def _write_secure_json_file(path: Path, payload: dict[str, object]) -> None:
    absolute = Path(os.path.abspath(path))
    directory_fd = _open_secure_parent(absolute, create=True)
    assert directory_fd is not None
    temporary_name: str | None = None
    try:
        os.fchmod(directory_fd, 0o700)
        temporary_name = f".{absolute.name}.{os.getpid()}.{secrets.token_hex(8)}.tmp"
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(temporary_name, flags, 0o600, dir_fd=directory_fd)
        try:
            data = json.dumps(payload, separators=(",", ":")).encode("utf-8")
            view = memoryview(data)
            while view:
                written = os.write(descriptor, view)
                if written <= 0:
                    raise OSError("credential write did not progress")
                view = view[written:]
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        os.replace(temporary_name, absolute.name, src_dir_fd=directory_fd, dst_dir_fd=directory_fd)
        temporary_name = None
        os.chmod(absolute.name, 0o600, dir_fd=directory_fd, follow_symlinks=False)
    finally:
        if temporary_name is not None:
            with contextlib.suppress(FileNotFoundError):
                os.unlink(temporary_name, dir_fd=directory_fd)
        os.close(directory_fd)


def _read_keychain(
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> dict[str, object] | None:
    result = runner(
        [
            "/usr/bin/security",
            "find-generic-password",
            "-a",
            CLAUDE_DESIGN_STANDALONE_KEYCHAIN_ACCOUNT,
            "-s",
            CLAUDE_DESIGN_STANDALONE_KEYCHAIN_SERVICE,
            "-w",
        ],
        capture_output=True,
        text=True,
        shell=False,
        timeout=10,
        check=False,
    )
    if result.returncode != 0:
        return None
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise DesignAuthError("Open Claude Design's Keychain credential is not valid JSON.") from error
    if not isinstance(payload, dict):
        raise DesignAuthError("Open Claude Design's Keychain credential must contain a JSON object.")
    return payload


def _read_standalone_raw(
    *,
    platform: str,
    home: Path | None,
    runner: Callable[..., subprocess.CompletedProcess[str]],
) -> dict[str, object] | None:
    if platform == "darwin":
        return _read_keychain(runner)
    if platform.startswith("linux"):
        return _read_secure_json_file(_credential_file(home))
    return None


@contextmanager
def _refresh_lock(home: Path | None = None) -> Iterator[None]:
    credential_path = Path(os.path.abspath(_credential_file(home)))
    directory_fd = _open_secure_parent(credential_path, create=True)
    assert directory_fd is not None
    os.fchmod(directory_fd, 0o700)
    lock_fd = os.open(
        ".refresh.lock",
        os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0),
        0o600,
        dir_fd=directory_fd,
    )
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        os.close(lock_fd)
        os.close(directory_fd)


def _write_keychain(
    payload: dict[str, object],
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> None:
    serialized = json.dumps(payload, separators=(",", ":"))
    result = runner(
        [
            "/usr/bin/security",
            "add-generic-password",
            "-U",
            "-a",
            CLAUDE_DESIGN_STANDALONE_KEYCHAIN_ACCOUNT,
            "-s",
            CLAUDE_DESIGN_STANDALONE_KEYCHAIN_SERVICE,
            "-w",
        ],
        input=f"{serialized}\n{serialized}\n",
        capture_output=True,
        text=True,
        shell=False,
        timeout=30,
        check=False,
    )
    if result.returncode != 0:
        raise DesignAuthError("Could not save the Design credential to macOS Keychain.")


def load_standalone_credential(
    *,
    platform: str = sys.platform,
    home: Path | None = None,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    now_ms: int | None = None,
    token_opener: Callable[..., _Response] = _TOKEN_OPENER.open,
) -> dict[str, object] | None:
    """Load and refresh Open Claude Design's own credential when available."""
    payload = _read_standalone_raw(platform=platform, home=home, runner=runner)
    if payload is None:
        return None
    current = int(time.time() * 1000) if now_ms is None else now_ms

    def needs_refresh(candidate: dict[str, object]) -> bool:
        candidate_oauth = candidate.get("designOauth")
        if not isinstance(candidate_oauth, dict):
            raise DesignAuthError("Open Claude Design's credential has no designOauth object.")
        expiry = candidate_oauth.get("expiresAt")
        return not (
            isinstance(expiry, int | float)
            and int(expiry) > current + CLAUDE_DESIGN_OAUTH_REFRESH_MARGIN_SECONDS * 1000
        )

    if not needs_refresh(payload):
        return payload
    with _refresh_lock(home):
        latest = _read_standalone_raw(platform=platform, home=home, runner=runner)
        if latest is None:
            return None
        if not needs_refresh(latest):
            return latest
        oauth = latest.get("designOauth")
        assert isinstance(oauth, dict)
        refresh_token = oauth.get("refreshToken")
        client_id = oauth.get("clientId")
        scopes = oauth.get("scopes")
        if not isinstance(refresh_token, str) or not refresh_token:
            return latest
        if not isinstance(client_id, str) or not client_id:
            client_id = CLAUDE_DESIGN_OAUTH_CLIENT_ID
        requested_scopes = [scope for scope in scopes if isinstance(scope, str)] if isinstance(scopes, list) else []
        refreshed = _request_token(
            {
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": client_id,
                "scope": " ".join(requested_scopes or CLAUDE_DESIGN_OAUTH_SCOPES),
            },
            opener=token_opener,
        )
        refreshed_payload = _credential_payload(
            refreshed,
            client_id=client_id,
            fallback_refresh_token=refresh_token,
            now_ms=current,
        )
        save_standalone_credential(refreshed_payload, platform=platform, home=home, runner=runner)
        return refreshed_payload


def save_standalone_credential(
    payload: dict[str, object],
    *,
    platform: str = sys.platform,
    home: Path | None = None,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> None:
    if platform == "darwin":
        _write_keychain(payload, runner)
        return
    if platform.startswith("linux"):
        _write_secure_json_file(_credential_file(home), payload)
        return
    raise DesignAuthError("Open Claude Design login supports macOS, Linux, and WSL2.")


def delete_standalone_credential(
    *,
    platform: str = sys.platform,
    home: Path | None = None,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> bool:
    if platform == "darwin":
        result = runner(
            [
                "/usr/bin/security",
                "delete-generic-password",
                "-a",
                CLAUDE_DESIGN_STANDALONE_KEYCHAIN_ACCOUNT,
                "-s",
                CLAUDE_DESIGN_STANDALONE_KEYCHAIN_SERVICE,
            ],
            capture_output=True,
            text=True,
            shell=False,
            timeout=10,
            check=False,
        )
        return result.returncode == 0
    if platform.startswith("linux"):
        path = Path(os.path.abspath(_credential_file(home)))
        directory_fd = _open_secure_parent(path, create=False)
        if directory_fd is None:
            return False
        try:
            os.unlink(path.name, dir_fd=directory_fd)
        except FileNotFoundError:
            return False
        finally:
            os.close(directory_fd)
        return True
    raise DesignAuthError("Open Claude Design logout supports macOS, Linux, and WSL2.")


def _request_token(
    fields: dict[str, object],
    *,
    opener: Callable[..., _Response] = _TOKEN_OPENER.open,
) -> dict[str, object]:
    request = urllib.request.Request(
        CLAUDE_DESIGN_OAUTH_TOKEN_URL,
        data=json.dumps(fields).encode("utf-8"),
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": CLAUDE_DESIGN_USER_AGENT,
        },
        method="POST",
    )
    try:
        with opener(request, timeout=30) as response:
            body = response.read(CLAUDE_DESIGN_OAUTH_RESPONSE_MAX_BYTES + 1)
    except urllib.error.HTTPError as error:
        detail = ""
        try:
            parsed = json.loads(error.read(CLAUDE_DESIGN_OAUTH_RESPONSE_MAX_BYTES).decode("utf-8"))
            if isinstance(parsed, dict):
                candidate = parsed.get("error_description") or parsed.get("error")
                detail = f": {candidate}" if isinstance(candidate, str) else ""
        except (UnicodeDecodeError, json.JSONDecodeError):
            pass
        raise DesignAuthError(f"Claude Design authorization was rejected (HTTP {error.code}){detail}.") from error
    except urllib.error.URLError as error:
        raise DesignAuthError(f"Could not reach the Claude authorization service: {error.reason}") from error
    if len(body) > CLAUDE_DESIGN_OAUTH_RESPONSE_MAX_BYTES:
        raise DesignAuthError("Claude authorization returned an oversized response.")
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise DesignAuthError("Claude authorization returned unreadable JSON.") from error
    if not isinstance(payload, dict):
        raise DesignAuthError("Claude authorization returned a non-object response.")
    return payload


def _credential_payload(
    token: dict[str, object],
    *,
    client_id: str,
    fallback_refresh_token: str | None = None,
    now_ms: int | None = None,
) -> dict[str, object]:
    access_token = token.get("access_token")
    refresh_token = token.get("refresh_token", fallback_refresh_token)
    expires_in = token.get("expires_in")
    raw_scope = token.get("scope")
    scopes = raw_scope.split() if isinstance(raw_scope, str) else []
    if not isinstance(access_token, str) or not access_token:
        raise DesignAuthError("Claude authorization returned no access token.")
    if not isinstance(refresh_token, str) or not refresh_token:
        raise DesignAuthError("Claude authorization returned no refresh token.")
    if not isinstance(expires_in, int | float) or expires_in <= 0:
        raise DesignAuthError("Claude authorization returned no valid expiry.")
    missing = [scope for scope in CLAUDE_DESIGN_OAUTH_SCOPES if scope not in scopes]
    if missing:
        raise DesignAuthError("Claude authorization did not grant the required Design scopes: " + ", ".join(missing))
    current = int(time.time() * 1000) if now_ms is None else now_ms
    return {
        "designOauth": {
            "accessToken": access_token,
            "refreshToken": refresh_token,
            "expiresAt": current + int(float(expires_in) * 1000),
            "scopes": list(CLAUDE_DESIGN_OAUTH_SCOPES),
            "clientId": client_id,
        }
    }


def _authorize_url(*, redirect_uri: str, challenge: str, state: str) -> str:
    query = urlencode(
        {
            "code": "true",
            "client_id": CLAUDE_DESIGN_OAUTH_CLIENT_ID,
            "response_type": "code",
            "redirect_uri": redirect_uri,
            "scope": " ".join(CLAUDE_DESIGN_OAUTH_SCOPES),
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "state": state,
        }
    )
    return f"{CLAUDE_DESIGN_OAUTH_AUTHORIZE_URL}?{query}"


class _CallbackServer(HTTPServer):
    expected_state: str
    authorization_code: str | None = None
    error_message: str | None = None


class _CallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 - stdlib callback name
        server = cast(_CallbackServer, self.server)
        parsed = urlparse(self.path)
        if parsed.path != "/callback":
            self.send_error(404)
            return
        parameters = parse_qs(parsed.query)
        state = parameters.get("state", [""])[0]
        if state != server.expected_state:
            server.error_message = "Claude authorization returned an invalid state."
            self.send_error(400, "Invalid state")
            return
        error = parameters.get("error", [""])[0]
        if error:
            description = parameters.get("error_description", [""])[0]
            server.error_message = description or error
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"Claude Design authorization was canceled. You can close this window.")
            return
        code = parameters.get("code", [""])[0]
        if not code:
            server.error_message = "Claude authorization returned no code."
            self.send_error(400, "Missing code")
            return
        server.authorization_code = code
        self.send_response(302)
        self.send_header("Location", CLAUDE_DESIGN_OAUTH_SUCCESS_URL)
        self.end_headers()

    def log_message(self, format: str, *_args: object) -> None:
        del format
        return


def _open_browser(
    url: str,
    *,
    platform: str = sys.platform,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> bool:
    if platform == "darwin":
        command = ["/usr/bin/open", url]
    elif platform.startswith("linux"):
        wslview = shutil.which("wslview")
        cmd = shutil.which("cmd.exe") if os.environ.get("WSL_DISTRO_NAME") else None
        if wslview:
            command = [wslview, url]
        elif cmd:
            command = [cmd, "/c", "start", "", f'"{url}"']
        else:
            opener = shutil.which("xdg-open")
            if not opener:
                return False
            command = [opener, url]
    else:
        return False
    try:
        result = runner(command, capture_output=True, text=True, shell=False, timeout=10, check=False)
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0


def automatic_browser_login_available(
    *,
    platform: str = sys.platform,
    environment: Mapping[str, str] = os.environ,
    container_marker: Path = Path("/.dockerenv"),
) -> bool:
    """Return whether automatic localhost OAuth is appropriate for this runtime."""
    override = environment.get(CLAUDE_DESIGN_BROWSER_LOGIN_ENV, "").lower()
    if override in {"1", "true", "yes"}:
        return True
    if override in {"0", "false", "no"}:
        return False
    if environment.get("CI", "").lower() in {"1", "true", "yes"}:
        return False
    if any(environment.get(name) for name in ("REMOTE_CONTAINERS", "CODESPACES", "SSH_CONNECTION")):
        return False
    if container_marker.exists():
        return False
    if platform == "darwin":
        return True
    if platform.startswith("linux"):
        if environment.get("WSL_DISTRO_NAME"):
            return True
        return bool(environment.get("DISPLAY") or environment.get("WAYLAND_DISPLAY"))
    return False


def login_design(
    *,
    manual: bool = False,
    timeout_seconds: int = CLAUDE_DESIGN_OAUTH_TIMEOUT_SECONDS,
    platform: str = sys.platform,
    home: Path | None = None,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    token_opener: Callable[..., _Response] = _TOKEN_OPENER.open,
    input_reader: Callable[[str], str] = getpass.getpass,
    emit: Callable[[str], None] = print,
    allow_manual_fallback: bool = True,
) -> dict[str, object]:
    """Authorize a Claude.ai account without requiring Claude Code."""
    if platform != "darwin" and not platform.startswith("linux"):
        raise DesignAuthError("Open Claude Design login supports macOS, Linux, and WSL2.")
    verifier = _base64url(secrets.token_bytes(32))
    challenge = _base64url(hashlib.sha256(verifier.encode("ascii")).digest())
    state = _base64url(secrets.token_bytes(32))
    server: _CallbackServer | None = None
    try:
        if manual:
            redirect_uri = CLAUDE_DESIGN_OAUTH_MANUAL_REDIRECT_URL
            authorize_url = _authorize_url(redirect_uri=redirect_uri, challenge=challenge, state=state)
            emit("Open this URL in a browser to authorize Claude Design:")
            emit(authorize_url)
            try:
                pasted = input_reader("Paste the code#state value: ").strip()
            except (EOFError, KeyboardInterrupt) as error:
                raise DesignAuthError(
                    "Manual Claude Design login needs an interactive terminal. Run "
                    "open-claude-design login --manual there and paste the returned code into that terminal, "
                    "not into a coding-agent chat."
                ) from error
            code, separator, returned_state = pasted.partition("#")
            if not separator or not code or returned_state != state:
                raise DesignAuthError("The pasted authorization code or state is invalid.")
        else:
            server = _CallbackServer(("127.0.0.1", 0), _CallbackHandler)
            server.expected_state = state
            redirect_uri = f"http://localhost:{server.server_port}/callback"
            automatic_url = _authorize_url(redirect_uri=redirect_uri, challenge=challenge, state=state)
            manual_url = _authorize_url(
                redirect_uri=CLAUDE_DESIGN_OAUTH_MANUAL_REDIRECT_URL,
                challenge=challenge,
                state=state,
            )
            emit("Opening Claude Design authorization in your browser...")
            if not _open_browser(automatic_url, platform=platform, runner=runner):
                server.server_close()
                server = None
                if not allow_manual_fallback:
                    raise DesignAuthError(
                        "No local browser could be opened. Run open-claude-design login --manual in an "
                        "interactive terminal; open its URL on your host browser and paste the returned code "
                        "back into that terminal."
                    )
                return login_design(
                    manual=True,
                    timeout_seconds=timeout_seconds,
                    platform=platform,
                    home=home,
                    runner=runner,
                    token_opener=token_opener,
                    input_reader=input_reader,
                    emit=emit,
                    allow_manual_fallback=allow_manual_fallback,
                )
            emit("Browser did not open? Use this URL and paste the returned code:")
            emit(manual_url)
            deadline = time.monotonic() + timeout_seconds
            while server.authorization_code is None and server.error_message is None and time.monotonic() < deadline:
                server.timeout = min(1.0, max(0.05, deadline - time.monotonic()))
                server.handle_request()
            if server.error_message:
                raise DesignAuthError(f"Claude Design authorization failed: {server.error_message}")
            if server.authorization_code is None:
                raise DesignAuthError("Claude Design authorization timed out. Retry with --manual if needed.")
            code = server.authorization_code
        token = _request_token(
            {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
                "client_id": CLAUDE_DESIGN_OAUTH_CLIENT_ID,
                "code_verifier": verifier,
                "state": state,
            },
            opener=token_opener,
        )
        payload = _credential_payload(token, client_id=CLAUDE_DESIGN_OAUTH_CLIENT_ID)
        save_standalone_credential(payload, platform=platform, home=home, runner=runner)
        oauth = payload["designOauth"]
        assert isinstance(oauth, dict)
        emit("Claude Design is connected.")
        return {"authenticated": True, "expiresAt": oauth["expiresAt"], "scopes": oauth["scopes"]}
    finally:
        if server is not None:
            server.server_close()
