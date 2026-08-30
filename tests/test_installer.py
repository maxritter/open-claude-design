"""Cross-agent skills CLI adapter contracts."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from open_claude_design.config import SKILL_NAMES, SKILLS_CLI_VERSION
from open_claude_design.installer import (
    InstallError,
    SkillsRuntime,
    _export_runtime_skills,
    doctor,
    resolve_skills_runtime,
    run_skills_action,
)

pytestmark = pytest.mark.unit


def _runtime() -> SkillsRuntime:
    return SkillsRuntime(
        node=Path("/runtime/bin/node"),
        npx=Path("/runtime/bin/npx"),
        source="managed",
        version=(22, 20, 0),
    )


def _installed_payload(tmp_path: Path) -> str:
    exported = _export_runtime_skills(tmp_path / "installed")
    return json.dumps(
        [
            {
                "name": skill,
                "path": str(exported / "skills" / skill),
                "scope": "global",
                "agents": ["Codex"],
            }
            for skill in SKILL_NAMES
        ]
    )


def test_runtime_skill_export_contains_all_skills_without_benchmark_payload(tmp_path: Path) -> None:
    exported = _export_runtime_skills(tmp_path / "source")

    for skill in SKILL_NAMES:
        assert (exported / "skills" / skill / "SKILL.md").is_file()
        assert not (exported / "skills" / skill / "tests").exists()


@patch("open_claude_design.installer.resolve_skills_runtime", return_value=_runtime())
@patch("open_claude_design.installer.subprocess.run")
def test_install_uses_one_pinned_skills_cli_for_every_agent(
    run: MagicMock,
    _resolve: MagicMock,
    tmp_path: Path,
) -> None:
    def execute(command: list[str], **kwargs: object) -> SimpleNamespace:
        if command[3] == "list":
            return SimpleNamespace(returncode=0, stdout="[]", stderr="")
        source = Path(command[4])
        assert source.is_dir()
        assert (source / "skills" / "open-claude-design-quality" / "SKILL.md").is_file()
        assert not list(source.rglob("tests"))
        assert kwargs["shell"] is False
        assert str(kwargs["env"]["PATH"]).split(":", 1)[0] == "/runtime/bin"
        return SimpleNamespace(returncode=0, stdout="installed", stderr="")

    run.side_effect = execute

    result = run_skills_action(
        "install",
        ("claude-code", "codex", "cursor", "pi"),
        "global",
        project_root=tmp_path,
        yes=True,
        capture_output=True,
    )

    command = run.call_args_list[-1].args[0]
    assert command[:4] == [
        "/runtime/bin/npx",
        "--yes",
        f"skills@{SKILLS_CLI_VERSION}",
        "add",
    ]
    assert command.count("--agent") == 4
    assert "--global" in command
    assert "--copy" in command
    assert result["skills"] == list(SKILL_NAMES)


@patch("open_claude_design.installer.resolve_skills_runtime", return_value=_runtime())
@patch("open_claude_design.installer.subprocess.run")
def test_install_is_a_noop_when_every_runtime_file_is_already_current(
    run: MagicMock,
    _resolve: MagicMock,
    tmp_path: Path,
) -> None:
    run.return_value = SimpleNamespace(returncode=0, stdout=_installed_payload(tmp_path), stderr="")

    result = run_skills_action(
        "install",
        ("codex",),
        "global",
        project_root=tmp_path,
        yes=True,
        capture_output=True,
    )

    assert run.call_count == 1
    assert run.call_args.args[0][3] == "list"
    assert result["executed"] is False
    assert result["unchanged"] is True


@patch("open_claude_design.installer.resolve_skills_runtime", return_value=_runtime())
@patch("open_claude_design.installer.subprocess.run")
def test_uninstall_removes_the_named_skills_from_every_agent_in_scope(
    run: MagicMock,
    _resolve: MagicMock,
    tmp_path: Path,
) -> None:
    run.return_value = SimpleNamespace(returncode=0, stdout="removed", stderr="")

    run_skills_action(
        "uninstall",
        (),
        "project",
        project_root=tmp_path,
        yes=True,
    )

    command = run.call_args.args[0]
    assert command[:4] == [
        "/runtime/bin/npx",
        "--yes",
        f"skills@{SKILLS_CLI_VERSION}",
        "remove",
    ]
    assert all(skill in command for skill in SKILL_NAMES)
    assert "--agent" not in command
    assert "--global" not in command


@patch("open_claude_design.installer.resolve_skills_runtime", return_value=_runtime())
@patch("open_claude_design.installer.subprocess.run")
def test_doctor_reads_installed_state_through_the_same_backend(
    run: MagicMock,
    _resolve: MagicMock,
    tmp_path: Path,
) -> None:
    run.return_value = SimpleNamespace(
        returncode=0,
        stdout=_installed_payload(tmp_path),
        stderr="",
    )

    result = doctor(("cursor",), "project", project_root=tmp_path)

    assert result["agent_skills"]["ready"] is True
    assert all(result["agent_skills"]["skills"].values())
    assert run.call_args.kwargs["shell"] is False
    assert str(run.call_args.kwargs["env"]["PATH"]).split(":", 1)[0] == "/runtime/bin"


@patch("open_claude_design.installer.resolve_skills_runtime", return_value=_runtime())
@patch("open_claude_design.installer.subprocess.run")
def test_doctor_all_agents_lists_the_complete_scope_without_a_literal_wildcard(
    run: MagicMock,
    _resolve: MagicMock,
    tmp_path: Path,
) -> None:
    run.return_value = SimpleNamespace(returncode=0, stdout=_installed_payload(tmp_path), stderr="")

    result = doctor(("*",), "global", project_root=tmp_path)

    command = run.call_args.args[0]
    assert "--agent" not in command
    assert "*" not in command
    assert "--global" in command
    assert result["agent_skills"]["ready"] is True


@patch("open_claude_design.installer.resolve_skills_runtime", return_value=_runtime())
@patch("open_claude_design.installer.subprocess.run")
def test_doctor_rejects_a_named_skill_whose_entrypoint_is_missing(
    run: MagicMock,
    _resolve: MagicMock,
    tmp_path: Path,
) -> None:
    payload = json.loads(_installed_payload(tmp_path))
    missing = Path(payload[0]["path"]) / "SKILL.md"
    missing.unlink()
    run.return_value = SimpleNamespace(returncode=0, stdout=json.dumps(payload), stderr="")

    result = doctor(("codex",), "global", project_root=tmp_path)

    assert result["agent_skills"]["ready"] is False
    assert result["agent_skills"]["skills"][payload[0]["name"]] is False


@patch("open_claude_design.installer.shutil.which", return_value=None)
@patch("open_claude_design.installer.subprocess.run")
def test_managed_node_runtime_is_used_when_system_node_is_missing(
    run: MagicMock,
    _which: MagicMock,
    tmp_path: Path,
) -> None:
    managed_bin = tmp_path / ".local" / "share" / "open-claude-design" / "node" / "bin"
    managed_bin.mkdir(parents=True)
    (managed_bin / "node").touch()
    (managed_bin / "npx").touch()
    run.return_value = SimpleNamespace(returncode=0, stdout="v22.20.0\n", stderr="")

    runtime = resolve_skills_runtime(tmp_path)

    assert runtime.source == "managed"
    assert runtime.npx == managed_bin / "npx"


@patch("open_claude_design.installer.shutil.which", return_value=None)
def test_missing_compatible_node_runtime_has_actionable_guidance(
    _which: MagicMock,
    tmp_path: Path,
) -> None:
    with pytest.raises(InstallError, match="Run install.sh"):
        resolve_skills_runtime(tmp_path)


@patch("open_claude_design.installer.resolve_skills_runtime", return_value=_runtime())
def test_dry_run_does_not_export_or_execute(
    _resolve: MagicMock,
    tmp_path: Path,
) -> None:
    with patch("open_claude_design.installer.subprocess.run") as run:
        result = run_skills_action(
            "install",
            ("*",),
            "project",
            project_root=tmp_path,
            yes=True,
            dry_run=True,
        )

    run.assert_not_called()
    assert result["executed"] is False
    assert "<bundled-skills>" in result["command"]
