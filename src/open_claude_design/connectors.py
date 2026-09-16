"""Detection of native Claude Design connectors that bypass the authenticated bridge.

A host agent can register the Claude Design MCP endpoint directly. Those registrations
authenticate with the host's own account token rather than an Open Claude Design
credential, so the endpoint answers HTTP 403 and the host reports Claude Design as
unavailable while the bridge works. Reporting the offending file keeps that failure
diagnosable instead of looking like a Claude Design outage.
"""

from __future__ import annotations

import json
import os
import tomllib
from collections.abc import Iterator
from pathlib import Path
from typing import Any, Final

from open_claude_design.config import (
    CLAUDE_CONFIG_ENV,
    CLAUDE_DESIGN_ENDPOINT,
    CLAUDE_DESIGN_NATIVE_CONNECTOR_CONTAINER_KEYS,
    CLAUDE_DESIGN_NATIVE_CONNECTOR_HOME_CONFIGS,
    CLAUDE_DESIGN_NATIVE_CONNECTOR_MAX_BYTES,
    CLAUDE_DESIGN_NATIVE_CONNECTOR_MAX_DEPTH,
    CLAUDE_DESIGN_NATIVE_CONNECTOR_PROJECT_CONFIGS,
    CLAUDE_DESIGN_NATIVE_CONNECTOR_REMEDIATION,
)

_NORMALIZED_ENDPOINT: Final = CLAUDE_DESIGN_ENDPOINT.casefold().rstrip("/")


def _matches_endpoint(value: str) -> bool:
    """Match both a plain URL field and an endpoint embedded in a launch command."""
    if CLAUDE_DESIGN_ENDPOINT in value:
        return True
    return value.casefold().split("?", 1)[0].rstrip("/") == _NORMALIZED_ENDPOINT


def _endpoint_trails(node: Any, trail: tuple[str, ...] = ()) -> Iterator[tuple[str, ...]]:
    """Yield the key trail of every string in a parsed config that names the endpoint."""
    if len(trail) > CLAUDE_DESIGN_NATIVE_CONNECTOR_MAX_DEPTH:
        return
    if isinstance(node, str):
        if _matches_endpoint(node):
            yield trail
    elif isinstance(node, dict):
        for key, value in node.items():
            yield from _endpoint_trails(value, (*trail, str(key)))
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from _endpoint_trails(value, (*trail, f"[{index}]"))


def _server_name(trail: tuple[str, ...]) -> str | None:
    """Return the connector name that owns the matched value, ignoring schema keys."""
    for part in reversed(trail[:-1]):
        if part.startswith("[") or part in CLAUDE_DESIGN_NATIVE_CONNECTOR_CONTAINER_KEYS:
            continue
        return part
    return None


def _load_config(path: Path) -> Any | None:
    """Parse a bounded JSON or TOML agent config, ignoring anything unreadable."""
    try:
        if path.stat().st_size > CLAUDE_DESIGN_NATIVE_CONNECTOR_MAX_BYTES:
            return None
        raw = path.read_bytes()
    except OSError:
        return None
    try:
        if path.suffix == ".toml":
            return tomllib.loads(raw.decode("utf-8"))
        return json.loads(raw)
    except (UnicodeDecodeError, ValueError, RecursionError):
        return None


def _candidate_configs(home: Path, project_root: Path | None) -> list[tuple[str, Path]]:
    candidates = [(agent, home.joinpath(*parts)) for agent, parts in CLAUDE_DESIGN_NATIVE_CONNECTOR_HOME_CONFIGS]
    override = os.environ.get(CLAUDE_CONFIG_ENV)
    if override:
        candidates.append(("Claude Code", Path(override).expanduser() / ".claude.json"))
    if project_root is not None:
        candidates.extend(
            (agent, project_root.joinpath(*parts)) for agent, parts in CLAUDE_DESIGN_NATIVE_CONNECTOR_PROJECT_CONFIGS
        )
    seen: set[Path] = set()
    unique: list[tuple[str, Path]] = []
    for agent, path in candidates:
        if path in seen:
            continue
        seen.add(path)
        unique.append((agent, path))
    return unique


def detect_native_connectors(
    *,
    home: Path | None = None,
    project_root: Path | None = None,
) -> list[dict[str, str]]:
    """Return every agent config entry that points a native connector at Claude Design.

    Only file paths and configuration keys are reported; no configured value is read
    back, because these files also hold host credentials.
    """
    user_home = (home or Path.home()).expanduser()
    detected: list[dict[str, str]] = []
    for agent, path in _candidate_configs(user_home, project_root):
        config = _load_config(path)
        if config is None:
            continue
        for trail in _endpoint_trails(config):
            entry = {"agent": agent, "path": str(path), "location": ".".join(trail)}
            server = _server_name(trail)
            if server is not None:
                entry["server"] = server
            detected.append(entry)
    return detected


def native_connector_report(
    *,
    home: Path | None = None,
    project_root: Path | None = None,
) -> dict[str, object]:
    """Summarize native connector conflicts for the installer and doctor payloads."""
    connectors = detect_native_connectors(home=home, project_root=project_root)
    report: dict[str, object] = {"bypass_detected": bool(connectors), "connectors": connectors}
    if connectors:
        report["remediation"] = CLAUDE_DESIGN_NATIVE_CONNECTOR_REMEDIATION
    return report
