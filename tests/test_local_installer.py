"""VS Code local-installer runner contracts."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from scripts.run_local_installer import find_release_wheel, run_local_installer

pytestmark = pytest.mark.unit


def test_find_release_wheel_requires_exactly_one_built_wheel(tmp_path: Path) -> None:
    dist = tmp_path / "dist"
    dist.mkdir()

    with pytest.raises(RuntimeError, match="exactly one local release wheel"):
        find_release_wheel(dist)

    expected = dist / "open_claude_design-1.0.0-py3-none-any.whl"
    expected.touch()
    assert find_release_wheel(dist) == expected

    (dist / "open_claude_design-0.2.0-py3-none-any.whl").touch()
    with pytest.raises(RuntimeError, match="exactly one local release wheel"):
        find_release_wheel(dist)


def test_local_installer_uses_built_asset_without_node_debug_injection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dist = tmp_path / "dist"
    dist.mkdir()
    wheel = dist / "open_claude_design-1.0.0-py3-none-any.whl"
    wheel.touch()
    installer = dist / "install.sh"
    installer.touch()
    monkeypatch.setenv("NODE_OPTIONS", "--require vscode-js-debug/bootloader.js")
    monkeypatch.setenv("VSCODE_INSPECTOR_OPTIONS", "debug-session")
    with patch("scripts.run_local_installer.subprocess.run") as run:
        run_local_installer(tmp_path, ("--all-agents",))

    command = run.call_args.args[0]
    environment = run.call_args.kwargs["env"]
    assert command == ["sh", str(installer), "--all-agents"]
    assert run.call_args.kwargs["cwd"] == tmp_path
    assert environment["OPEN_CLAUDE_DESIGN_PACKAGE"] == str(wheel)
    assert "NODE_OPTIONS" not in environment
    assert "VSCODE_INSPECTOR_OPTIONS" not in environment
    assert environment["PATH"] == os.environ["PATH"]
