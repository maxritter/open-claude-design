"""Cross-agent skills CLI adapter contracts."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

import open_claude_design.installer as installer_module
from open_claude_design.config import FEATURED_AGENT_IDS, SKILL_NAMES, SKILLS_CLI_VERSION
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
    list_calls = 0

    def execute(command: list[str], **kwargs: object) -> SimpleNamespace:
        nonlocal list_calls
        if command[3] == "list":
            list_calls += 1
            stdout = "[]" if list_calls == 1 else _installed_payload(tmp_path)
            return SimpleNamespace(returncode=0, stdout=stdout, stderr="")
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

    command = next(call.args[0] for call in run.call_args_list if call.args[0][3] == "add")
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
    assert result["verified"] is True


@patch("open_claude_design.installer.resolve_skills_runtime", return_value=_runtime())
@patch("open_claude_design.installer.subprocess.run")
def test_install_rejects_backend_success_when_runtime_skills_are_not_installed(
    run: MagicMock,
    _resolve: MagicMock,
    tmp_path: Path,
) -> None:
    def execute(command: list[str], **_kwargs: object) -> SimpleNamespace:
        if command[3] == "list":
            return SimpleNamespace(returncode=0, stdout="[]", stderr="")
        return SimpleNamespace(returncode=0, stdout="installed", stderr="")

    run.side_effect = execute

    with pytest.raises(InstallError, match="could not be verified"):
        run_skills_action(
            "install",
            ("codex",),
            "global",
            project_root=tmp_path,
            yes=True,
            capture_output=True,
        )


@patch("open_claude_design.installer.resolve_skills_runtime", return_value=_runtime())
@patch("open_claude_design.installer.subprocess.run")
def test_install_rejects_success_when_one_requested_agent_remains_unconnected(
    run: MagicMock,
    _resolve: MagicMock,
    tmp_path: Path,
) -> None:
    installed = False

    def execute(command: list[str], **_kwargs: object) -> SimpleNamespace:
        nonlocal installed
        if command[3] == "add":
            installed = True
            return SimpleNamespace(returncode=0, stdout="installed", stderr="")
        agent = command[command.index("--agent") + 1]
        stdout = _installed_payload(tmp_path) if installed and agent == "codex" else "[]"
        return SimpleNamespace(returncode=0, stdout=stdout, stderr="")

    run.side_effect = execute

    with pytest.raises(InstallError, match="cursor"):
        run_skills_action(
            "install",
            ("codex", "cursor"),
            "global",
            project_root=tmp_path,
            yes=True,
            capture_output=True,
        )


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
def test_doctor_all_agents_verifies_every_agent_without_a_literal_wildcard(
    run: MagicMock,
    _resolve: MagicMock,
    tmp_path: Path,
) -> None:
    run.return_value = SimpleNamespace(returncode=0, stdout=_installed_payload(tmp_path), stderr="")

    result = doctor(("*",), "global", project_root=tmp_path)

    commands = [call.args[0] for call in run.call_args_list]
    assert len(commands) == len(FEATURED_AGENT_IDS)
    assert {command[command.index("--agent") + 1] for command in commands} == set(FEATURED_AGENT_IDS)
    assert all("*" not in command and "--global" in command for command in commands)
    assert result["agent_skills"]["ready"] is True
    assert set(result["agent_skills"]["agents"]) == set(FEATURED_AGENT_IDS)


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


def test_data_root_prefers_the_installed_wheel_layout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An installed wheel resolves skills from open_claude_design/data/skills."""
    package_dir = tmp_path / "open_claude_design"
    skill = SKILL_NAMES[0]
    source = package_dir / "data" / "skills" / skill
    source.mkdir(parents=True)
    (source / "SKILL.md").write_text("---\nname: x\n---\n", encoding="utf-8")
    (source / "tests").mkdir()
    (source / "tests" / "evals.json").write_text("[]", encoding="utf-8")
    monkeypatch.setattr(installer_module, "__file__", str(package_dir / "installer.py"))

    files = installer_module._runtime_files(skill)

    assert set(files) == {"SKILL.md"}
    assert files["SKILL.md"] == source / "SKILL.md"


def test_data_root_fails_clearly_when_package_data_is_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    orphan = tmp_path / "deep" / "nested" / "package"
    orphan.mkdir(parents=True)
    monkeypatch.setattr(installer_module, "__file__", str(orphan / "installer.py"))

    with pytest.raises(InstallError, match="package data is missing"):
        installer_module._data_root()
