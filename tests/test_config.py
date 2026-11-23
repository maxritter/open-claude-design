"""Central configuration consistency."""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from open_claude_artifacts import __version__
from open_claude_artifacts.commands import ARTIFACT_COMMANDS
from open_claude_artifacts.config import (
    ARTIFACT_FILE_KINDS,
    ARTIFACT_TYPE_KINDS,
    DEFAULT_INSTALL_SCOPE,
    INSTALL_SCOPES,
    OAUTH_CLIENT_ID,
    OAUTH_SCOPES,
    PACKAGE_NAME,
    SKILL_NAMES,
    SKILLS_CLI_VERSION,
    VERSION,
)

pytestmark = pytest.mark.unit


def test_central_version_matches_project_metadata() -> None:
    project = tomllib.loads((Path(__file__).parents[1] / "pyproject.toml").read_text(encoding="utf-8"))

    assert VERSION == __version__ == project["project"]["version"]
    assert PACKAGE_NAME == project["project"]["name"] == "open-claude-artifacts"


def test_public_command_and_scope_configuration_is_complete() -> None:
    assert {"list", "types", "inspect", "files", "pull", "push", "publish", "render", "sync", "assets", "db"} <= set(
        ARTIFACT_COMMANDS
    )
    assert DEFAULT_INSTALL_SCOPE in INSTALL_SCOPES
    assert "open-claude-artifacts" in SKILL_NAMES
    assert "open-claude-design-quality" in SKILL_NAMES
    assert SKILLS_CLI_VERSION == "1.7.0"
    assert OAUTH_CLIENT_ID == "9d1c250a-e61b-44d9-88ed-5944d1962f5e"  # gitleaks:allow
    assert OAUTH_SCOPES == ("user:profile", "user:inference", "user:sessions:claude_code")
    assert ARTIFACT_FILE_KINDS["slides"] == ("project/deck.json", (4, 5))
    assert {"Design", "Slides", "Design System", "Data", "Whiteboard", "Docs", "Sheets"} <= set(ARTIFACT_TYPE_KINDS)
