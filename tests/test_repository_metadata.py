"""Public repository documentation and contribution-surface contracts."""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

import pytest
import yaml

from open_claude_design.config import (
    SKILL_NAMES,
    SKILLS_CLI_NODE_VERSION,
    SKILLS_CLI_PACKAGE,
    SKILLS_CLI_VERSION,
)

pytestmark = pytest.mark.unit
ROOT = Path(__file__).parents[1]


def test_shell_scripts_track_the_python_configuration_pins() -> None:
    """install.sh / uninstall.sh literals must not drift from config.py."""
    install = (ROOT / "install.sh").read_text(encoding="utf-8")
    uninstall = (ROOT / "uninstall.sh").read_text(encoding="utf-8")

    assert f'SKILLS_NODE_VERSION="{SKILLS_CLI_NODE_VERSION}"' in install

    pinned_cli = f"{SKILLS_CLI_PACKAGE}@{SKILLS_CLI_VERSION}"
    referenced_pins = set(re.findall(r"\bskills@[0-9][0-9.]*\b", uninstall))
    assert referenced_pins == {pinned_cli}

    removal_blocks = re.findall(r"remove \\\n((?:\s+[a-z0-9-]+ \\\n)+)", uninstall)
    assert removal_blocks, "uninstall.sh lost its skill removal fallback"
    for block in removal_blocks:
        removed = {line.strip().removesuffix(" \\") for line in block.splitlines() if line.strip()}
        assert removed == set(SKILL_NAMES)


def test_readme_keeps_activation_order_and_local_links_valid() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    ordered_sections = [
        "<h1>Claude Design for any coding agent</h1>",
        "## Quick start",
        "## One workflow, both sides",
        "## Why Claude Design is the design tool to beat",
        "## What you can do",
        "## Works with Impeccable",
        "> [!TIP]",
        "## Agent compatibility",
        "## Maintenance",
        "## Open for pull requests",
        "## License",
    ]
    offsets = [readme.index(section) for section in ordered_sections]
    assert offsets == sorted(offsets)
    assert "How it feels" not in readme
    assert "THIRD_PARTY_NOTICES" not in readme

    local_targets = [
        target
        for target in re.findall(r"\[[^\]]+\]\(([^)]+)\)", readme)
        if not target.startswith(("http://", "https://", "#"))
    ]
    assert local_targets
    assert all((ROOT / target).is_file() for target in local_targets)
    assert (ROOT / "docs" / "media" / "open-claude-design-hero.png").is_file()


def test_readme_promotes_the_one_line_installer_above_platforms() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    command = "curl -fsSL https://github.com/maxritter/open-claude-design/releases/latest/download/install.sh | sh"

    assert readme.count(command) == 1
    assert readme.index(command) < readme.index("**macOS · Linux · WSL2**")
    subtitle = (
        "**Use Claude Design from your favorite coding agents—no Claude Code installation "
        "or Anthropic API key required.**"
    )
    assert readme.index("<h1>Claude Design for any coding agent</h1>") < readme.index(subtitle) < readme.index(command)
    assert "img.shields.io/github/stars/maxritter/open-claude-design" in readme
    assert "api.star-history.com" not in readme


def test_issue_forms_are_structured_and_security_routes_privately() -> None:
    template_root = ROOT / ".github" / "ISSUE_TEMPLATE"
    bug = yaml.safe_load((template_root / "bug_report.yml").read_text(encoding="utf-8"))
    feature = yaml.safe_load((template_root / "feature_request.yml").read_text(encoding="utf-8"))
    config = yaml.safe_load((template_root / "config.yml").read_text(encoding="utf-8"))

    assert bug["name"] == "Bug report"
    assert feature["name"] == "Feature request"
    assert any(item.get("id") == "reproduction" for item in bug["body"])
    assert any(item.get("id") == "problem" for item in feature["body"])
    assert config["blank_issues_enabled"] is False
    assert config["contact_links"][0]["url"].endswith("/security/policy")


def test_install_and_uninstall_are_posix_release_assets() -> None:
    install = (ROOT / "install.sh").read_text(encoding="utf-8")
    uninstall = (ROOT / "uninstall.sh").read_text(encoding="utf-8")
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    release = (ROOT / ".github" / "workflows" / "release-bootstrap.yml").read_text(encoding="utf-8")

    assert install.startswith("#!/bin/sh\nset -eu\n")
    assert uninstall.startswith("#!/bin/sh\nset -eu\n")
    assert "sh scripts/check-shell.sh" in ci
    assert "sh install.sh" in ci
    assert "sh uninstall.sh --yes" in ci
    assert "dist/uninstall.sh" in ci
    assert "dist/uninstall.sh" in release


def test_installer_has_a_responsive_wordmark_and_completion_guide() -> None:
    install = (ROOT / "install.sh").read_text(encoding="utf-8")

    assert "OPEN CLAUDE DESIGN" in install
    assert "Design intelligence for coding agents" in install
    assert "terminal_columns" in install
    assert "Open Claude Design is ready" in install
    assert "Star Open Claude Design" in install
    assert "Go further with Pilot Shell" in install


def test_product_context_records_the_confirmed_public_constraints() -> None:
    product = (ROOT / "PRODUCT.md").read_text(encoding="utf-8")

    assert "<!-- impeccable:product-schema 1 -->" in product
    assert "no separate website" in product
    assert "macOS, Linux, or WSL2" in product
    assert "Product name: Open Claude Design" in product


def test_vscode_launch_builds_and_installs_the_local_release() -> None:
    tasks = json.loads((ROOT / ".vscode" / "tasks.json").read_text(encoding="utf-8"))
    launch = json.loads((ROOT / ".vscode" / "launch.json").read_text(encoding="utf-8"))

    build_task = next(task for task in tasks["tasks"] if task["label"] == "Open Claude Design: Build release")
    assert build_task["command"] == "bash"
    assert build_task["args"] == ["scripts/build-release.sh"]

    configuration = next(
        item for item in launch["configurations"] if item["name"] == "Open Claude Design: Build and run local installer"
    )
    assert configuration["preLaunchTask"] == build_task["label"]
    assert configuration["type"] == "debugpy"
    assert configuration["program"] == "${workspaceFolder}/scripts/run_local_installer.py"
    assert configuration["console"] == "integratedTerminal"


def test_manual_release_is_gated_and_reproducible() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    bootstrap = (ROOT / ".github" / "workflows" / "release-bootstrap.yml").read_text(encoding="utf-8")
    security = (ROOT / ".github" / "workflows" / "security.yml").read_text(encoding="utf-8")
    package_config = (ROOT / "src" / "open_claude_design" / "config.py").read_text(encoding="utf-8")
    lockfile = (ROOT / "uv.lock").read_text(encoding="utf-8")
    precommit = (ROOT / ".pre-commit-config.yaml").read_text(encoding="utf-8")

    version = project["project"]["version"]
    assert f'VERSION: Final = "{version}"' in package_config
    assert re.search(
        rf'\[\[package\]\]\nname = "open-claude-design"\nversion = "{version}"',
        lockfile,
    )
    assert not (ROOT / "release-please-config.json").exists()
    assert not (ROOT / ".release-please-manifest.json").exists()
    assert not (ROOT / ".github" / "workflows" / "release.yml").exists()
    assert "workflow_dispatch:" in bootstrap
    assert "push:" not in bootstrap
    assert "gh release create" in bootstrap
    assert "gh release edit" in bootstrap and "--draft=false" in bootstrap
    assert "environment: release" in bootstrap
    assert bootstrap.count("dist/CHANGELOG.md") >= 3
    assert "trivy-action@" in security
    assert "dependency-review-action@" in security
    assert "detect-private-key" in precommit
    assert "scripts/security-check.sh" in precommit

    for workflow in (bootstrap, security):
        refs = re.findall(r"uses:\s+[^@\s]+@([^\s#]+)", workflow)
        assert refs
        assert all(re.fullmatch(r"[0-9a-f]{40}", ref) for ref in refs)
