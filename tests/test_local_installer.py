"""VS Code local-installer runner contracts."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from scripts.run_local_installer import find_release_wheel, run_local_installer

pytestmark = pytest.mark.unit
ROOT = Path(__file__).parents[1]


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)


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
    assert command == ["sh", "-s", "--", "--all-agents"]
    assert run.call_args.kwargs["cwd"] == tmp_path
    assert run.call_args.kwargs["input"] == ""
    assert run.call_args.kwargs["text"] is True
    assert environment["OPEN_CLAUDE_DESIGN_PACKAGE"] == str(wheel)
    assert "NODE_OPTIONS" not in environment
    assert "VSCODE_INSPECTOR_OPTIONS" not in environment
    assert environment["PATH"] == os.environ["PATH"]


def test_advertised_pipe_mode_reaches_install_and_uninstall_completion(tmp_path: Path) -> None:
    """Children must never consume the streamed remainder of either shell script."""
    home = tmp_path / "home"
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_cli = tmp_path / "open-claude-design"
    fake_wheel = tmp_path / "open_claude_design-1.0.0-py3-none-any.whl"
    uv_trace = tmp_path / "uv-trace.txt"
    fake_wheel.touch()

    _write_executable(
        fake_cli,
        """#!/bin/sh
case "${1:-}" in
  --version) printf '1.0.0\\n' ;;
  install|uninstall) cat > /dev/null; printf '{}\\n' ;;
  status) exit 1 ;;
  *) exit 0 ;;
esac
""",
    )
    _write_executable(
        fake_bin / "uv",
        """#!/bin/sh
if [ "${1:-}" = "--version" ]; then
  printf 'uv 0.12.7\\n'
elif [ "${1:-}" = "tool" ] && [ "${2:-}" = "install" ] && [ "${3:-}" = "--help" ]; then
  printf '%s\\n' '--default-index' '--no-sources'
elif [ "${1:-}" = "tool" ] && [ "${2:-}" = "dir" ] && [ "${3:-}" = "--bin" ]; then
  printf '%s\\n' "${UV_TOOL_BIN_DIR:-$HOME/.local/bin}"
elif [ "${1:-}" = "tool" ] && [ "${2:-}" = "install" ]; then
  {
    printf 'args=%s\\n' "$*"
    env | grep '^UV_' | sort
  } >> "$UV_TRACE"
  mkdir -p "$HOME/.local/bin"
  cp "$FAKE_OPEN_CLAUDE_DESIGN" "$HOME/.local/bin/open-claude-design"
  chmod 0755 "$HOME/.local/bin/open-claude-design"
fi
""",
    )
    _write_executable(
        fake_bin / "node",
        """#!/bin/sh
if [ "${1:-}" = "--version" ]; then printf 'v22.20.0\\n'; fi
""",
    )
    _write_executable(fake_bin / "npx", "#!/bin/sh\nexit 0\n")

    environment = os.environ.copy()
    environment.update(
        {
            "FAKE_OPEN_CLAUDE_DESIGN": str(fake_cli),
            "HOME": str(home),
            "NO_COLOR": "1",
            "OPEN_CLAUDE_DESIGN_PACKAGE": str(fake_wheel),
            "OPEN_CLAUDE_DESIGN_SKIP_LOGIN": "1",
            "PATH": f"{fake_bin}:/usr/bin:/bin",
            "UV_CONFIG_FILE": str(tmp_path / "untrusted-uv.toml"),
            "UV_DEFAULT_INDEX": "https://packages.invalid/simple",
            "UV_INDEX": "https://extra-packages.invalid/simple",
            "UV_TRACE": str(uv_trace),
        }
    )

    install = subprocess.run(
        ["sh"],
        input=(ROOT / "install.sh").read_text(encoding="utf-8"),
        text=True,
        capture_output=True,
        check=True,
        env=environment,
    )
    assert "[5/5] Connecting Claude Design" in install.stdout
    assert "Open Claude Design is ready" in install.stdout
    trace = uv_trace.read_text(encoding="utf-8")
    assert "--no-config --default-index https://pypi.org/simple --no-sources" in trace
    assert "UV_NO_CONFIG=1" in trace
    assert "UV_DEFAULT_INDEX=https://pypi.org/simple" in trace
    assert "UV_CONFIG_FILE=" not in trace
    assert "UV_INDEX=" not in trace

    uninstall = subprocess.run(
        ["sh", "-s", "--", "--yes"],
        input=(ROOT / "uninstall.sh").read_text(encoding="utf-8"),
        text=True,
        capture_output=True,
        check=True,
        env=environment,
    )
    assert "[3/3] Removing owned runtime data" in uninstall.stdout
    assert "Open Claude Design was removed" in uninstall.stdout
