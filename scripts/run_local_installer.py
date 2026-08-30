"""Run the built release installer without inheriting VS Code's Node debugger."""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def find_release_wheel(dist: Path) -> Path:
    """Return the single wheel produced by the release build."""
    wheels = sorted(dist.glob("open_claude_design-*-py3-none-any.whl"))
    if len(wheels) != 1:
        raise RuntimeError(f"expected exactly one local release wheel in {dist}, found {len(wheels)}")
    return wheels[0]


def run_local_installer(root: Path, arguments: Sequence[str] = ()) -> None:
    """Install the built wheel through the exact release installer asset."""
    dist = root / "dist"
    installer = dist / "install.sh"
    if not installer.is_file():
        raise RuntimeError(f"local installer asset is missing: {installer}")

    environment = os.environ.copy()
    environment.pop("NODE_OPTIONS", None)
    environment.pop("VSCODE_INSPECTOR_OPTIONS", None)
    environment["OPEN_CLAUDE_DESIGN_PACKAGE"] = str(find_release_wheel(dist))
    subprocess.run(
        ["sh", str(installer), *arguments],
        cwd=root,
        env=environment,
        check=True,
    )


def main(arguments: Sequence[str] | None = None) -> int:
    """Run the local installer from VS Code or a terminal."""
    run_local_installer(ROOT, tuple(sys.argv[1:] if arguments is None else arguments))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
