"""VS Code local-installer runner and public shell-script contracts."""

from __future__ import annotations

import hashlib
import os
import re
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from scripts.run_local_installer import find_release_wheel, run_local_installer

pytestmark = pytest.mark.integration
ROOT = Path(__file__).parents[1]


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)


def _fake_cli_script(trace: Path | None = None) -> str:
    record = f'printf \'%s\\n\' "$*" >> "{trace}"\n' if trace is not None else ""
    return (
        "#!/bin/sh\n"
        f"{record}"
        'case "${1:-}" in\n'
        "  --version) printf '1.0.0\\n' ;;\n"
        '  install) cat > /dev/null; printf \'{"action": "install", "verified": true}\\n\' ;;\n'
        "  uninstall) cat > /dev/null; printf '{}\\n' ;;\n"
        "  status) exit 1 ;;\n"
        "  *) exit 0 ;;\n"
        "esac\n"
    )


def _pipe_environment(tmp_path: Path) -> dict[str, str]:
    """Fake uv/node/npx toolchain for streamed install.sh / uninstall.sh runs."""
    home = tmp_path / "home"
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir(exist_ok=True)
    fake_cli = tmp_path / "open-claude-design"
    fake_wheel = tmp_path / "open_claude_design-1.0.0-py3-none-any.whl"
    fake_wheel.touch()
    fake_archive = tmp_path / "open-claude-design.tar.gz"
    fake_archive.write_bytes(b"synthetic release archive")
    fake_manifest = tmp_path / "SHA256SUMS"
    fake_manifest.write_text(
        f"{hashlib.sha256(fake_archive.read_bytes()).hexdigest()}  {fake_archive.name}\n"
        f"{hashlib.sha256(fake_wheel.read_bytes()).hexdigest()}  {fake_wheel.name}\n",
        encoding="utf-8",
    )

    _write_executable(fake_cli, _fake_cli_script())
    _write_executable(
        fake_bin / "uv",
        """#!/bin/sh
if [ "${1:-}" = "--version" ]; then
  printf 'uv 0.12.7\\n'
elif [ "${1:-}" = "tool" ] && [ "${2:-}" = "install" ] && [ "${3:-}" = "--help" ]; then
  cat > /dev/null
  printf '%s\\n' '--default-index' '--no-sources'
elif [ "${1:-}" = "tool" ] && [ "${2:-}" = "dir" ] && [ "${3:-}" = "--bin" ]; then
  cat > /dev/null
  if [ -n "${FORCE_COLOR:-}" ] && [ -z "${NO_COLOR:-}" ]; then
    printf '\\033[36m%s\\033[39m\\n' "${UV_TOOL_BIN_DIR:-$HOME/.local/bin}"
  else
    printf '%s\\n' "${UV_TOOL_BIN_DIR:-$HOME/.local/bin}"
  fi
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
    _write_executable(
        fake_bin / "curl",
        """#!/bin/sh
url=""
output=""
while [ "$#" -gt 0 ]; do
  case "$1" in
    -o) shift; output="$1" ;;
    http://*|https://*) url="$1" ;;
  esac
  shift
done
case "$url" in
  */SHA256SUMS) cp "$FAKE_RELEASE_MANIFEST" "$output" ;;
  */open-claude-design.tar.gz) cp "$FAKE_RELEASE_ARCHIVE" "$output" ;;
  */open_claude_design-*-py3-none-any.whl) cp "$FAKE_RELEASE_WHEEL" "$output" ;;
  *) exit 22 ;;
esac
""",
    )

    environment = os.environ.copy()
    environment.update(
        {
            "FAKE_OPEN_CLAUDE_DESIGN": str(fake_cli),
            "FAKE_RELEASE_ARCHIVE": str(fake_archive),
            "FAKE_RELEASE_MANIFEST": str(fake_manifest),
            "FAKE_RELEASE_WHEEL": str(fake_wheel),
            "HOME": str(home),
            "NO_COLOR": "1",
            "OPEN_CLAUDE_DESIGN_PACKAGE": str(fake_wheel),
            "OPEN_CLAUDE_DESIGN_SKIP_LOGIN": "1",
            "PATH": f"{fake_bin}:/usr/bin:/bin",
            "UV_CONFIG_FILE": str(tmp_path / "untrusted-uv.toml"),
            "UV_DEFAULT_INDEX": "https://packages.invalid/simple",
            "UV_INDEX": "https://extra-packages.invalid/simple",
            "UV_TRACE": str(tmp_path / "uv-trace.txt"),
        }
    )
    return environment


def _run_script(name: str, environment: dict[str, str], *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["sh", "-s", "--", *arguments],
        input=(ROOT / name).read_text(encoding="utf-8"),
        text=True,
        capture_output=True,
        check=False,
        env=environment,
    )


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
    environment = _pipe_environment(tmp_path)

    install = _run_script("install.sh", environment)
    assert install.returncode == 0, install.stderr
    assert "[5/5] Connecting Claude Design" in install.stdout
    assert "Open Claude Design is ready" in install.stdout
    trace = Path(environment["UV_TRACE"]).read_text(encoding="utf-8")
    assert "--no-config --default-index https://pypi.org/simple --no-sources" in trace
    assert "UV_NO_CONFIG=1" in trace
    assert "UV_DEFAULT_INDEX=https://pypi.org/simple" in trace
    assert "UV_CONFIG_FILE=" not in trace
    assert "UV_INDEX=" not in trace

    uninstall = _run_script("uninstall.sh", environment, "--yes")
    assert uninstall.returncode == 0, uninstall.stderr
    assert "[3/3] Removing owned runtime data" in uninstall.stdout
    assert "Open Claude Design was removed" in uninstall.stdout


def test_public_install_records_stable_latest_archive_for_uv_upgrade(tmp_path: Path) -> None:
    environment = _pipe_environment(tmp_path)
    del environment["OPEN_CLAUDE_DESIGN_PACKAGE"]

    install = _run_script("install.sh", environment)

    assert install.returncode == 0, install.stderr + install.stdout
    trace = Path(environment["UV_TRACE"]).read_text(encoding="utf-8")
    install_args = next(line for line in trace.splitlines() if line.startswith("args="))
    assert (
        "https://github.com/maxritter/open-claude-design/releases/latest/download/open-claude-design.tar.gz"
        in install_args
    )
    assert ".whl" not in install_args


def test_local_package_install_persists_its_uv_requirement_source(tmp_path: Path) -> None:
    environment = _pipe_environment(tmp_path)
    manifest = Path(environment["FAKE_RELEASE_MANIFEST"])
    manifest.write_text(
        manifest.read_text(encoding="utf-8").replace(
            hashlib.sha256(Path(environment["FAKE_RELEASE_WHEEL"]).read_bytes()).hexdigest(),
            "f" * 64,
        ),
        encoding="utf-8",
    )

    install = _run_script("install.sh", environment)

    assert install.returncode == 0, install.stderr + install.stdout
    package = (
        Path(environment["HOME"])
        / ".local/share/open-claude-design/packages"
        / Path(environment["OPEN_CLAUDE_DESIGN_PACKAGE"]).name
    )
    assert package.is_file()
    trace = Path(environment["UV_TRACE"]).read_text(encoding="utf-8")
    assert str(package) in trace


def test_published_local_package_switches_to_the_upgradeable_latest_source(tmp_path: Path) -> None:
    environment = _pipe_environment(tmp_path)

    install = _run_script("install.sh", environment)

    assert install.returncode == 0, install.stderr + install.stdout
    trace = Path(environment["UV_TRACE"]).read_text(encoding="utf-8")
    install_args = next(line for line in trace.splitlines() if line.startswith("args="))
    assert (
        "https://github.com/maxritter/open-claude-design/releases/latest/download/open-claude-design.tar.gz"
        in install_args
    )
    assert "enabling uv upgrades" in install.stdout


def test_install_survives_forced_color_from_a_parent_process(tmp_path: Path) -> None:
    """uv run exports FORCE_COLOR, which wraps captured uv output in ANSI codes."""
    environment = _pipe_environment(tmp_path)
    del environment["NO_COLOR"]
    environment["FORCE_COLOR"] = "3"

    install = _run_script("install.sh", environment)
    assert install.returncode == 0, install.stderr + install.stdout
    assert "Open Claude Design is ready" in install.stdout


def test_install_warns_when_login_shell_path_misses_the_tool_bin(tmp_path: Path) -> None:
    environment = _pipe_environment(tmp_path)
    install = _run_script("install.sh", environment)
    assert install.returncode == 0, install.stderr
    tool_bin = f"{environment['HOME']}/.local/bin"
    assert f'export PATH="{tool_bin}:$PATH"' in install.stdout


def test_install_dry_run_reports_no_changes_instead_of_success(tmp_path: Path) -> None:
    environment = _pipe_environment(tmp_path)
    install = _run_script("install.sh", environment, "--dry-run")
    assert install.returncode == 0, install.stderr
    assert "Dry run: no agent files were changed" in install.stdout
    assert "Automatic design workflows installed" not in install.stdout


@pytest.mark.parametrize("flag", ["--help", "-h"])
def test_install_help_prints_usage_without_installing(tmp_path: Path, flag: str) -> None:
    environment = _pipe_environment(tmp_path)

    install = _run_script("install.sh", environment, flag)

    assert install.returncode == 0, install.stderr
    assert install.stdout.startswith("Usage: install.sh")
    assert "[1/5]" not in install.stdout
    assert not Path(environment["UV_TRACE"]).exists()
    assert not (Path(environment["HOME"]) / ".local").exists()


def test_install_refuses_success_when_agent_install_returns_no_result(tmp_path: Path) -> None:
    """A zero exit that installed nothing (e.g. help text) must not read as a verified install."""
    environment = _pipe_environment(tmp_path)
    _write_executable(
        Path(environment["FAKE_OPEN_CLAUDE_DESIGN"]),
        "#!/bin/sh\n"
        'case "${1:-}" in\n'
        "  --version) printf '1.0.0\\n' ;;\n"
        "  install) printf 'usage: open-claude-design install [-h]\\n' ;;\n"
        "  *) exit 0 ;;\n"
        "esac\n",
    )

    install = _run_script("install.sh", environment)

    assert install.returncode == 1
    assert "returned no install result" in install.stderr
    assert "installed and verified" not in install.stdout
    assert "Open Claude Design is ready" not in install.stdout


def test_uninstall_scope_project_routes_scope_to_cli_without_npx_fallback(tmp_path: Path) -> None:
    environment = _pipe_environment(tmp_path)
    cli_trace = tmp_path / "cli-trace.txt"
    npx_trace = tmp_path / "npx-trace.txt"
    fake_bin = tmp_path / "bin"
    _write_executable(fake_bin / "open-claude-design", _fake_cli_script(cli_trace))
    _write_executable(fake_bin / "npx", f'#!/bin/sh\nprintf \'%s\\n\' "$*" >> "{npx_trace}"\nexit 0\n')

    uninstall = _run_script("uninstall.sh", environment, "--scope", "project", "--yes")
    assert uninstall.returncode == 0, uninstall.stderr
    assert "uninstall --scope project --yes" in cli_trace.read_text(encoding="utf-8")
    assert not npx_trace.exists()


@pytest.mark.parametrize(
    ("scope_arguments", "expects_global"),
    [((), True), (("--scope=project",), False)],
)
def test_uninstall_fallback_scopes_the_agent_skills_backend(
    tmp_path: Path,
    scope_arguments: tuple[str, ...],
    expects_global: bool,
) -> None:
    environment = _pipe_environment(tmp_path)
    npx_trace = tmp_path / "npx-trace.txt"
    fake_bin = tmp_path / "bin"
    _write_executable(fake_bin / "npx", f'#!/bin/sh\nprintf \'%s\\n\' "$*" >> "{npx_trace}"\nexit 0\n')

    uninstall = _run_script("uninstall.sh", environment, *scope_arguments, "--yes")
    assert uninstall.returncode == 0, uninstall.stderr
    recorded = npx_trace.read_text(encoding="utf-8")
    assert "skills@1.5.23 remove" in recorded
    assert ("--global" in recorded) is expects_global


def test_uninstall_reports_unconfirmed_removal_when_every_backend_fails(tmp_path: Path) -> None:
    environment = _pipe_environment(tmp_path)
    fake_bin = tmp_path / "bin"
    _write_executable(fake_bin / "npx", "#!/bin/sh\nexit 1\n")

    uninstall = _run_script("uninstall.sh", environment, "--yes")
    assert uninstall.returncode == 0, uninstall.stderr
    assert "Could not confirm skill removal" in uninstall.stdout
    assert "Agent integrations are clean" not in uninstall.stdout


def test_release_manifest_archive_checksum_requires_the_exact_asset_name(tmp_path: Path) -> None:
    install_text = (ROOT / "install.sh").read_text(encoding="utf-8")
    match = re.search(r"""awk -v name="\$ARCHIVE_NAME" '([^']*)' """, install_text)
    assert match is not None, "archive checksum extraction line not found in install.sh"
    program = match.group(1)

    manifest = tmp_path / "SHA256SUMS"
    manifest.write_text(
        "0" * 64 + "  nested/open-claude-design.tar.gz\n" + "1" * 64 + "  open-claude-design.tar.gz\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        ["awk", "-v", "name=open-claude-design.tar.gz", program, str(manifest)],
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.strip() == "1" * 64
