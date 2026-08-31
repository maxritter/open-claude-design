"""Central configuration consistency."""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from open_claude_design import __version__
from open_claude_design.config import (
    BRIDGE_COMMAND_NAMES,
    CLAUDE_DESIGN_OAUTH_CLIENT_ID,
    CLAUDE_DESIGN_OAUTH_SCOPES,
    DEFAULT_INSTALL_SCOPE,
    INSTALL_SCOPES,
    SKILL_NAMES,
    SKILLS_CLI_VERSION,
    VERSION,
)

pytestmark = pytest.mark.unit


def test_central_version_matches_project_metadata() -> None:
    project = tomllib.loads((Path(__file__).parents[1] / "pyproject.toml").read_text(encoding="utf-8"))

    assert VERSION == __version__ == project["project"]["version"]


def test_public_command_and_scope_configuration_is_complete() -> None:
    assert BRIDGE_COMMAND_NAMES == (
        "status",
        "authoring-context",
        "tools",
        "describe",
        "call",
        "planned-call",
        "preview",
        "files",
        "pull",
        "push",
        "delete",
    )
    assert DEFAULT_INSTALL_SCOPE in INSTALL_SCOPES
    assert "open-claude-design-quality" in SKILL_NAMES
    assert SKILLS_CLI_VERSION == "1.5.23"
    assert CLAUDE_DESIGN_OAUTH_CLIENT_ID == "59637612-477b-4836-a601-b0589eda7704"  # gitleaks:allow
    assert CLAUDE_DESIGN_OAUTH_SCOPES == ("user:design:read", "user:design:write")
