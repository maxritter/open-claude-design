"""Native Claude Design connector detection contracts."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from open_claude_design.config import CLAUDE_CONFIG_ENV, CLAUDE_DESIGN_ENDPOINT
from open_claude_design.connectors import detect_native_connectors, native_connector_report

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _isolated_claude_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(CLAUDE_CONFIG_ENV, raising=False)


def _write(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_reports_a_claude_code_http_connector_with_its_server_name(tmp_path: Path) -> None:
    _write(
        tmp_path / ".claude.json",
        {"mcpServers": {"claude-design": {"type": "http", "url": CLAUDE_DESIGN_ENDPOINT}}},
    )

    report = native_connector_report(home=tmp_path)

    assert report["bypass_detected"] is True
    assert report["connectors"] == [
        {
            "agent": "Claude Code",
            "path": str(tmp_path / ".claude.json"),
            "location": "mcpServers.claude-design.url",
            "server": "claude-design",
        }
    ]
    assert "claude mcp remove" in str(report["remediation"])


def test_reports_an_endpoint_passed_through_a_launch_command(tmp_path: Path) -> None:
    _write(
        tmp_path / ".claude.json",
        {
            "mcpServers": {
                "design-proxy": {
                    "command": "npx",
                    "args": ["-y", "mcp-remote", f"{CLAUDE_DESIGN_ENDPOINT}?flavor=beta"],
                }
            }
        },
    )

    detected = detect_native_connectors(home=tmp_path)

    assert [entry["server"] for entry in detected] == ["design-proxy"]
    assert detected[0]["location"] == "mcpServers.design-proxy.args.[2]"


def test_reports_a_codex_toml_connector(tmp_path: Path) -> None:
    config = tmp_path / ".codex" / "config.toml"
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text(
        f'[mcp_servers.claude-design]\nurl = "{CLAUDE_DESIGN_ENDPOINT}"\n',
        encoding="utf-8",
    )

    detected = detect_native_connectors(home=tmp_path)

    assert detected == [
        {
            "agent": "Codex",
            "path": str(config),
            "location": "mcp_servers.claude-design.url",
            "server": "claude-design",
        }
    ]


def test_reports_a_project_scoped_connector(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    project = tmp_path / "project"
    _write(project / ".mcp.json", {"mcpServers": {"design": {"url": CLAUDE_DESIGN_ENDPOINT}}})

    detected = detect_native_connectors(home=home, project_root=project)

    assert [entry["path"] for entry in detected] == [str(project / ".mcp.json")]


def test_honours_a_relocated_claude_code_configuration_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    relocated = tmp_path / "relocated"
    _write(relocated / ".claude.json", {"mcpServers": {"claude-design": {"url": CLAUDE_DESIGN_ENDPOINT}}})
    monkeypatch.setenv(CLAUDE_CONFIG_ENV, str(relocated))

    detected = detect_native_connectors(home=home)

    assert [entry["path"] for entry in detected] == [str(relocated / ".claude.json")]


def test_never_echoes_configured_values_from_a_credential_bearing_config(tmp_path: Path) -> None:
    _write(
        tmp_path / ".claude.json",
        {
            "oauthAccount": {"accessToken": "secret-host-token"},
            "mcpServers": {
                "claude-design": {
                    "url": CLAUDE_DESIGN_ENDPOINT,
                    "headers": {"Authorization": "Bearer secret-connector-token"},
                }
            },
        },
    )

    serialized = json.dumps(native_connector_report(home=tmp_path))

    assert "secret-host-token" not in serialized
    assert "secret-connector-token" not in serialized


def test_stays_quiet_without_a_native_connector(tmp_path: Path) -> None:
    _write(tmp_path / ".claude.json", {"mcpServers": {"unrelated": {"url": "https://example.invalid/mcp"}}})

    report = native_connector_report(home=tmp_path)

    assert report == {"bypass_detected": False, "connectors": []}


def test_ignores_unreadable_missing_and_malformed_configuration(tmp_path: Path) -> None:
    (tmp_path / ".claude.json").write_text("{not json", encoding="utf-8")
    codex = tmp_path / ".codex" / "config.toml"
    codex.parent.mkdir(parents=True, exist_ok=True)
    codex.write_text("this is = not = toml", encoding="utf-8")

    assert detect_native_connectors(home=tmp_path) == []


def test_ignores_a_configuration_file_beyond_the_size_bound(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("open_claude_design.connectors.CLAUDE_DESIGN_NATIVE_CONNECTOR_MAX_BYTES", 16)
    _write(tmp_path / ".claude.json", {"mcpServers": {"claude-design": {"url": CLAUDE_DESIGN_ENDPOINT}}})

    assert detect_native_connectors(home=tmp_path) == []
