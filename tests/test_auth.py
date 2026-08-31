"""Standalone Claude Design OAuth and credential-store contracts."""

from __future__ import annotations

import base64
import http.client
import json
import stat
import subprocess
import threading
import urllib.request
from email.message import Message
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest

import open_claude_design.auth as auth
from open_claude_design.config import (
    CLAUDE_DESIGN_OAUTH_CLIENT_ID,
    CLAUDE_DESIGN_OAUTH_MANUAL_REDIRECT_URL,
    CLAUDE_DESIGN_OAUTH_SCOPES,
    CLAUDE_DESIGN_USER_AGENT,
)

pytestmark = pytest.mark.unit


class FakeResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self.body = json.dumps(payload).encode("utf-8")
        self.headers = Message()
        self.headers["Content-Type"] = "application/json"

    def read(self, amount: int | None = None) -> bytes:
        return self.body if amount is None else self.body[:amount]

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *_args: object) -> None:
        return None


def _token_response(*, access: str = "access-value", refresh: str = "refresh-value") -> dict[str, object]:
    return {
        "access_token": access,
        "refresh_token": refresh,
        "expires_in": 3600,
        "scope": " ".join(CLAUDE_DESIGN_OAUTH_SCOPES),
    }


def test_manual_login_uses_pkce_and_persists_without_claude_code(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    random_values = [b"a" * 32, b"b" * 32]
    original_token_bytes = auth.secrets.token_bytes

    def token_bytes(size: int | None = None) -> bytes:
        return random_values.pop(0) if random_values else original_token_bytes(size)

    monkeypatch.setattr(auth.secrets, "token_bytes", token_bytes)
    expected_state = base64.urlsafe_b64encode(b"b" * 32).decode("ascii").rstrip("=")
    requests: list[dict[str, Any]] = []

    def opener(request: urllib.request.Request, *, timeout: int) -> FakeResponse:
        assert timeout == 30
        requests.append(json.loads(bytes(request.data or b"").decode("utf-8")))
        return FakeResponse(_token_response())

    messages: list[str] = []
    result = auth.login_design(
        manual=True,
        platform="linux",
        home=tmp_path,
        token_opener=opener,
        input_reader=lambda _prompt: f"authorization-code#{expected_state}",
        emit=messages.append,
    )

    assert result["authenticated"] is True
    assert requests == [
        {
            "grant_type": "authorization_code",
            "code": "authorization-code",
            "redirect_uri": CLAUDE_DESIGN_OAUTH_MANUAL_REDIRECT_URL,
            "client_id": CLAUDE_DESIGN_OAUTH_CLIENT_ID,
            "code_verifier": base64.urlsafe_b64encode(b"a" * 32).decode("ascii").rstrip("="),
            "state": expected_state,
        }
    ]
    stored = auth.load_standalone_credential(platform="linux", home=tmp_path, now_ms=0)
    assert stored is not None
    stored_oauth = stored["designOauth"]
    assert isinstance(stored_oauth, dict)
    assert stored_oauth["accessToken"] == "access-value"
    assert "access-value" not in "\n".join(messages)
    credential = tmp_path.joinpath(".config", "open-claude-design", "credentials.json")
    assert stat.S_IMODE(credential.stat().st_mode) == 0o600


def _localhost_browser_runner(
    visit: Any,
) -> Any:
    """Return a fake browser runner that hits the login callback like a real browser."""

    def runner(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        url = command[-1]
        parameters = parse_qs(urlparse(url).query)
        state = parameters["state"][0]
        redirect = urlparse(parameters["redirect_uri"][0])
        assert redirect.hostname == "localhost"
        port = redirect.port
        assert port is not None
        threading.Thread(target=visit, args=(port, state), daemon=True).start()
        return subprocess.CompletedProcess(command, 0, "", "")

    return runner


def _get_callback(port: int, query: str) -> None:
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        connection.request("GET", f"/callback?{query}")
        connection.getresponse().read()
    finally:
        connection.close()


def test_automatic_login_serves_the_localhost_callback_and_persists(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("WSL_DISTRO_NAME", raising=False)
    monkeypatch.setattr(auth.shutil, "which", lambda name: "/usr/bin/xdg-open" if name == "xdg-open" else None)
    requests: list[dict[str, Any]] = []

    def opener(request: urllib.request.Request, *, timeout: int) -> FakeResponse:
        requests.append(json.loads(bytes(request.data or b"").decode("utf-8")))
        return FakeResponse(_token_response(access="callback-access"))

    def visit(port: int, state: str) -> None:
        _get_callback(port, f"code=browser-code&state={state}")

    messages: list[str] = []
    result = auth.login_design(
        timeout_seconds=10,
        platform="linux",
        home=tmp_path,
        runner=_localhost_browser_runner(visit),
        token_opener=opener,
        emit=messages.append,
    )

    assert result["authenticated"] is True
    assert requests[0]["grant_type"] == "authorization_code"
    assert requests[0]["code"] == "browser-code"
    assert requests[0]["redirect_uri"].startswith("http://localhost:")
    stored = auth.load_standalone_credential(platform="linux", home=tmp_path, now_ms=0)
    assert stored is not None
    stored_oauth = stored["designOauth"]
    assert isinstance(stored_oauth, dict)
    assert stored_oauth["accessToken"] == "callback-access"
    assert "callback-access" not in "\n".join(messages)


def test_automatic_login_rejects_a_callback_with_the_wrong_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("WSL_DISTRO_NAME", raising=False)
    monkeypatch.setattr(auth.shutil, "which", lambda name: "/usr/bin/xdg-open" if name == "xdg-open" else None)

    def visit(port: int, _state: str) -> None:
        _get_callback(port, "code=browser-code&state=forged-state")

    def opener(_request: urllib.request.Request, *, timeout: int) -> FakeResponse:
        raise AssertionError(f"no token request may follow a forged state (timeout={timeout})")

    with pytest.raises(auth.DesignAuthError, match="invalid state"):
        auth.login_design(
            timeout_seconds=10,
            platform="linux",
            home=tmp_path,
            runner=_localhost_browser_runner(visit),
            token_opener=opener,
            emit=lambda _message: None,
        )

    assert auth.load_standalone_credential(platform="linux", home=tmp_path, now_ms=0) is None


def test_automatic_browser_login_detection_is_safe_for_headless_runtimes(tmp_path: Path) -> None:
    no_container = tmp_path / "no-container-marker"
    container = tmp_path / "container-marker"
    container.touch()

    assert auth.automatic_browser_login_available(
        platform="darwin",
        environment={},
        container_marker=no_container,
    )
    assert auth.automatic_browser_login_available(
        platform="linux",
        environment={"DISPLAY": ":0"},
        container_marker=no_container,
    )
    assert auth.automatic_browser_login_available(
        platform="linux",
        environment={"WSL_DISTRO_NAME": "Ubuntu"},
        container_marker=no_container,
    )
    assert not auth.automatic_browser_login_available(
        platform="linux",
        environment={},
        container_marker=no_container,
    )
    assert not auth.automatic_browser_login_available(
        platform="linux",
        environment={"DISPLAY": ":0"},
        container_marker=container,
    )
    assert not auth.automatic_browser_login_available(
        platform="linux",
        environment={"DISPLAY": ":0", "SSH_CONNECTION": "host"},
        container_marker=no_container,
    )
    assert auth.automatic_browser_login_available(
        platform="linux",
        environment={"CI": "true", "OPEN_CLAUDE_DESIGN_BROWSER_LOGIN": "1"},
        container_marker=container,
    )


def test_automatic_login_does_not_fall_into_manual_input_when_noninteractive(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("WSL_DISTRO_NAME", raising=False)
    monkeypatch.setattr(auth.shutil, "which", lambda _name: None)

    with pytest.raises(auth.DesignAuthError, match="No local browser could be opened"):
        auth.login_design(
            platform="linux",
            home=tmp_path,
            runner=lambda *_args, **_kwargs: pytest.fail("no browser command should exist"),
            input_reader=lambda _prompt: pytest.fail("manual input must not be attempted"),
            emit=lambda _message: None,
            allow_manual_fallback=False,
        )


def test_manual_login_reports_noninteractive_terminal_without_traceback(tmp_path: Path) -> None:
    def raise_eof(_prompt: str) -> str:
        raise EOFError

    with pytest.raises(auth.DesignAuthError, match="interactive terminal"):
        auth.login_design(
            manual=True,
            platform="linux",
            home=tmp_path,
            input_reader=raise_eof,
            emit=lambda _message: None,
        )


def test_refresh_uses_stored_client_and_rotates_credential(tmp_path: Path) -> None:
    auth.save_standalone_credential(
        {
            "designOauth": {
                "accessToken": "expired-access",
                "refreshToken": "old-refresh",
                "expiresAt": 1,
                "scopes": list(CLAUDE_DESIGN_OAUTH_SCOPES),
                "clientId": CLAUDE_DESIGN_OAUTH_CLIENT_ID,
            }
        },
        platform="linux",
        home=tmp_path,
    )
    requests: list[dict[str, Any]] = []

    def opener(request: urllib.request.Request, *, timeout: int) -> FakeResponse:
        assert timeout == 30
        requests.append(json.loads(bytes(request.data or b"").decode("utf-8")))
        return FakeResponse(_token_response(access="new-access", refresh="new-refresh"))

    payload = auth.load_standalone_credential(
        platform="linux",
        home=tmp_path,
        now_ms=1_000,
        token_opener=opener,
    )

    assert payload is not None
    refreshed_oauth = payload["designOauth"]
    assert isinstance(refreshed_oauth, dict)
    assert refreshed_oauth["accessToken"] == "new-access"
    assert requests[0]["grant_type"] == "refresh_token"
    assert requests[0]["refresh_token"] == "old-refresh"


def test_keychain_write_keeps_tokens_out_of_argv() -> None:
    calls: list[tuple[list[str], dict[str, object]]] = []

    def runner(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, "", "")

    auth.save_standalone_credential(
        {"designOauth": {"accessToken": "secret-access", "refreshToken": "secret-refresh"}},
        platform="darwin",
        runner=runner,
    )

    command, kwargs = calls[0]
    assert "secret-access" not in " ".join(command)
    assert "secret-refresh" not in " ".join(command)
    assert str(kwargs["input"]).count("secret-access") == 2
    assert kwargs["shell"] is False


def test_token_request_sends_a_product_user_agent(tmp_path: Path) -> None:
    # Cloudflare answers the default "Python-urllib/3.x" agent with Error 1010, which
    # surfaces as "authorization was rejected (HTTP 403)" and fails every login.
    seen: list[str | None] = []
    messages: list[str] = []

    def opener(request: urllib.request.Request, *, timeout: int) -> FakeResponse:
        seen.append(request.get_header("User-agent"))
        return FakeResponse(_token_response())

    def reply(_prompt: str) -> str:
        authorize_url = next(line for line in messages if line.startswith("https://"))
        state = parse_qs(urlparse(authorize_url).query)["state"][0]
        return f"authorization-code#{state}"

    auth.login_design(
        manual=True,
        platform="linux",
        home=tmp_path,
        token_opener=opener,
        input_reader=reply,
        emit=messages.append,
    )

    assert seen == [CLAUDE_DESIGN_USER_AGENT]
    assert "python-urllib" not in str(seen[0]).lower()


def test_authorize_url_is_registered_public_client_with_exact_design_scopes() -> None:
    url = auth._authorize_url(
        redirect_uri="http://localhost:1234/callback",
        challenge="challenge",
        state="state",
    )
    parsed = urlparse(url)
    parameters = parse_qs(parsed.query)

    assert parsed.scheme == "https"
    assert parsed.netloc == "claude.com"
    assert parameters["client_id"] == [CLAUDE_DESIGN_OAUTH_CLIENT_ID]
    assert parameters["scope"] == [" ".join(CLAUDE_DESIGN_OAUTH_SCOPES)]
    assert parameters["code_challenge_method"] == ["S256"]
    assert parameters["redirect_uri"] == ["http://localhost:1234/callback"]


def test_delete_standalone_linux_credential_is_exact_and_idempotent(tmp_path: Path) -> None:
    auth.save_standalone_credential(
        {"designOauth": {"accessToken": "a"}},
        platform="linux",
        home=tmp_path,
    )

    assert auth.delete_standalone_credential(platform="linux", home=tmp_path) is True
    assert auth.delete_standalone_credential(platform="linux", home=tmp_path) is False
    assert tmp_path.joinpath(".config", "open-claude-design").is_dir()


def test_linux_credential_write_rejects_symlinked_parent(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (tmp_path / ".config").symlink_to(outside, target_is_directory=True)

    with pytest.raises(auth.DesignAuthError, match="symlinked or unsafe"):
        auth.save_standalone_credential(
            {"designOauth": {"accessToken": "secret"}},
            platform="linux",
            home=tmp_path,
        )

    assert not (outside / "open-claude-design" / "credentials.json").exists()


def test_wsl_browser_open_uses_quoted_windows_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WSL_DISTRO_NAME", "Ubuntu")
    monkeypatch.setattr(
        auth.shutil,
        "which",
        lambda name: "/mnt/c/Windows/System32/cmd.exe" if name == "cmd.exe" else None,
    )
    commands: list[list[str]] = []

    def runner(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        return subprocess.CompletedProcess(command, 0, "", "")

    assert auth._open_browser("https://claude.com/cai/oauth/authorize?a=1&b=2", platform="linux", runner=runner)
    assert commands == [
        [
            "/mnt/c/Windows/System32/cmd.exe",
            "/c",
            "start",
            "",
            '"https://claude.com/cai/oauth/authorize?a=1&b=2"',
        ]
    ]
