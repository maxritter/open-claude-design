"""Public CLI parsing and output contracts."""

from __future__ import annotations

import json

import pytest

import open_claude_design.cli as cli
from open_claude_design.cli import main

pytestmark = pytest.mark.unit


def test_list_reports_all_skills(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["list", "--json"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["skills"] == [
        "open-claude-design-quality",
        "open-claude-ui-design",
        "open-claude-design-system",
        "open-claude-ui-review",
        "open-claude-design",
    ]
    assert payload["skills_cli"].startswith("skills@")
    assert "cursor" in payload["featured_agents"]


def test_invalid_agent_id_is_rejected_without_writes(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as error:
        main(["install", "--agents=bad agent", "--yes"])

    assert error.value.code == 2
    assert "invalid agent" in capsys.readouterr().err


def test_install_delegates_all_agents_to_the_portable_backend(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    captured: dict[str, object] = {}

    def fake_action(action: str, agents: tuple[str, ...], scope: str, **kwargs: object) -> dict[str, object]:
        captured.update(action=action, agents=agents, scope=scope, kwargs=kwargs)
        return {"executed": False}

    monkeypatch.setattr(cli, "run_skills_action", fake_action)

    assert main(["install", "--all-agents", "--scope=global", "--yes", "--dry-run", "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == {"executed": False}
    assert captured["agents"] == ("*",)
    assert captured["scope"] == "global"


def test_uninstall_is_all_agent_within_the_selected_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_action(action: str, agents: tuple[str, ...], scope: str, **kwargs: object) -> dict[str, object]:
        captured.update(action=action, agents=agents, scope=scope, kwargs=kwargs)
        return {"executed": True}

    monkeypatch.setattr(cli, "run_skills_action", fake_action)

    assert main(["uninstall", "--scope=project", "--yes", "--json"]) == 0
    assert captured["agents"] == ()
    assert captured["scope"] == "project"


def test_login_is_standalone_and_does_not_route_through_bridge(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def fake_login(**kwargs: object) -> dict[str, object]:
        captured.update(kwargs)
        return {"authenticated": True}

    monkeypatch.setattr(cli, "login_design", fake_login)
    monkeypatch.setattr(cli.bridge, "main", lambda _arguments: pytest.fail("login must not use the MCP command parser"))

    assert main(["login", "--manual", "--timeout=42"]) == 0
    assert captured["manual"] is True
    assert captured["timeout_seconds"] == 42


def test_automatic_login_fails_cleanly_in_headless_runtime(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(cli, "automatic_browser_login_available", lambda: False)
    monkeypatch.setattr(cli, "login_design", lambda **_kwargs: pytest.fail("headless login must not start OAuth"))

    assert main(["login"]) == 1

    error = capsys.readouterr().err
    assert "login --manual" in error
    assert "interactive terminal" in error
    assert "coding-agent chat" in error


def test_logout_removes_only_standalone_credential(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(cli, "delete_standalone_credential", lambda: True)

    assert main(["logout", "--yes"]) == 0
    assert capsys.readouterr().out == "Open Claude Design credential removed.\n"


def test_bridge_commands_are_flat_top_level_commands(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[str] = []

    def fake_bridge(arguments: list[str]) -> int:
        captured.extend(arguments)
        return 0

    monkeypatch.setattr(cli.bridge, "main", fake_bridge)

    assert main(["status", "--json"]) == 0
    assert captured == ["status", "--json"]


def test_sync_lifecycle_is_a_flat_bridge_command(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[str] = []

    def fake_bridge(arguments: list[str]) -> int:
        captured.extend(arguments)
        return 0

    monkeypatch.setattr(cli.bridge, "main", fake_bridge)

    assert main(["sync", "status", "0123456789abcdef0123456789abcdef", "--json"]) == 0
    assert captured == ["sync", "status", "0123456789abcdef0123456789abcdef", "--json"]


def test_authoring_context_is_a_flat_bridge_command(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[str] = []

    def fake_bridge(arguments: list[str]) -> int:
        captured.extend(arguments)
        return 0

    monkeypatch.setattr(cli.bridge, "main", fake_bridge)

    arguments = [
        "authoring-context",
        "project-1",
        "--design-system=system-1",
        "--skill=hifi-design",
        "--json",
    ]
    assert main(arguments) == 0
    assert captured == arguments


@pytest.mark.parametrize("json_mode", [False, True])
def test_cli_output_escapes_terminal_format_controls(
    json_mode: bool,
    capsys: pytest.CaptureFixture[str],
) -> None:
    cli._print({"message": "safe\u202ereversed"}, json_mode=json_mode)

    output = capsys.readouterr().out
    assert "\u202e" not in output
    assert "\\u202e" in output
