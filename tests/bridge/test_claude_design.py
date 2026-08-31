"""Read-only-by-default Claude Design bridge contracts."""

from __future__ import annotations

import io
import json
import subprocess
import sys
from argparse import Namespace
from collections.abc import Callable
from email.message import Message
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

import open_claude_design.bridge as claude_design
from open_claude_design.bridge import (
    ClaudeDesignAuthError,
    ClaudeDesignClient,
    ClaudeDesignCredential,
    ClaudeDesignProtocolError,
    ClaudeDesignSafetyError,
    _RejectAuthenticatedRedirects,
    parse_mcp_response,
    read_design_credential,
    run_design_command,
)

pytestmark = pytest.mark.unit


class FakeResponse:
    """Minimal urllib response for deterministic MCP transport tests."""

    def __init__(
        self,
        payload: dict[str, Any] | None,
        *,
        status: int = 200,
        content_type: str = "application/json",
        session_id: str | None = None,
    ) -> None:
        self.status = status
        self._body = b"" if payload is None else json.dumps(payload).encode()
        self.headers = Message()
        self.headers["Content-Type"] = content_type
        if session_id:
            self.headers["Mcp-Session-Id"] = session_id

    def read(self, amount: int | None = None) -> bytes:
        return self._body if amount is None else self._body[:amount]

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *_args: object) -> None:
        return None


def _credential_runner(payload: dict[str, Any]) -> Callable[..., subprocess.CompletedProcess[str]]:
    def run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        assert args[0] == [
            "/usr/bin/security",
            "find-generic-password",
            "-s",
            "Claude Code-credentials",
            "-w",
        ]
        assert kwargs["capture_output"] is True
        assert kwargs["text"] is True
        assert kwargs["shell"] is False
        return subprocess.CompletedProcess(args[0], 0, json.dumps(payload), "")

    return run


def _no_standalone(**_kwargs: object) -> None:
    return None


def test_read_design_credential_extracts_only_scoped_fields_and_normalizes_seconds() -> None:
    credential = read_design_credential(
        platform="darwin",
        runner=_credential_runner(
            {
                "designOauth": {
                    "accessToken": "secret-access-token",
                    "refreshToken": "must-not-escape",
                    "expiresAt": 2_000_000_000,
                    "scopes": ["user:design:read", "user:design:write"],
                }
            }
        ),
        now_ms=1_900_000_000_000,
        standalone_reader=_no_standalone,
    )

    assert credential.access_token == "secret-access-token"
    assert credential.expires_at_ms == 2_000_000_000_000
    assert credential.scopes == ("user:design:read", "user:design:write")
    assert not hasattr(credential, "refresh_token")


def test_read_design_credential_prefers_standalone_store_over_claude_code() -> None:
    credential = read_design_credential(
        platform="darwin",
        runner=MagicMock(side_effect=AssertionError("legacy keychain must not be read")),
        now_ms=1_900_000_000_000,
        standalone_reader=lambda **_kwargs: {
            "designOauth": {
                "accessToken": "standalone-token",
                "expiresAt": 2_000_000_000_000,
                "scopes": ["user:design:read", "user:design:write"],
            }
        },
    )

    assert credential.access_token == "standalone-token"


def _write_linux_credential(config_dir: Path, payload: dict[str, Any], *, mode: int = 0o600) -> Path:
    credential_path = config_dir / ".credentials.json"
    credential_path.write_text(json.dumps(payload), encoding="utf-8")
    credential_path.chmod(mode)
    return credential_path


def test_read_design_credential_supports_linux_and_wsl2(tmp_path: Path) -> None:
    _write_linux_credential(
        tmp_path,
        {
            "designOauth": {
                "accessToken": "linux-design-token",
                "expiresAt": 2_000_000_000_000,
                "scopes": ["user:design:read"],
            }
        },
    )

    credential = read_design_credential(
        platform="linux",
        config_dir=tmp_path,
        now_ms=1_900_000_000_000,
        standalone_reader=_no_standalone,
    )

    assert credential.access_token == "linux-design-token"
    assert credential.scopes == ("user:design:read",)


def test_read_design_credential_rejects_broad_linux_permissions(tmp_path: Path) -> None:
    _write_linux_credential(
        tmp_path,
        {"designOauth": {"accessToken": "secret", "expiresAt": 2_000_000_000_000}},
        mode=0o644,
    )

    with pytest.raises(ClaudeDesignAuthError, match="0600"):
        read_design_credential(
            platform="linux",
            config_dir=tmp_path,
            now_ms=0,
            standalone_reader=_no_standalone,
        )


def test_read_design_credential_rejects_linux_symlink(tmp_path: Path) -> None:
    real_dir = tmp_path / "real"
    real_dir.mkdir()
    _write_linux_credential(
        real_dir,
        {"designOauth": {"accessToken": "secret", "expiresAt": 2_000_000_000_000}},
    )
    linked_dir = tmp_path / "linked"
    linked_dir.symlink_to(real_dir, target_is_directory=True)

    with pytest.raises(ClaudeDesignAuthError, match="safely readable"):
        read_design_credential(
            platform="linux",
            config_dir=linked_dir,
            now_ms=0,
            standalone_reader=_no_standalone,
        )


def test_read_design_credential_fails_closed_on_unsupported_platform() -> None:
    with pytest.raises(ClaudeDesignAuthError, match="Linux, and WSL2"):
        read_design_credential(
            platform="win32",
            runner=MagicMock(),
            now_ms=0,
            standalone_reader=_no_standalone,
        )


def test_read_design_credential_requires_design_login() -> None:
    with pytest.raises(ClaudeDesignAuthError, match="open-claude-design login"):
        read_design_credential(
            platform="darwin",
            runner=_credential_runner({"oauthAccount": {"accessToken": "unrelated"}}),
            now_ms=0,
            standalone_reader=_no_standalone,
        )


def test_parse_mcp_response_supports_json_and_sse() -> None:
    assert parse_mcp_response(b'{"jsonrpc":"2.0","id":1,"result":{"ok":true}}', "application/json") == {
        "jsonrpc": "2.0",
        "id": 1,
        "result": {"ok": True},
    }
    assert parse_mcp_response(
        b'event: message\ndata: {"jsonrpc":"2.0","id":2,"result":{"ok":true}}\n\n',
        "text/event-stream",
    ) == {"jsonrpc": "2.0", "id": 2, "result": {"ok": True}}


def test_parse_mcp_response_rejects_wrong_request_id() -> None:
    with pytest.raises(ClaudeDesignProtocolError, match="different request"):
        parse_mcp_response(
            b'{"jsonrpc":"2.0","id":9,"result":{"ok":true}}',
            "application/json",
            expected_id=2,
        )


def test_mcp_response_body_limit_is_enforced() -> None:
    response = FakeResponse(None)
    response._body = b"x" * (claude_design.CLAUDE_DESIGN_MAX_RESPONSE_BYTES + 1)

    with pytest.raises(ClaudeDesignProtocolError, match="safety limit"):
        claude_design._read_bounded_response(response)


def test_authenticated_requests_never_follow_redirects() -> None:
    handler = _RejectAuthenticatedRedirects()

    assert handler.redirect_request(None, None, 302, "Found", {}, "https://attacker.invalid", "https://source") is None


def test_client_lists_tools_progressively_without_returning_token() -> None:
    responses = iter(
        [
            FakeResponse(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "result": {
                        "protocolVersion": "2025-11-25",
                        "serverInfo": {"name": "Claude Design", "version": "0.1.0"},
                    },
                },
                session_id="session-1",
            ),
            FakeResponse(None, status=202),
            FakeResponse(
                {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "result": {
                        "tools": [
                            {
                                "name": "read_file",
                                "description": "Read one project file. More details stay on describe.",
                                "inputSchema": {"type": "object"},
                                "annotations": {"readOnlyHint": True},
                            }
                        ]
                    },
                }
            ),
        ]
    )
    seen_authorization: list[str] = []

    def opener(request: Any, *, timeout: int) -> FakeResponse:
        assert timeout == 30
        seen_authorization.append(request.headers["Authorization"])
        if request.headers.get("Mcp-session-id"):
            assert request.headers["Mcp-session-id"] == "session-1"
        return next(responses)

    client = ClaudeDesignClient(token_reader=lambda: "secret-access-token", opener=opener)
    tools = client.list_tools()

    assert tools[0]["name"] == "read_file"
    assert seen_authorization == ["Bearer secret-access-token"] * 3
    assert "secret-access-token" not in json.dumps(tools)


def test_client_rejects_repeated_tool_cursor() -> None:
    class RepeatingCursorClient(ClaudeDesignClient):
        def _initialize(self) -> dict[str, Any]:
            return {}

        def _send(self, method: str, params: dict[str, Any] | None = None, *, notification: bool = False) -> Any:
            assert method == "tools/list"
            return {"tools": [], "nextCursor": "same-cursor"}

    with pytest.raises(ClaudeDesignProtocolError, match="repeated"):
        RepeatingCursorClient(token_reader=lambda: "unused").list_tools()


def test_client_refuses_to_start_write_near_credential_expiry() -> None:
    client = ClaudeDesignClient(
        credential_reader=lambda: ClaudeDesignCredential(
            access_token="secret",
            expires_at_ms=1_299_000,
            scopes=("user:design:write",),
        )
    )

    with pytest.raises(ClaudeDesignAuthError, match="expires too soon"):
        client.require_write_window(minimum_seconds=300, now_ms=1_000_000)


class StubClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []
        self.write_preflights = 0

    def require_write_window(self) -> None:
        self.write_preflights += 1

    def status(self) -> dict[str, object]:
        return {"authenticated": True, "server": {"name": "Claude Design"}}

    def list_tools(self) -> list[dict[str, object]]:
        return [
            {
                "name": "read_file",
                "description": "Read one file.",
                "inputSchema": {"type": "object"},
                "annotations": {"readOnlyHint": True},
            },
            {
                "name": "write_files",
                "description": "Write project files.",
                "inputSchema": {"type": "object"},
                "annotations": {"readOnlyHint": False},
            },
            {
                "name": "add_member",
                "description": "Add a project member.",
                "inputSchema": {"type": "object"},
                "annotations": {"readOnlyHint": False},
            },
            {
                "name": "render_preview",
                "description": "Return temporary and durable preview URLs.",
                "inputSchema": {"type": "object"},
                "annotations": {"readOnlyHint": False},
            },
            {
                "name": "delete_files",
                "description": "Delete exact project files.",
                "inputSchema": {"type": "object"},
                "annotations": {"readOnlyHint": False, "destructiveHint": True},
            },
            {
                "name": "create_support_js",
                "description": "Create support runtime.",
                "inputSchema": {"type": "object"},
                "annotations": {"readOnlyHint": False},
            },
            {
                "name": "copy_files",
                "description": "Copy project files.",
                "inputSchema": {"type": "object"},
                "annotations": {"readOnlyHint": False, "destructiveHint": True},
            },
        ]

    def call_tool(self, name: str, arguments: dict[str, object]) -> dict[str, object]:
        self.calls.append((name, arguments))
        if name in {"add_member", "write_files"}:
            return {"content": [{"type": "text", "text": '{"status":"success"}'}]}
        return {"content": [{"type": "text", "text": "ok"}]}


def test_cmd_design_blocks_mutating_tools_without_explicit_flag(capsys: pytest.CaptureFixture[str]) -> None:
    client = StubClient()
    args = Namespace(
        design_command="call",
        tool="add_member",
        args='{"project_id":"p","email":"person@example.com"}',
        allow_write=False,
        allow_guarded=False,
        json=True,
    )

    with pytest.raises(ClaudeDesignSafetyError, match="--allow-write"):
        run_design_command(args, client_factory=lambda: client)

    assert client.calls == []
    assert client.write_preflights == 0
    assert capsys.readouterr().out == ""


def test_cmd_design_allows_read_tools_without_flag(capsys: pytest.CaptureFixture[str]) -> None:
    client = StubClient()
    args = Namespace(
        design_command="call",
        tool="read_file",
        args='{"project_id":"p","path":"index.html"}',
        allow_write=False,
        allow_guarded=False,
        json=True,
    )

    assert run_design_command(args, client_factory=lambda: client) == 0
    assert client.calls == [("read_file", {"project_id": "p", "path": "index.html"})]
    output = json.loads(capsys.readouterr().out)
    assert output["tool"] == "read_file"
    assert output["result"]["content"][0]["text"] == "ok"
    assert client.write_preflights == 0


def test_authoring_context_fetches_once_then_uses_verified_local_cache(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    class AuthoringClient(StubClient):
        def call_tool(self, name: str, arguments: dict[str, object]) -> dict[str, object]:
            self.calls.append((name, arguments))
            text = "current project prompt" if name == "get_claude_design_prompt" else "current hi-fi skill"
            return {"content": [{"type": "text", "text": text}]}

    args = Namespace(
        design_command="authoring-context",
        project_id="project-1",
        design_system_id="system-1",
        skill="hifi-design",
        refresh=False,
        json=True,
    )
    client = AuthoringClient()

    assert run_design_command(args, client_factory=lambda: client, workspace_root=tmp_path) == 0

    first = json.loads(capsys.readouterr().out)
    assert first["cached"] is False
    assert client.calls == [
        (
            "get_claude_design_prompt",
            {"project_id": "project-1", "design_system_id": "system-1"},
        ),
        ("read_design_skill", {"skill": "hifi-design"}),
    ]
    assert (tmp_path / first["prompt"]["path"]).read_text(encoding="utf-8") == "current project prompt"
    assert (tmp_path / first["skill"]["path"]).read_text(encoding="utf-8") == "current hi-fi skill"
    assert (tmp_path / ".open-claude-design" / ".gitignore").read_text(encoding="utf-8") == "*\n"

    cached_client = AuthoringClient()
    assert run_design_command(args, client_factory=lambda: cached_client, workspace_root=tmp_path) == 0

    second = json.loads(capsys.readouterr().out)
    assert second["cached"] is True
    assert second["prompt"]["sha256"] == first["prompt"]["sha256"]
    assert second["skill"]["sha256"] == first["skill"]["sha256"]
    assert cached_client.calls == []


def test_authoring_context_supports_a_project_without_a_bound_design_system(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    class AuthoringClient(StubClient):
        def call_tool(self, name: str, arguments: dict[str, object]) -> dict[str, object]:
            self.calls.append((name, arguments))
            return {"content": [{"type": "text", "text": f"current {name}"}]}

    args = Namespace(
        design_command="authoring-context",
        project_id="project-1",
        design_system_id=None,
        skill="hifi-design",
        refresh=False,
        json=True,
    )
    client = AuthoringClient()

    assert run_design_command(args, client_factory=lambda: client, workspace_root=tmp_path) == 0
    assert json.loads(capsys.readouterr().out)["cached"] is False
    assert client.calls == [
        ("get_claude_design_prompt", {"project_id": "project-1"}),
        ("read_design_skill", {"skill": "hifi-design"}),
    ]


def test_known_read_only_tool_ignores_incompatible_remote_destructive_hint(
    capsys: pytest.CaptureFixture[str],
) -> None:
    class ContradictoryAnnotationStub(StubClient):
        def list_tools(self) -> list[dict[str, object]]:
            tools = super().list_tools()
            tools[0]["annotations"] = {"readOnlyHint": True, "destructiveHint": True}
            return tools

    client = ContradictoryAnnotationStub()
    args = Namespace(
        design_command="call",
        tool="read_file",
        args='{"project_id":"p","path":"index.html"}',
        allow_write=False,
        allow_destructive=False,
        allow_guarded=False,
        json=True,
    )

    assert run_design_command(args, client_factory=lambda: client) == 0
    assert client.write_preflights == 0
    assert json.loads(capsys.readouterr().out)["tool"] == "read_file"


def test_cmd_design_preflights_authorized_remote_write(capsys: pytest.CaptureFixture[str]) -> None:
    client = StubClient()
    args = Namespace(
        design_command="call",
        tool="add_member",
        args='{"project_id":"p","email":"person@example.com"}',
        allow_write=True,
        allow_guarded=False,
        json=True,
    )

    assert run_design_command(args, client_factory=lambda: client) == 0
    assert client.write_preflights == 1
    assert client.calls == [("add_member", {"project_id": "p", "email": "person@example.com"})]
    assert json.loads(capsys.readouterr().out)["tool"] == "add_member"


def test_generic_delete_is_disabled_even_with_write_permission() -> None:
    client = StubClient()
    args = Namespace(
        design_command="call",
        tool="delete_files",
        args='{"project_id":"p","paths":["Obsolete.dc.html"]}',
        allow_write=True,
        allow_destructive=True,
        allow_guarded=False,
        json=True,
    )

    with pytest.raises(ClaudeDesignSafetyError, match="Generic delete_files calls are disabled"):
        run_design_command(args, client_factory=lambda: client)

    assert client.calls == []
    assert client.write_preflights == 0


def test_known_mutator_cannot_be_downgraded_by_remote_read_only_annotation() -> None:
    class MisannotatedStub(StubClient):
        def list_tools(self) -> list[dict[str, object]]:
            tools = super().list_tools()
            for tool in tools:
                if tool["name"] == "add_member":
                    tool["annotations"] = {"readOnlyHint": True}
            return tools

    client = MisannotatedStub()
    args = Namespace(
        design_command="call",
        tool="add_member",
        args='{"project_id":"p","email":"person@example.com"}',
        allow_write=False,
        allow_guarded=False,
        json=True,
    )

    with pytest.raises(ClaudeDesignSafetyError, match="--allow-write"):
        run_design_command(args, client_factory=lambda: client)

    assert client.calls == []


def test_unknown_remote_read_only_tool_requires_write_acknowledgement() -> None:
    class FutureToolStub(StubClient):
        def list_tools(self) -> list[dict[str, object]]:
            return [
                {
                    "name": "future_lookup",
                    "inputSchema": {"type": "object"},
                    "annotations": {"readOnlyHint": True},
                }
            ]

        def call_tool(self, name: str, arguments: dict[str, object]) -> dict[str, object]:
            self.calls.append((name, arguments))
            return {"structuredContent": {"status": "success"}}

    client = FutureToolStub()
    args = Namespace(
        design_command="call",
        tool="future_lookup",
        args="{}",
        allow_write=False,
        allow_guarded=False,
        json=True,
    )

    with pytest.raises(ClaudeDesignSafetyError, match="--allow-write"):
        run_design_command(args, client_factory=lambda: client)

    args.allow_guarded = True
    with pytest.raises(ClaudeDesignSafetyError, match="--allow-write"):
        run_design_command(args, client_factory=lambda: client)

    args.allow_write = True
    assert run_design_command(args, client_factory=lambda: client) == 0
    assert client.write_preflights == 1


def test_plain_text_mutation_result_fails_closed(capsys: pytest.CaptureFixture[str]) -> None:
    class PlainMutationStub(StubClient):
        def call_tool(self, name: str, arguments: dict[str, object]) -> dict[str, object]:
            self.calls.append((name, arguments))
            return {"content": [{"type": "text", "text": "ok"}]}

    client = PlainMutationStub()
    args = Namespace(
        design_command="call",
        tool="add_member",
        args='{"project_id":"p","email":"person@example.com"}',
        allow_write=True,
        allow_guarded=False,
        json=True,
    )

    assert run_design_command(args, client_factory=lambda: client) == 2
    assert json.loads(capsys.readouterr().out)["tool"] == "add_member"


def test_structured_mutation_result_must_match_requested_entity(capsys: pytest.CaptureFixture[str]) -> None:
    class WrongEntityStub(StubClient):
        def call_tool(self, name: str, arguments: dict[str, object]) -> dict[str, object]:
            self.calls.append((name, arguments))
            return {
                "structuredContent": {
                    "status": "success",
                    "project_id": "wrong-project",
                    "paths": ["Other.dc.html"],
                }
            }

    client = WrongEntityStub()
    args = Namespace(
        design_command="call",
        tool="add_member",
        args='{"project_id":"p","email":"person@example.com"}',
        allow_write=True,
        allow_guarded=False,
        json=True,
    )

    assert run_design_command(args, client_factory=lambda: client) == 2
    assert json.loads(capsys.readouterr().out)["tool"] == "add_member"


def test_unrecognized_structured_mutation_result_fails_closed(capsys: pytest.CaptureFixture[str]) -> None:
    class UnexpectedResultStub(StubClient):
        def call_tool(self, name: str, arguments: dict[str, object]) -> dict[str, object]:
            self.calls.append((name, arguments))
            return {"structuredContent": {"unexpected": "value"}}

    args = Namespace(
        design_command="call",
        tool="add_member",
        args='{"project_id":"p","email":"person@example.com"}',
        allow_write=True,
        allow_guarded=False,
        json=True,
    )

    assert run_design_command(args, client_factory=UnexpectedResultStub) == 2
    assert json.loads(capsys.readouterr().out)["tool"] == "add_member"


def test_generic_output_escapes_terminal_format_controls(capsys: pytest.CaptureFixture[str]) -> None:
    class BidiStub(StubClient):
        def call_tool(self, name: str, arguments: dict[str, object]) -> dict[str, object]:
            self.calls.append((name, arguments))
            return {"structuredContent": {"label": "safe\u202ereversed"}}

    args = Namespace(
        design_command="call",
        tool="read_file",
        args='{"project_id":"p","path":"index.html"}',
        allow_write=False,
        allow_guarded=False,
        json=True,
    )

    assert run_design_command(args, client_factory=BidiStub) == 0
    output = capsys.readouterr().out
    assert "\u202e" not in output
    assert "\\u202e" in output


def test_preview_exposes_only_durable_url(capsys: pytest.CaptureFixture[str]) -> None:
    class PreviewStub(StubClient):
        def call_tool(self, name: str, arguments: dict[str, object]) -> dict[str, object]:
            self.calls.append((name, arguments))
            return {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(
                            {
                                "serve_url": "https://private.invalid/capability",
                                "open_url": "https://claude.ai/design/project",
                            }
                        ),
                    }
                ]
            }

    client = PreviewStub()
    args = Namespace(
        design_command="preview",
        project_id="p",
        remote_path="Example.dc.html",
        open_browser=False,
        json=True,
    )

    assert run_design_command(args, client_factory=lambda: client) == 0
    output = capsys.readouterr().out
    assert "private.invalid" not in output
    assert "serve_url" not in output
    assert "claude.ai/design/project" in output


def test_preview_open_uses_short_lived_render_without_exposing_it(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    class PreviewStub(StubClient):
        def call_tool(self, name: str, arguments: dict[str, object]) -> dict[str, object]:
            self.calls.append((name, arguments))
            return {
                "structuredContent": {
                    "serve_url": "https://preview-1.claudeusercontent.com/render",
                    "open_url": "https://claude.ai/design/project",
                }
            }

    opened: list[str] = []
    monkeypatch.setattr(claude_design, "_open_preview_url", opened.append)
    args = Namespace(
        design_command="preview",
        project_id="p",
        remote_path="Example.dc.html",
        open_browser=True,
        json=True,
    )

    assert run_design_command(args, client_factory=PreviewStub) == 0
    assert opened == ["https://preview-1.claudeusercontent.com/render"]
    output = capsys.readouterr().out
    assert "claudeusercontent.com" not in output
    assert json.loads(output)["opened"] is True


@pytest.mark.parametrize(
    "url",
    [
        "http://preview.claudeusercontent.com/render",
        "https://evil.example\\@preview-1.claudeusercontent.com/render",
        "https://attacker@preview.claudeusercontent.com/render",
        "https://preview.claudeusercontent.com:444/render",
        "https://claudeusercontent.com.attacker.example/render",
        "https://attacker.example/render",
    ],
)
def test_preview_open_rejects_untrusted_short_lived_urls(url: str) -> None:
    with pytest.raises(ClaudeDesignProtocolError, match="preview URL"):
        claude_design._validate_serve_preview_url(url)


@pytest.mark.parametrize(
    "url",
    [
        "https://evil.example\\@claude.ai/design/project",
        "https://attacker@claude.ai/design/project",
        "https://claude.ai:444/design/project",
        "https://claude.ai.attacker.example/design/project",
    ],
)
def test_durable_preview_rejects_browser_parser_differentials(url: str) -> None:
    with pytest.raises(ClaudeDesignProtocolError, match="preview URL"):
        claude_design._validate_durable_preview_url(url)


def test_cmd_design_requires_valid_object_arguments() -> None:
    args = Namespace(
        design_command="call",
        tool="read_file",
        args="[]",
        allow_write=False,
        allow_guarded=False,
        json=True,
    )

    with pytest.raises(ValueError, match="JSON object"):
        run_design_command(args, client_factory=StubClient)


class FileStubClient(StubClient):
    def __init__(self) -> None:
        super().__init__()
        self.written: dict[str, str] = {}

    def call_tool(self, name: str, arguments: dict[str, object]) -> dict[str, object]:
        self.calls.append((name, arguments))
        if name == "read_file":
            path = str(arguments["path"])
            if path in self.written:
                body = self.written[path]
                escaped = body.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                return {
                    "content": [
                        {
                            "type": "text",
                            "text": (
                                f'<untrusted-project-content path="{path}" etag="124">\n'
                                f"{escaped}</untrusted-project-content>"
                            ),
                        }
                    ]
                }
            return {
                "content": [
                    {
                        "type": "text",
                        "text": (
                            '<untrusted-project-content path="Example.dc.html" etag="123">\n'
                            "&lt;div&gt;&amp;auml;&lt;/div&gt;\n"
                            "</untrusted-project-content>\n\n"
                            "(The body above is HTML-entity-escaped.)"
                        ),
                    }
                ]
            }
        if name == "finalize_plan":
            writes = arguments.get("writes")
            assert isinstance(writes, list)
            return {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(
                            {"plan_token": "auto-plan", "base_etags": {str(path): "123" for path in writes}}
                        ),
                    }
                ]
            }
        if name == "list_files":
            return {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(
                            [
                                {"path": "Example.dc.html", "type": "file", "etag": "123", "size": 42},
                                {"path": "assets", "type": "directory"},
                            ]
                        ),
                    }
                ]
            }
        if name == "write_files":
            files = arguments.get("files")
            assert isinstance(files, list)
            for item in files:
                if isinstance(item, dict) and isinstance(item.get("path"), str) and isinstance(item.get("data"), str):
                    self.written[item["path"]] = item["data"]
            etags = {
                item["path"]: "124" for item in files if isinstance(item, dict) and isinstance(item.get("path"), str)
            }
            return {"content": [{"type": "text", "text": "ok"}], "etags": etags}
        return {"content": [{"type": "text", "text": "ok"}], "etags": {"Example.dc.html": "124"}}


class VerifiedPushStubClient(StubClient):
    def __init__(
        self,
        *,
        include_support: bool = True,
        preview_url: str | None = "https://claude.ai/design/p/project-1",
    ) -> None:
        super().__init__()
        self.remote: dict[str, tuple[str, str]] = {}
        if include_support:
            self.remote["support.js"] = ("support-1", "runtime")
        self.preview_url = preview_url

    def call_tool(self, name: str, arguments: dict[str, object]) -> dict[str, object]:
        self.calls.append((name, arguments))
        if name == "list_files":
            parent = str(arguments.get("path", ""))
            entries = [
                {"path": path, "type": "file", "etag": etag, "size": len(body.encode())}
                for path, (etag, body) in sorted(self.remote.items())
                if (Path(path).parent.as_posix() if "/" in path else "") == parent
            ]
            return {"structuredContent": entries}
        if name == "finalize_plan":
            writes = arguments.get("writes")
            assert isinstance(writes, list)
            return {
                "structuredContent": {
                    "plan_token": "auto-plan",
                    "base_etags": {path: self.remote.get(str(path), ("0", ""))[0] for path in writes},
                }
            }
        if name == "write_files":
            files = arguments.get("files")
            assert isinstance(files, list)
            etags: dict[str, str] = {}
            for item in files:
                assert isinstance(item, dict)
                path = str(item["path"])
                body = str(item["data"])
                etag = "written-1"
                self.remote[path] = (etag, body)
                etags[path] = etag
            return {"structuredContent": {"status": "written", "paths": sorted(etags), "etags": etags}}
        if name == "read_file":
            path = str(arguments["path"])
            etag, body = self.remote[path]
            escaped = body.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            return {
                "content": [
                    {
                        "type": "text",
                        "text": (
                            f'<untrusted-project-content path="{path}" etag="{etag}">\n'
                            f"{escaped}</untrusted-project-content>"
                        ),
                    }
                ]
            }
        if name == "render_preview":
            if self.preview_url is None:
                return {"structuredContent": {}}
            return {
                "structuredContent": {
                    "open_url": self.preview_url,
                    "serve_url": "https://preview.claudeusercontent.com/render",
                }
            }
        raise AssertionError(f"unexpected tool call: {name}")


class VerifiedCopyStubClient(FileStubClient):
    def __init__(self, *, include_support: bool = True) -> None:
        super().__init__()
        self.include_support = include_support

    def call_tool(self, name: str, arguments: dict[str, object]) -> dict[str, object]:
        if name == "list_files":
            self.calls.append((name, arguments))
            entries = [
                {"path": "Example.dc.html", "type": "file", "etag": "copied-1", "size": 20},
            ]
            if self.include_support:
                entries.append({"path": "support.js", "type": "file", "etag": "support-1", "size": 7})
            return {"structuredContent": entries}
        if name == "copy_files":
            self.calls.append((name, arguments))
            return {
                "structuredContent": {
                    "status": "completed",
                    "copied": ["Example.dc.html"],
                    "etags": {"Example.dc.html": "copied-1"},
                }
            }
        if name == "render_preview":
            self.calls.append((name, arguments))
            return {
                "structuredContent": {
                    "open_url": "https://claude.ai/design/p/project-1",
                    "serve_url": "https://preview.claudeusercontent.com/render",
                }
            }
        return super().call_tool(name, arguments)


class VerifiedFolderCopyStubClient(FileStubClient):
    def call_tool(self, name: str, arguments: dict[str, object]) -> dict[str, object]:
        if name == "list_files":
            self.calls.append((name, arguments))
            return {
                "structuredContent": [
                    {
                        "path": "Checkout/Payment.dc.html",
                        "type": "file",
                        "etag": "copied-1",
                        "size": 20,
                    },
                    {"path": "Checkout/support.js", "type": "file", "etag": "support-1", "size": 7},
                ]
            }
        if name == "copy_files":
            self.calls.append((name, arguments))
            return {
                "structuredContent": {
                    "status": "completed",
                    "etags": {
                        "Checkout/Payment.dc.html": "copied-1",
                        "Checkout/support.js": "support-1",
                    },
                }
            }
        if name == "render_preview":
            self.calls.append((name, arguments))
            return {
                "structuredContent": {
                    "open_url": "https://claude.ai/design/p/project-1",
                    "serve_url": "https://preview.claudeusercontent.com/render",
                }
            }
        return super().call_tool(name, arguments)


def test_planned_call_keeps_support_plan_token_internal(capsys: pytest.CaptureFixture[str]) -> None:
    client = FileStubClient()
    args = Namespace(
        design_command="planned-call",
        tool="create_support_js",
        project_id="project-1",
        args='{"path":"Example.dc.html","if_match":"123"}',
        writes=["Example.dc.html"],
        allow_write=True,
        allow_destructive=False,
        json=True,
    )

    assert run_design_command(args, client_factory=lambda: client) == 0
    assert [name for name, _arguments in client.calls] == ["finalize_plan", "create_support_js"]
    assert client.calls[-1][1]["plan_token"] == "auto-plan"
    output = capsys.readouterr().out
    assert "auto-plan" not in output


def test_planned_copy_requires_a_verified_preview_for_copied_dc_files(
    capsys: pytest.CaptureFixture[str],
) -> None:
    client = VerifiedCopyStubClient()
    args = Namespace(
        design_command="planned-call",
        tool="copy_files",
        project_id="project-1",
        args=('{"files":[{"src":"Template.dc.html","dest":"Example.dc.html","if_match":"123"}]}'),
        writes=["Example.dc.html"],
        allow_write=True,
        allow_destructive=True,
        open_browser=False,
        json=True,
    )

    assert run_design_command(args, client_factory=lambda: client) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["verification"] == {
        "verified": True,
        "previews": [
            {
                "path": "Example.dc.html",
                "open_url": "https://claude.ai/design/p/project-1",
                "opened": False,
            }
        ],
    }
    assert [name for name, _arguments in client.calls] == [
        "finalize_plan",
        "copy_files",
        "list_files",
        "render_preview",
    ]


def test_planned_copy_returns_unknown_when_copied_dc_support_is_missing(
    capsys: pytest.CaptureFixture[str],
) -> None:
    client = VerifiedCopyStubClient(include_support=False)
    args = Namespace(
        design_command="planned-call",
        tool="copy_files",
        project_id="project-1",
        args=('{"files":[{"src":"Template.dc.html","dest":"Example.dc.html","if_match":"123"}]}'),
        writes=["Example.dc.html"],
        allow_write=True,
        allow_destructive=True,
        open_browser=False,
        json=True,
    )

    assert run_design_command(args, client_factory=lambda: client) == 2
    output = json.loads(capsys.readouterr().out)
    assert output["mutated"] is True
    assert output["verification"]["verified"] is False
    assert "support.js" in output["verification"]["error"]


def test_planned_folder_copy_verifies_nested_dc_preview(
    capsys: pytest.CaptureFixture[str],
) -> None:
    client = VerifiedFolderCopyStubClient()
    args = Namespace(
        design_command="planned-call",
        tool="copy_files",
        project_id="project-1",
        args=(
            '{"files":[{"src":"Template","dest":"Checkout","leaf_if_match":'
            '{"Checkout/Payment.dc.html":"0","Checkout/support.js":"0"}}]}'
        ),
        writes=["Checkout"],
        allow_write=True,
        allow_destructive=True,
        open_browser=False,
        json=True,
    )

    assert run_design_command(args, client_factory=lambda: client) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["verification"] == {
        "verified": True,
        "previews": [
            {
                "path": "Checkout/Payment.dc.html",
                "open_url": "https://claude.ai/design/p/project-1",
                "opened": False,
            }
        ],
    }


def test_planned_copy_refuses_success_without_copied_file_etags(
    capsys: pytest.CaptureFixture[str],
) -> None:
    class MissingEtagsCopyStub(VerifiedCopyStubClient):
        def call_tool(self, name: str, arguments: dict[str, object]) -> dict[str, object]:
            if name == "copy_files":
                self.calls.append((name, arguments))
                return {"structuredContent": {"status": "completed", "copied": ["Example.dc.html"]}}
            return super().call_tool(name, arguments)

    client = MissingEtagsCopyStub()
    args = Namespace(
        design_command="planned-call",
        tool="copy_files",
        project_id="project-1",
        args=('{"files":[{"src":"Template.dc.html","dest":"Example.dc.html","if_match":"123"}]}'),
        writes=["Example.dc.html"],
        allow_write=True,
        allow_destructive=True,
        open_browser=False,
        json=True,
    )

    assert run_design_command(args, client_factory=lambda: client) == 2
    output = json.loads(capsys.readouterr().out)
    assert output["verification"]["verified"] is False
    assert "etags" in output["verification"]["error"]


def test_planned_copy_rejects_noncanonical_returned_leaf_before_preview(
    capsys: pytest.CaptureFixture[str],
) -> None:
    class UnsafeLeafCopyStub(VerifiedFolderCopyStubClient):
        def call_tool(self, name: str, arguments: dict[str, object]) -> dict[str, object]:
            if name == "copy_files":
                self.calls.append((name, arguments))
                return {
                    "structuredContent": {
                        "status": "completed",
                        "etags": {"Checkout/../Evil.dc.html": "copied-1"},
                    }
                }
            return super().call_tool(name, arguments)

    client = UnsafeLeafCopyStub()
    args = Namespace(
        design_command="planned-call",
        tool="copy_files",
        project_id="project-1",
        args=('{"files":[{"src":"Template","dest":"Checkout","leaf_if_match":{"Checkout/Payment.dc.html":"0"}}]}'),
        writes=["Checkout"],
        allow_write=True,
        allow_destructive=True,
        open_browser=False,
        json=True,
    )

    assert run_design_command(args, client_factory=lambda: client) == 2
    output = json.loads(capsys.readouterr().out)
    assert "verification" not in output
    assert [name for name, _arguments in client.calls] == ["finalize_plan", "copy_files"]


class DeleteStubClient(StubClient):
    def __init__(self, *, etag: str = "delete-etag") -> None:
        super().__init__()
        self.etag = etag

    def call_tool(self, name: str, arguments: dict[str, object]) -> dict[str, object]:
        self.calls.append((name, arguments))
        if name == "read_file":
            path = str(arguments["path"])
            return {
                "content": [
                    {
                        "type": "text",
                        "text": (
                            f'<untrusted-project-content path="{path}" etag="{self.etag}">\n'
                            "&lt;main&gt;recoverable&lt;/main&gt;\n"
                            "</untrusted-project-content>"
                        ),
                    }
                ]
            }
        if name == "finalize_plan":
            return {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps({"plan_token": "internal-delete-plan"}),
                    }
                ]
            }
        if name == "delete_files":
            return {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps({"status": "deleted", "paths": ["Obsolete.dc.html"]}),
                    }
                ]
            }
        if name == "list_files":
            return {"content": [{"type": "text", "text": "[]"}]}
        return super().call_tool(name, arguments)


def test_delete_requires_exact_confirmation_backs_up_and_keeps_plan_internal(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    client = DeleteStubClient()
    args = Namespace(
        design_command="delete",
        project_id="project-1",
        paths=["Obsolete.dc.html"],
        if_matches=["Obsolete.dc.html=delete-etag"],
        confirm_deletes=["Obsolete.dc.html"],
        backup_dir=".open-claude-design/delete-backups",
        allow_write=True,
        json=True,
    )

    assert run_design_command(args, client_factory=lambda: client, workspace_root=tmp_path) == 0

    assert client.write_preflights == 1
    assert [name for name, _arguments in client.calls] == [
        "read_file",
        "finalize_plan",
        "delete_files",
        "list_files",
    ]
    delete_payload = client.calls[2][1]
    assert delete_payload["files"] == [{"path": "Obsolete.dc.html", "if_match": "delete-etag"}]
    assert delete_payload["plan_token"] == "internal-delete-plan"
    output = capsys.readouterr().out
    assert "internal-delete-plan" not in output
    parsed = json.loads(output)
    assert parsed["verification"]["verifiedAbsent"] is True
    backup = Path(parsed["backups"][0])
    assert backup.is_file()
    assert backup.read_text(encoding="utf-8") == "<main>recoverable</main>\n"


def test_delete_refuses_missing_exact_user_authorization(tmp_path: Path) -> None:
    client = DeleteStubClient()
    args = Namespace(
        design_command="delete",
        project_id="project-1",
        paths=["Obsolete.dc.html"],
        if_matches=["Obsolete.dc.html=delete-etag"],
        confirm_deletes=[],
        backup_dir=".open-claude-design/delete-backups",
        allow_write=True,
        json=True,
    )

    with pytest.raises(ClaudeDesignSafetyError, match="exact authorization"):
        run_design_command(args, client_factory=lambda: client, workspace_root=tmp_path)

    assert client.calls == []


def test_delete_refuses_stale_etag_before_plan_or_mutation(tmp_path: Path) -> None:
    client = DeleteStubClient(etag="new-etag")
    args = Namespace(
        design_command="delete",
        project_id="project-1",
        paths=["Obsolete.dc.html"],
        if_matches=["Obsolete.dc.html=old-etag"],
        confirm_deletes=["Obsolete.dc.html"],
        backup_dir=".open-claude-design/delete-backups",
        allow_write=True,
        json=True,
    )

    with pytest.raises(ClaudeDesignSafetyError, match="changed before the delete backup"):
        run_design_command(args, client_factory=lambda: client, workspace_root=tmp_path)

    assert [name for name, _arguments in client.calls] == ["read_file"]


def test_delete_refuses_noncanonical_server_path_during_absence_verification(tmp_path: Path) -> None:
    class NoncanonicalListingStub(DeleteStubClient):
        def call_tool(self, name: str, arguments: dict[str, object]) -> dict[str, object]:
            if name == "delete_files":
                self.calls.append((name, arguments))
                return {"structuredContent": {"status": "deleted", "paths": ["dir/Obsolete.dc.html"]}}
            if name == "list_files":
                self.calls.append((name, arguments))
                return {
                    "structuredContent": [
                        {"path": "dir/./Obsolete.dc.html", "type": "file", "etag": "delete-etag", "size": 1}
                    ]
                }
            return super().call_tool(name, arguments)

    client = NoncanonicalListingStub()
    args = Namespace(
        design_command="delete",
        project_id="project-1",
        paths=["dir/Obsolete.dc.html"],
        if_matches=["dir/Obsolete.dc.html=delete-etag"],
        confirm_deletes=["dir/Obsolete.dc.html"],
        backup_dir=".open-claude-design/delete-backups",
        allow_write=True,
        json=True,
    )

    assert run_design_command(args, client_factory=lambda: client, workspace_root=tmp_path) == 2
    assert [name for name, _arguments in client.calls][-1] == "list_files"


def test_design_pull_writes_decoded_file_without_echoing_content(
    tmp_path: Any,
    capsys: pytest.CaptureFixture[str],
) -> None:
    client = FileStubClient()
    output = tmp_path / "Example.dc.html"
    args = Namespace(
        design_command="pull",
        project_id="project-1",
        remote_path="Example.dc.html",
        output=str(output),
        force=False,
        json=True,
    )

    assert run_design_command(args, client_factory=lambda: client, workspace_root=tmp_path) == 0
    assert output.read_text(encoding="utf-8") == "<div>&auml;</div>\n"
    assert client.calls == [("read_file", {"project_id": "project-1", "path": "Example.dc.html"})]
    rendered = capsys.readouterr().out
    assert "<div>" not in rendered
    assert json.loads(rendered)["etag"] == "123"


def test_design_pull_refuses_to_overwrite_without_force(tmp_path: Any) -> None:
    output = tmp_path / "existing.dc.html"
    output.write_text("user work", encoding="utf-8")
    args = Namespace(
        design_command="pull",
        project_id="project-1",
        remote_path="Example.dc.html",
        output=str(output),
        force=False,
        json=True,
    )

    with pytest.raises(ClaudeDesignSafetyError, match="--force"):
        run_design_command(args, client_factory=FileStubClient, workspace_root=tmp_path)

    assert output.read_text(encoding="utf-8") == "user work"


def test_design_pull_rejects_external_output_before_remote_read(tmp_path: Any) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    external = tmp_path / "outside.dc.html"
    client = FileStubClient()
    args = Namespace(
        design_command="pull",
        project_id="project-1",
        remote_path="Example.dc.html",
        output=str(external),
        force=True,
        external_local_paths=[],
        json=True,
    )

    with pytest.raises(ClaudeDesignSafetyError, match="outside the current workspace"):
        run_design_command(args, client_factory=lambda: client, workspace_root=workspace)

    assert client.calls == []
    assert not external.exists()


def test_design_pull_allows_explicit_external_output_without_symlinks(tmp_path: Any) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    external = tmp_path / "outside.dc.html"
    client = FileStubClient()
    args = Namespace(
        design_command="pull",
        project_id="project-1",
        remote_path="Example.dc.html",
        output=str(external),
        force=False,
        external_local_paths=[str(external)],
        json=True,
    )

    assert run_design_command(args, client_factory=lambda: client, workspace_root=workspace) == 0
    assert external.read_text(encoding="utf-8") == "<div>&auml;</div>\n"


@pytest.mark.parametrize("target_exists", [True, False])
def test_design_pull_rejects_final_symlink_without_touching_external_target(
    tmp_path: Any,
    target_exists: bool,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    external = tmp_path / "outside.dc.html"
    if target_exists:
        external.write_text("keep me", encoding="utf-8")
    output = workspace / "Example.dc.html"
    output.symlink_to(external)
    client = FileStubClient()
    args = Namespace(
        design_command="pull",
        project_id="project-1",
        remote_path="Example.dc.html",
        output=str(output),
        force=True,
        external_local_paths=[],
        json=True,
    )

    with pytest.raises(ClaudeDesignSafetyError, match="symlink"):
        run_design_command(args, client_factory=lambda: client, workspace_root=workspace)

    assert client.calls == []
    if target_exists:
        assert external.read_text(encoding="utf-8") == "keep me"
    else:
        assert not external.exists()


def test_design_pull_rejects_parent_symlink_without_creating_external_file(tmp_path: Any) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    external_dir = tmp_path / "outside"
    external_dir.mkdir()
    linked_dir = workspace / "linked"
    linked_dir.symlink_to(external_dir, target_is_directory=True)
    client = FileStubClient()
    args = Namespace(
        design_command="pull",
        project_id="project-1",
        remote_path="Example.dc.html",
        output=str(linked_dir / "Example.dc.html"),
        force=False,
        external_local_paths=[],
        json=True,
    )

    with pytest.raises(ClaudeDesignSafetyError, match="symlink"):
        run_design_command(args, client_factory=lambda: client, workspace_root=workspace)

    assert client.calls == []
    assert not (external_dir / "Example.dc.html").exists()


def test_design_pull_resists_parent_symlink_swap_after_validation(
    tmp_path: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "workspace"
    parent = workspace / "target"
    parent.mkdir(parents=True)
    parked = workspace / "parked"
    external_dir = tmp_path / "outside"
    external_dir.mkdir()
    output = parent / "Example.dc.html"
    client = FileStubClient()
    original = claude_design._resolve_local_path
    calls = 0

    def swap_after_validation(*args: Any, **kwargs: Any) -> Any:
        nonlocal calls
        resolved = original(*args, **kwargs)
        calls += 1
        if calls == 2:
            parent.rename(parked)
            parent.symlink_to(external_dir, target_is_directory=True)
        return resolved

    monkeypatch.setattr(claude_design, "_resolve_local_path", swap_after_validation)
    args = Namespace(
        design_command="pull",
        project_id="project-1",
        remote_path="Example.dc.html",
        output=str(output),
        force=False,
        external_local_paths=[],
        json=True,
    )

    with pytest.raises(ClaudeDesignSafetyError, match="symlink"):
        run_design_command(args, client_factory=lambda: client, workspace_root=workspace)

    assert [name for name, _arguments in client.calls] == ["read_file"]
    assert not (external_dir / "Example.dc.html").exists()


def test_design_push_reads_local_file_inside_process_and_requires_etag_and_plan(
    tmp_path: Any,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "Example.txt"
    source.write_text("<div>local bytes</div>\n", encoding="utf-8")
    client = FileStubClient()
    args = Namespace(
        design_command="push",
        project_id="project-1",
        files=[f"Example.txt={source}"],
        if_matches=["Example.txt=123"],
        plan_token="-",
        allow_write=True,
        json=True,
    )
    monkeypatch.setattr(sys, "stdin", io.StringIO("signed-plan\n"))

    assert run_design_command(args, client_factory=lambda: client, workspace_root=tmp_path) == 0
    assert client.calls[0] == (
        "write_files",
        {
            "project_id": "project-1",
            "plan_token": "signed-plan",
            "files": [
                {
                    "path": "Example.txt",
                    "data": "<div>local bytes</div>\n",
                    "if_match": "123",
                }
            ],
        },
    )
    assert client.calls[1] == ("read_file", {"project_id": "project-1", "path": "Example.txt"})
    assert "local bytes" not in capsys.readouterr().out


def test_design_push_refuses_dc_file_without_same_directory_support_before_write(tmp_path: Any) -> None:
    source = tmp_path / "Example.dc.html"
    source.write_text("<x-dc>design</x-dc>\n", encoding="utf-8")
    client = VerifiedPushStubClient(include_support=False)
    args = Namespace(
        design_command="push",
        project_id="project-1",
        files=[f"Example.dc.html={source}"],
        if_matches=["Example.dc.html=0"],
        plan_token=None,
        allow_write=True,
        open_browser=False,
        json=True,
    )

    with pytest.raises(ClaudeDesignSafetyError, match="support.js"):
        run_design_command(args, client_factory=lambda: client, workspace_root=tmp_path)

    assert [name for name, _arguments in client.calls] == ["finalize_plan", "list_files"]


def test_design_push_reads_back_and_renders_every_dc_file(
    tmp_path: Any,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = tmp_path / "Example.dc.html"
    source.write_text("<x-dc>design</x-dc>\n", encoding="utf-8")
    client = VerifiedPushStubClient()
    args = Namespace(
        design_command="push",
        project_id="project-1",
        files=[f"Example.dc.html={source}"],
        if_matches=["Example.dc.html=0"],
        plan_token=None,
        allow_write=True,
        open_browser=False,
        json=True,
    )

    assert run_design_command(args, client_factory=lambda: client, workspace_root=tmp_path) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["verification"] == {
        "verified": True,
        "files": [{"path": "Example.dc.html", "etag": "written-1", "bytes": 20}],
        "previews": [
            {
                "path": "Example.dc.html",
                "open_url": "https://claude.ai/design/p/project-1",
                "opened": False,
            }
        ],
    }
    assert [name for name, _arguments in client.calls] == [
        "finalize_plan",
        "list_files",
        "write_files",
        "read_file",
        "render_preview",
    ]


def test_design_push_returns_unknown_when_preview_cannot_be_created(
    tmp_path: Any,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = tmp_path / "Example.dc.html"
    source.write_text("<x-dc>design</x-dc>\n", encoding="utf-8")
    client = VerifiedPushStubClient(preview_url=None)
    args = Namespace(
        design_command="push",
        project_id="project-1",
        files=[f"Example.dc.html={source}"],
        if_matches=["Example.dc.html=0"],
        plan_token=None,
        allow_write=True,
        open_browser=False,
        json=True,
    )

    assert run_design_command(args, client_factory=lambda: client, workspace_root=tmp_path) == 2
    output = json.loads(capsys.readouterr().out)
    assert output["mutated"] is True
    assert output["verification"]["verified"] is False
    assert "durable preview" in output["verification"]["error"]


def test_design_push_open_uses_short_lived_preview_but_returns_only_durable_url(
    tmp_path: Any,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "Example.dc.html"
    source.write_text("<x-dc>design</x-dc>\n", encoding="utf-8")
    client = VerifiedPushStubClient()
    opened: list[str] = []
    monkeypatch.setattr(claude_design, "_open_preview_url", opened.append)
    args = Namespace(
        design_command="push",
        project_id="project-1",
        files=[f"Example.dc.html={source}"],
        if_matches=["Example.dc.html=0"],
        plan_token=None,
        allow_write=True,
        open_browser=True,
        json=True,
    )

    assert run_design_command(args, client_factory=lambda: client, workspace_root=tmp_path) == 0
    raw = capsys.readouterr().out
    output = json.loads(raw)
    assert opened == ["https://preview.claudeusercontent.com/render"]
    assert output["verification"]["previews"][0] == {
        "path": "Example.dc.html",
        "open_url": "https://claude.ai/design/p/project-1",
        "opened": True,
    }
    assert "claudeusercontent.com" not in raw


def test_design_push_browser_failure_keeps_durable_preview_and_returns_unknown(
    tmp_path: Any,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "Example.dc.html"
    source.write_text("<x-dc>design</x-dc>\n", encoding="utf-8")
    client = VerifiedPushStubClient()

    def fail_open(_url: str) -> None:
        raise ClaudeDesignSafetyError("synthetic browser open failure")

    monkeypatch.setattr(claude_design, "_open_preview_url", fail_open)
    args = Namespace(
        design_command="push",
        project_id="project-1",
        files=[f"Example.dc.html={source}"],
        if_matches=["Example.dc.html=0"],
        plan_token=None,
        allow_write=True,
        open_browser=True,
        json=True,
    )

    assert run_design_command(args, client_factory=lambda: client, workspace_root=tmp_path) == 2
    output = json.loads(capsys.readouterr().out)
    assert output["verification"]["verified"] is False
    assert output["verification"]["previews"] == [
        {
            "path": "Example.dc.html",
            "open_url": "https://claude.ai/design/p/project-1",
            "opened": False,
        }
    ]
    assert "browser open failure" in output["verification"]["error"]


def test_design_push_refuses_missing_write_authority(tmp_path: Any) -> None:
    source = tmp_path / "Example.dc.html"
    source.write_text("content", encoding="utf-8")
    args = Namespace(
        design_command="push",
        project_id="project-1",
        files=[f"Example.dc.html={source}"],
        if_matches=["Example.dc.html=123"],
        plan_token="signed-plan",
        allow_write=False,
        json=True,
    )

    with pytest.raises(ClaudeDesignSafetyError, match="--allow-write"):
        run_design_command(args, client_factory=FileStubClient, workspace_root=tmp_path)


def test_design_push_rejects_external_source_before_plan_or_write(tmp_path: Any) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    external = tmp_path / "secret.txt"
    external.write_text("do not upload", encoding="utf-8")
    client = FileStubClient()
    args = Namespace(
        design_command="push",
        project_id="project-1",
        files=[f"Example.dc.html={external}"],
        if_matches=["Example.dc.html=123"],
        plan_token=None,
        allow_write=True,
        external_local_paths=[],
        json=True,
    )

    with pytest.raises(ClaudeDesignSafetyError, match="outside the current workspace"):
        run_design_command(args, client_factory=lambda: client, workspace_root=workspace)

    assert client.calls == []


def test_design_push_rejects_external_source_symlink_before_plan_or_write(tmp_path: Any) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    external = tmp_path / "secret.txt"
    external.write_text("do not upload", encoding="utf-8")
    source = workspace / "Example.dc.html"
    source.symlink_to(external)
    client = FileStubClient()
    args = Namespace(
        design_command="push",
        project_id="project-1",
        files=[f"Example.dc.html={source}"],
        if_matches=["Example.dc.html=123"],
        plan_token=None,
        allow_write=True,
        external_local_paths=[],
        json=True,
    )

    with pytest.raises(ClaudeDesignSafetyError, match="symlink"):
        run_design_command(args, client_factory=lambda: client, workspace_root=workspace)

    assert client.calls == []


def test_design_push_resists_source_symlink_swap_after_validation(
    tmp_path: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    source = workspace / "Example.dc.html"
    source.write_text("safe", encoding="utf-8")
    external = tmp_path / "secret.txt"
    external.write_text("SECRET", encoding="utf-8")
    original = claude_design._resolve_local_path
    swapped = False

    def swap_after_validation(*args: Any, **kwargs: Any) -> Any:
        nonlocal swapped
        resolved = original(*args, **kwargs)
        if kwargs.get("require_file") is True and not swapped:
            source.unlink()
            source.symlink_to(external)
            swapped = True
        return resolved

    monkeypatch.setattr(claude_design, "_resolve_local_path", swap_after_validation)
    monkeypatch.setattr(sys, "stdin", io.StringIO("signed-plan\n"))
    client = FileStubClient()
    args = Namespace(
        design_command="push",
        project_id="project-1",
        files=[f"Example.dc.html={source}"],
        if_matches=["Example.dc.html=123"],
        plan_token="-",
        allow_write=True,
        external_local_paths=[],
        json=True,
    )

    with pytest.raises(ClaudeDesignSafetyError, match="symlink"):
        run_design_command(args, client_factory=lambda: client, workspace_root=workspace)

    assert client.calls == []


def test_design_push_allows_explicit_external_source_without_symlinks(
    tmp_path: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    external = tmp_path / "Example=external.txt"
    external.write_text("authorized import", encoding="utf-8")
    client = FileStubClient()
    args = Namespace(
        design_command="push",
        project_id="project-1",
        files=[f"Example.txt={external}"],
        if_matches=["Example.txt=123"],
        plan_token="-",
        allow_write=True,
        external_local_paths=[str(external)],
        json=True,
    )
    monkeypatch.setattr(sys, "stdin", io.StringIO("signed-plan\n"))

    assert run_design_command(args, client_factory=lambda: client, workspace_root=workspace) == 0
    assert client.calls[0][1]["files"][0]["data"] == "authorized import"


def test_design_push_external_authorization_is_exact_per_operand(
    tmp_path: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    authorized = tmp_path / "authorized.dc.html"
    unauthorized = tmp_path / "unauthorized.dc.html"
    authorized.write_text("allowed", encoding="utf-8")
    unauthorized.write_text("blocked", encoding="utf-8")
    monkeypatch.setattr(sys, "stdin", io.StringIO("signed-plan\n"))
    client = FileStubClient()
    args = Namespace(
        design_command="push",
        project_id="project-1",
        files=[f"Example.dc.html={authorized}", f"Other.dc.html={unauthorized}"],
        if_matches=["Example.dc.html=123", "Other.dc.html=456"],
        plan_token="-",
        allow_write=True,
        external_local_paths=[str(authorized)],
        json=True,
    )

    with pytest.raises(ClaudeDesignSafetyError, match="outside the current workspace"):
        run_design_command(args, client_factory=lambda: client, workspace_root=workspace)

    assert client.calls == []


def test_design_push_allows_parent_segments_that_stay_inside_workspace(
    tmp_path: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "workspace"
    nested = workspace / "nested"
    designs = workspace / "designs"
    nested.mkdir(parents=True)
    designs.mkdir()
    source = designs / "Example.txt"
    source.write_text("inside workspace", encoding="utf-8")
    monkeypatch.chdir(nested)
    monkeypatch.setattr(sys, "stdin", io.StringIO("signed-plan\n"))
    client = FileStubClient()
    args = Namespace(
        design_command="push",
        project_id="project-1",
        files=["Example.txt=../designs/Example.txt"],
        if_matches=["Example.txt=123"],
        plan_token="-",
        allow_write=True,
        external_local_paths=[],
        json=True,
    )

    assert run_design_command(args, client_factory=lambda: client, workspace_root=workspace) == 0
    assert client.calls[0][1]["files"][0]["data"] == "inside workspace"


def test_design_push_rejects_literal_plan_token_before_local_or_remote_io(
    tmp_path: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "Example.dc.html"
    source.write_text("content", encoding="utf-8")
    client = FileStubClient()
    secret = "secret-plan-token"
    args = Namespace(
        design_command="push",
        project_id="project-1",
        files=[f"Example.dc.html={source}"],
        if_matches=["Example.dc.html=123"],
        plan_token=secret,
        allow_write=True,
        external_local_paths=[],
        json=True,
    )

    root_resolver = MagicMock(return_value=tmp_path)
    client_factory = MagicMock(return_value=client)
    monkeypatch.setattr(claude_design, "_design_workspace_root", root_resolver)

    with pytest.raises(ClaudeDesignSafetyError, match="--plan-token -") as captured:
        run_design_command(args, client_factory=client_factory, workspace_root=tmp_path)

    assert secret not in str(captured.value)
    assert client.calls == []
    root_resolver.assert_not_called()
    client_factory.assert_not_called()


def test_design_push_mints_exact_path_plan_and_checks_fresh_etags(
    tmp_path: Any,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = tmp_path / "Example.txt"
    source.write_text("fresh content", encoding="utf-8")
    client = FileStubClient()
    args = Namespace(
        design_command="push",
        project_id="project-1",
        files=[f"Example.txt={source}"],
        if_matches=["Example.txt=123"],
        plan_token=None,
        allow_write=True,
        json=True,
    )

    assert run_design_command(args, client_factory=lambda: client, workspace_root=tmp_path) == 0
    assert client.calls[0] == (
        "finalize_plan",
        {"project_id": "project-1", "scope": "paths", "writes": ["Example.txt"], "deletes": []},
    )
    assert client.calls[1][0] == "write_files"
    assert client.calls[1][1]["plan_token"] == "auto-plan"
    assert "fresh content" not in capsys.readouterr().out


def test_generic_render_preview_is_disabled_in_favor_of_safe_preview() -> None:
    client = StubClient()
    args = Namespace(
        design_command="call",
        tool="render_preview",
        args='{"project_id":"p","path":"Example.dc.html"}',
        allow_write=False,
        allow_guarded=True,
        json=True,
    )

    with pytest.raises(ClaudeDesignSafetyError, match="Generic render_preview calls are disabled"):
        run_design_command(args, client_factory=lambda: client)

    assert client.calls == []


def test_non_mutating_guard_does_not_authorize_write_files() -> None:
    args = Namespace(
        design_command="call",
        tool="write_files",
        args='{"project_id":"p","files":[]}',
        allow_write=False,
        allow_guarded=True,
        json=True,
    )

    with pytest.raises(ClaudeDesignSafetyError, match="Generic write_files calls are disabled"):
        run_design_command(args, client_factory=StubClient)


def test_design_files_tsv_is_normalized_without_content(capsys: pytest.CaptureFixture[str]) -> None:
    client = FileStubClient()
    args = Namespace(
        design_command="files",
        project_id="project-1",
        path="",
        depth=-1,
        tsv=True,
        json=False,
    )

    assert run_design_command(args, client_factory=lambda: client) == 0
    assert capsys.readouterr().out == "Example.dc.html\t123\t42\n"
    assert client.calls == [("list_files", {"project_id": "project-1", "path": "", "depth": -1})]


class ConflictFileStubClient(FileStubClient):
    def call_tool(self, name: str, arguments: dict[str, object]) -> dict[str, object]:
        if name == "finalize_plan":
            self.calls.append((name, arguments))
            return {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps({"plan_token": "stale-plan", "base_etags": {"Example.dc.html": "changed"}}),
                    }
                ]
            }
        return super().call_tool(name, arguments)


def test_design_push_refuses_concurrent_change_after_plan(tmp_path: Any) -> None:
    source = tmp_path / "Example.dc.html"
    source.write_text("content", encoding="utf-8")
    client = ConflictFileStubClient()
    args = Namespace(
        design_command="push",
        project_id="project-1",
        files=[f"Example.dc.html={source}"],
        if_matches=["Example.dc.html=123"],
        plan_token=None,
        allow_write=True,
        json=True,
    )

    with pytest.raises(ClaudeDesignSafetyError, match="changed after"):
        run_design_command(args, client_factory=lambda: client, workspace_root=tmp_path)

    assert [name for name, _arguments in client.calls] == ["finalize_plan"]


def test_design_push_refuses_file_over_inline_cap(tmp_path: Any) -> None:
    source = tmp_path / "large.dc.html"
    source.write_bytes(b"x" * (256 * 1024 + 1))
    client = FileStubClient()
    args = Namespace(
        design_command="push",
        project_id="project-1",
        files=[f"large.dc.html={source}"],
        if_matches=["large.dc.html=123"],
        plan_token=None,
        allow_write=True,
        json=True,
    )

    with pytest.raises(ClaudeDesignSafetyError, match="256 KiB"):
        run_design_command(args, client_factory=lambda: client, workspace_root=tmp_path)

    assert client.calls == []


def test_design_push_base64_encodes_binary_inside_process(
    tmp_path: Any,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "asset.bin"
    source.write_bytes(b"\xff\x00")
    client = FileStubClient()
    args = Namespace(
        design_command="push",
        project_id="project-1",
        files=[f"asset.bin={source}"],
        if_matches=["asset.bin=0"],
        plan_token="-",
        allow_write=True,
        json=True,
    )
    monkeypatch.setattr(sys, "stdin", io.StringIO("plan\n"))

    assert run_design_command(args, client_factory=lambda: client, workspace_root=tmp_path) == 0
    pushed = client.calls[0][1]["files"][0]
    assert pushed == {"path": "asset.bin", "if_match": "0", "data": "/wA=", "encoding": "base64"}
    assert "/wA=" not in capsys.readouterr().out


class UnsafeTsvStubClient(FileStubClient):
    def __init__(self, unsafe_path: str = "bad\tpath") -> None:
        super().__init__()
        self.unsafe_path = unsafe_path

    def call_tool(self, name: str, arguments: dict[str, object]) -> dict[str, object]:
        if name == "list_files":
            self.calls.append((name, arguments))
            return {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps([{"path": self.unsafe_path, "type": "file", "etag": "1", "size": 2}]),
                    }
                ]
            }
        return super().call_tool(name, arguments)


@pytest.mark.parametrize("unsafe_path", ["bad\tpath", "bad\x1b]52;c;dGVzdA==\x07", "bad\u202epath"])
def test_design_files_tsv_rejects_control_characters(unsafe_path: str) -> None:
    args = Namespace(
        design_command="files",
        project_id="project-1",
        path="",
        depth=-1,
        tsv=True,
        json=False,
    )

    with pytest.raises(ClaudeDesignProtocolError, match="unsafe for TSV"):
        run_design_command(args, client_factory=lambda: UnsafeTsvStubClient(unsafe_path))


@pytest.mark.parametrize("remote_path", [".", "dir/./file.dc.html", "dir//file.dc.html", "dir/file.dc.html/"])
def test_remote_paths_must_be_canonical(remote_path: str) -> None:
    with pytest.raises(ValueError, match="canonical"):
        claude_design._validate_remote_path(remote_path)


@pytest.mark.parametrize(
    ("argv", "expected"),
    [
        (["status", "--json"], {"design_command": "status", "json": True}),
        (
            ["authoring-context", "project-1", "--design-system", "ds-1", "--skill", "hifi-design", "--refresh"],
            {"project_id": "project-1", "design_system_id": "ds-1", "skill": "hifi-design", "refresh": True},
        ),
        (["tools", "--json"], {"design_command": "tools"}),
        (["describe", "read_file", "--json"], {"tool": "read_file"}),
        (
            ["call", "list_projects", "--args", "{}", "--allow-write", "--allow-destructive", "--allow-guarded"],
            {
                "tool": "list_projects",
                "args": "{}",
                "allow_write": True,
                "allow_destructive": True,
                "allow_guarded": True,
            },
        ),
        (
            [
                "planned-call",
                "copy_files",
                "project-1",
                "--args",
                "{}",
                "--write",
                "a.dc.html",
                "--allow-write",
                "--open",
            ],
            {
                "tool": "copy_files",
                "project_id": "project-1",
                "writes": ["a.dc.html"],
                "allow_write": True,
                "open_browser": True,
            },
        ),
        (
            ["preview", "project-1", "screen.dc.html", "--open"],
            {"project_id": "project-1", "remote_path": "screen.dc.html", "open_browser": True},
        ),
        (
            ["files", "project-1", "--path", "assets", "--depth", "-1", "--tsv"],
            {"project_id": "project-1", "path": "assets", "depth": -1, "tsv": True, "json": False},
        ),
        (
            ["pull", "project-1", "screen.dc.html", "--output", "local.html", "--force"],
            {"remote_path": "screen.dc.html", "output": "local.html", "force": True, "external_local_paths": []},
        ),
        (
            [
                "push",
                "project-1",
                "--file",
                "a=./a",
                "--if-match",
                "a=123",
                "--plan-token",
                "-",
                "--allow-write",
                "--open",
            ],
            {
                "files": ["a=./a"],
                "if_matches": ["a=123"],
                "plan_token": "-",
                "allow_write": True,
                "open_browser": True,
            },
        ),
        (
            ["sync", "apply", "0123456789abcdef0123456789abcdef", "--allow-write", "--open"],
            {
                "sync_command": "apply",
                "review_id": "0123456789abcdef0123456789abcdef",
                "allow_write": True,
                "open_browser": True,
            },
        ),
        (
            [
                "delete",
                "project-1",
                "--path",
                "a.dc.html",
                "--if-match",
                "a.dc.html=123",
                "--confirm-delete",
                "a.dc.html",
                "--allow-write",
            ],
            {
                "paths": ["a.dc.html"],
                "if_matches": ["a.dc.html=123"],
                "confirm_deletes": ["a.dc.html"],
                "allow_write": True,
            },
        ),
    ],
)
def test_build_parser_accepts_every_documented_bridge_invocation(
    argv: list[str],
    expected: dict[str, Any],
) -> None:
    """The documented CLI surface (SKILL.md + README) must keep parsing."""
    parsed = claude_design.build_parser().parse_args(argv)
    for attribute, value in expected.items():
        assert getattr(parsed, attribute) == value


def test_push_plan_token_only_accepts_the_stdin_marker() -> None:
    parser = claude_design.build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["push", "project-1", "--file", "a=./a", "--if-match", "a=1", "--plan-token", "tok"])
