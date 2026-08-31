"""Portable Agent Skills installation through Vercel's maintained skills CLI."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from open_claude_design.config import (
    FEATURED_AGENT_IDS,
    PACKAGE_NAME,
    SKILL_NAMES,
    SKILLS_CLI_NODE_MINIMUM,
    SKILLS_CLI_NODE_RUNTIME_PARTS,
    SKILLS_CLI_PACKAGE,
    SKILLS_CLI_VERSION,
    SUPPORTED_PLATFORM_LABELS,
    VERSION,
)

Scope = Literal["project", "global"]
Action = Literal["install", "update", "uninstall"]

SKILLS = SKILL_NAMES
AGENTS = FEATURED_AGENT_IDS


class InstallError(RuntimeError):
    """Raised when portable skill installation cannot complete safely."""


@dataclass(frozen=True)
class SkillsRuntime:
    """Compatible Node.js executables used for the pinned skills CLI."""

    node: Path
    npx: Path
    source: str
    version: tuple[int, int, int]


def _data_root() -> Path:
    installed = Path(__file__).parent / "data"
    if installed.is_dir():
        return installed
    repository = Path(__file__).parents[2]
    if (repository / "skills").is_dir():
        return repository
    raise InstallError("Open Claude Design package data is missing.")


def _runtime_files(skill: str) -> dict[str, Path]:
    source = _data_root() / "skills" / skill
    if not (source / "SKILL.md").is_file():
        raise InstallError(f"Skill source is incomplete: {skill}")
    return {
        path.relative_to(source).as_posix(): path
        for path in sorted(source.rglob("*"))
        if path.is_file() and "tests" not in path.relative_to(source).parts and path.name != ".DS_Store"
    }


def _export_runtime_skills(destination: Path) -> Path:
    """Create a sanitized local source accepted by the skills CLI."""
    skills_root = destination / "skills"
    for skill in SKILLS:
        for relative, source in _runtime_files(skill).items():
            target = skills_root / skill / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
    return destination


def _runtime_tree_matches(skill: str, installed: Path) -> bool:
    """Return whether an installed skill is a complete byte-for-byte runtime copy."""
    if not installed.is_dir() or installed.is_symlink():
        return False
    expected = _runtime_files(skill)
    try:
        actual = {
            path.relative_to(installed).as_posix()
            for path in installed.rglob("*")
            if path.is_file() and path.name != ".DS_Store"
        }
        if actual != set(expected):
            return False
        return all(
            not (installed / relative).is_symlink() and (installed / relative).read_bytes() == source.read_bytes()
            for relative, source in expected.items()
        )
    except OSError:
        return False


def _parse_node_version(raw: str) -> tuple[int, int, int] | None:
    value = raw.strip().removeprefix("v")
    parts = value.split(".")
    if len(parts) < 3:
        return None
    try:
        return int(parts[0]), int(parts[1]), int(parts[2].split("-", 1)[0])
    except ValueError:
        return None


def _runtime_from(node: Path, npx: Path, source: str) -> SkillsRuntime | None:
    try:
        result = subprocess.run(
            [str(node), "--version"],
            capture_output=True,
            text=True,
            shell=False,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    version = _parse_node_version(result.stdout)
    if result.returncode != 0 or version is None or version < SKILLS_CLI_NODE_MINIMUM:
        return None
    return SkillsRuntime(node=node, npx=npx, source=source, version=version)


def resolve_skills_runtime(home: Path | None = None) -> SkillsRuntime:
    """Resolve a compatible system or Open Claude Design-managed Node runtime."""
    system_node = shutil.which("node")
    system_npx = shutil.which("npx")
    if system_node and system_npx:
        runtime = _runtime_from(Path(system_node), Path(system_npx), "system")
        if runtime is not None:
            return runtime

    user_home = (home or Path.home()).resolve()
    managed_bin = user_home.joinpath(*SKILLS_CLI_NODE_RUNTIME_PARTS) / "bin"
    runtime = _runtime_from(managed_bin / "node", managed_bin / "npx", "managed")
    if runtime is not None:
        return runtime

    minimum = ".".join(str(part) for part in SKILLS_CLI_NODE_MINIMUM)
    raise InstallError(
        f"Node.js {minimum}+ with npx is required for cross-agent skill installation. "
        "Run install.sh to set up the managed runtime, or install a compatible Node.js release."
    )


def _skills_prefix(runtime: SkillsRuntime) -> list[str]:
    return [str(runtime.npx), "--yes", f"{SKILLS_CLI_PACKAGE}@{SKILLS_CLI_VERSION}"]


def _skills_environment(runtime: SkillsRuntime) -> dict[str, str]:
    """Expose the resolved Node binary to npx shebangs in fresh shells."""
    environment = os.environ.copy()
    environment["DO_NOT_TRACK"] = "1"
    existing_path = environment.get("PATH", "")
    environment["PATH"] = str(runtime.node.parent) + (os.pathsep + existing_path if existing_path else "")
    return environment


def _installed_skills(
    runtime: SkillsRuntime,
    root: Path,
    agents: tuple[str, ...],
    scope: Scope,
) -> tuple[subprocess.CompletedProcess[str], dict[str, Path]]:
    """List installed skills and retain only well-formed paths for this package."""
    command = [*_skills_prefix(runtime), "list", *_agent_flags(agents), "--json"]
    if scope == "global":
        command.append("--global")
    listed = subprocess.run(
        command,
        cwd=root,
        env=_skills_environment(runtime),
        capture_output=True,
        text=True,
        shell=False,
        timeout=60,
        check=False,
    )
    paths: dict[str, Path] = {}
    if listed.returncode != 0:
        return listed, paths
    try:
        entries = json.loads(listed.stdout)
    except json.JSONDecodeError:
        return listed, paths
    if not isinstance(entries, list):
        return listed, paths
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        name = entry.get("name")
        raw_path = entry.get("path")
        if name in SKILLS and isinstance(raw_path, str) and raw_path:
            paths[name] = Path(raw_path)
    return listed, paths


def _installed_skill_state(paths: dict[str, Path]) -> dict[str, bool]:
    return {skill: skill in paths and _runtime_tree_matches(skill, paths[skill]) for skill in SKILLS}


def _verified_install_state(
    runtime: SkillsRuntime,
    root: Path,
    agents: tuple[str, ...],
    scope: Scope,
) -> tuple[dict[str, bool], dict[str, dict[str, bool]], list[str]]:
    """Verify byte-complete skills independently for every requested agent."""
    targets = AGENTS if agents == ("*",) else agents
    if not targets:
        listed, paths = _installed_skills(runtime, root, (), scope)
        state = _installed_skill_state(paths)
        errors = [] if listed.returncode == 0 else [(listed.stderr or "skills list failed").strip()[-500:]]
        return state, {}, errors

    aggregate = {skill: True for skill in SKILLS}
    agent_state: dict[str, dict[str, bool]] = {}
    errors: list[str] = []
    for agent in targets:
        listed, paths = _installed_skills(runtime, root, (agent,), scope)
        state = _installed_skill_state(paths)
        agent_state[agent] = state
        for skill, ready in state.items():
            aggregate[skill] = aggregate[skill] and listed.returncode == 0 and ready
        if listed.returncode != 0:
            detail = (listed.stderr or listed.stdout or "skills list failed").strip()[-500:]
            errors.append(f"{agent}: {detail}")
        elif not all(state.values()):
            missing = [skill for skill, ready in state.items() if not ready]
            errors.append(f"{agent}: missing, stale, or incomplete {', '.join(missing)}")
    return aggregate, agent_state, errors


def _agent_flags(agents: tuple[str, ...]) -> list[str]:
    return [item for agent in agents for item in ("--agent", agent)]


def _skills_command(
    runtime: SkillsRuntime,
    action: Action,
    source: Path | None,
    agents: tuple[str, ...],
    scope: Scope,
    *,
    yes: bool,
) -> list[str]:
    command = _skills_prefix(runtime)
    if action in {"install", "update"}:
        if source is None:
            raise InstallError("The bundled skill source is unavailable.")
        command.extend(["add", str(source), "--skill", "*", "--copy"])
    else:
        command.extend(["remove", *SKILLS])
    command.extend(_agent_flags(agents))
    if scope == "global":
        command.append("--global")
    if yes:
        command.append("--yes")
    return command


def run_skills_action(
    action: Action,
    agents: tuple[str, ...],
    scope: Scope,
    *,
    project_root: Path | None = None,
    home: Path | None = None,
    yes: bool = False,
    dry_run: bool = False,
    capture_output: bool = False,
) -> dict[str, object]:
    """Run one pinned, shell-free skills CLI action."""
    root = (project_root or Path.cwd()).resolve()
    runtime = resolve_skills_runtime(home)
    if dry_run:
        preview = _skills_command(runtime, action, Path("<bundled-skills>"), agents, scope, yes=yes)
        return {
            "action": action,
            "scope": scope,
            "agents": list(agents) or ["auto-detect"],
            "skills": list(SKILLS),
            "command": preview,
            "executed": False,
        }

    if action in {"install", "update"}:
        current, current_agents, current_errors = _verified_install_state(runtime, root, agents, scope)
        if not current_errors and all(current.values()):
            return {
                "action": action,
                "scope": scope,
                "agents": list(agents) or ["auto-detect"],
                "skills": list(SKILLS),
                "skills_cli": f"{SKILLS_CLI_PACKAGE}@{SKILLS_CLI_VERSION}",
                "node": ".".join(str(part) for part in runtime.version),
                "node_source": runtime.source,
                "executed": False,
                "unchanged": True,
                "verified": True,
                "agent_state": current_agents,
            }

    with tempfile.TemporaryDirectory(prefix="open-claude-design-skills-") as temporary:
        source = _export_runtime_skills(Path(temporary)) if action in {"install", "update"} else None
        command = _skills_command(runtime, action, source, agents, scope, yes=yes)
        try:
            result = subprocess.run(
                command,
                cwd=root,
                env=_skills_environment(runtime),
                capture_output=capture_output,
                text=True,
                shell=False,
                timeout=300,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as error:
            raise InstallError(f"Cross-agent skill {action} failed: {error}") from error
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "skills CLI failed").strip()
        raise InstallError(detail[-1000:])
    verified_agents: dict[str, dict[str, bool]] = {}
    if action in {"install", "update"}:
        verified, verified_agents, verification_errors = _verified_install_state(runtime, root, agents, scope)
        if verification_errors or not all(verified.values()):
            missing = [skill for skill, ready in verified.items() if not ready]
            raise InstallError(
                "Agent skill installation reported success but could not be verified byte-for-byte. "
                f"Missing, stale, or incomplete: {', '.join(missing) or 'unknown'}. " + "; ".join(verification_errors)
            )
    payload: dict[str, object] = {
        "action": action,
        "scope": scope,
        "agents": list(agents) or ["auto-detect"],
        "skills": list(SKILLS),
        "skills_cli": f"{SKILLS_CLI_PACKAGE}@{SKILLS_CLI_VERSION}",
        "node": ".".join(str(part) for part in runtime.version),
        "node_source": runtime.source,
        "executed": True,
    }
    if action in {"install", "update"}:
        payload["verified"] = True
        payload["agent_state"] = verified_agents
    return payload


def doctor(
    agents: tuple[str, ...],
    scope: Scope,
    *,
    project_root: Path | None = None,
    home: Path | None = None,
    check_auth: bool = False,
) -> dict[str, object]:
    """Return cross-agent installer and Claude Design bridge readiness."""
    root = (project_root or Path.cwd()).resolve()
    try:
        runtime = resolve_skills_runtime(home)
        skill_state, agent_state, errors = _verified_install_state(runtime, root, agents, scope)
        installer_status: dict[str, object] = {
            "ready": not errors and all(skill_state.values()),
            "backend": f"{SKILLS_CLI_PACKAGE}@{SKILLS_CLI_VERSION}",
            "node": ".".join(str(part) for part in runtime.version),
            "node_source": runtime.source,
            "skills": skill_state,
        }
        if agent_state:
            installer_status["agents"] = {
                agent: {"ready": all(state.values()), "skills": state} for agent, state in agent_state.items()
            }
        if errors:
            installer_status["error"] = "; ".join(errors)
        elif not all(skill_state.values()):
            missing = [skill for skill, ready in skill_state.items() if not ready]
            installer_status["error"] = f"Missing, stale, or incomplete skills: {', '.join(missing)}"
    except InstallError as error:
        installer_status = {
            "ready": False,
            "backend": f"{SKILLS_CLI_PACKAGE}@{SKILLS_CLI_VERSION}",
            "skills": {skill: False for skill in SKILLS},
            "error": str(error),
        }

    bridge_status: dict[str, object] = {
        "platform_supported": sys_platform_supported(),
        "platforms": list(SUPPORTED_PLATFORM_LABELS),
        "authentication": "not checked",
    }
    if check_auth and bridge_status["platform_supported"]:
        try:
            from open_claude_design.bridge import ClaudeDesignClient

            bridge_status.update(ClaudeDesignClient().status())
        except Exception as error:
            bridge_status["authenticated"] = False
            bridge_status["error"] = str(error)

    return {
        "package_version": VERSION,
        "scope": scope,
        "agents": list(agents) or ["auto-detect"],
        "agent_skills": installer_status,
        "claude_design_bridge": bridge_status,
    }


def sys_platform_supported() -> bool:
    """Return whether the authenticated bridge supports this platform."""
    import sys

    return sys.platform == "darwin" or sys.platform.startswith("linux")


def package_summary() -> dict[str, object]:
    """Return the portable package inventory without running external tools."""
    return {
        "package": PACKAGE_NAME,
        "version": VERSION,
        "skills": list(SKILLS),
        "skills_cli": f"{SKILLS_CLI_PACKAGE}@{SKILLS_CLI_VERSION}",
        "featured_agents": list(AGENTS),
        "additional_agents": "Any agent supported by the Agent Skills installer",
    }
