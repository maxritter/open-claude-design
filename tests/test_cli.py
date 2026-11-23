"""Public CLI parsing and output contracts."""

from __future__ import annotations

import json

import pytest

import open_claude_artifacts.cli as cli
from open_claude_artifacts.cli import main

pytestmark = pytest.mark.unit


def test_skills_reports_all_skills(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["skills", "--json"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["package"] == "open-claude-artifacts"
    assert payload["skills"] == [
        "open-claude-design-quality",
        "open-claude-ui-design",
        "open-claude-design-system",
        "open-claude-ui-review",
        "open-claude-artifacts",
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


def test_login_calls_artifact_oauth(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def fake_login(**kwargs: object) -> dict[str, object]:
        captured.update(kwargs)
        return {"authenticated": True}

    monkeypatch.setattr(cli, "login_artifacts", fake_login)

    assert main(["login", "--manual", "--timeout=42"]) == 0
    assert captured["manual"] is True
    assert captured["timeout_seconds"] == 42


def test_automatic_login_fails_cleanly_in_headless_runtime(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(cli, "automatic_browser_login_available", lambda: False)
    monkeypatch.setattr(cli, "login_artifacts", lambda **_kwargs: pytest.fail("headless login must not start OAuth"))

    assert main(["login"]) == 1

    error = capsys.readouterr().err
    assert "login --manual" in error
    assert "interactive terminal" in error


def test_logout_removes_stored_credential(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(cli, "delete_artifact_credential", lambda: True)

    assert main(["logout", "--yes"]) == 0
    assert capsys.readouterr().out == "Removed Claude Artifacts credential.\n"


def test_artifact_commands_are_top_level(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[str] = []

    def fake_run(args: object, **_kwargs: object) -> int:
        captured.append(getattr(args, "command", ""))
        return 0

    monkeypatch.setattr(cli, "run_artifact_command", fake_run)

    assert main(["list", "--json"]) == 0
    assert main(["render", "abc", "--slide", "1", "--slide", "cover", "--json"]) == 0
    assert main(["sync", "status", "0123456789abcdef0123456789abcdef", "--json"]) == 0
    assert main(["authoring-context", "abc", "--design-system=none", "--json"]) == 0
    assert captured == ["list", "render", "sync", "authoring-context"]


@pytest.mark.parametrize("json_mode", [False, True])
def test_cli_output_escapes_terminal_format_controls(
    json_mode: bool,
    capsys: pytest.CaptureFixture[str],
) -> None:
    cli._print({"message": "safe‮reversed"}, json_mode=json_mode)

    output = capsys.readouterr().out
    assert "‮" not in output
    assert "\\u202e" in output
