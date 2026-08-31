#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DIST="$ROOT/dist"
ARCHIVE="$DIST/open-claude-design.tar.gz"

mkdir -p "$DIST"
rm -f "$DIST"/*.tar.gz "$DIST"/*.whl "$DIST/install.sh" "$DIST/uninstall.sh" "$DIST/SHA256SUMS"

cd "$ROOT"
UV_NO_CONFIG=1 UV_DEFAULT_INDEX=https://pypi.org/simple uv build --sdist --wheel --out-dir "$DIST"

SDIST="$(find "$DIST" -maxdepth 1 -name 'open_claude_design-*.tar.gz' -print -quit)"
[[ -n "$SDIST" ]] || {
  echo "release sdist was not created" >&2
  exit 1
}
cp "$SDIST" "$ARCHIVE"
cp "$ROOT/install.sh" "$DIST/install.sh"
cp "$ROOT/uninstall.sh" "$DIST/uninstall.sh"
chmod 0755 "$DIST/install.sh" "$DIST/uninstall.sh"

cd "$DIST"
if command -v sha256sum > /dev/null 2>&1; then
  sha256sum install.sh uninstall.sh "$(basename "$ARCHIVE")" open_claude_design-*.whl > SHA256SUMS
else
  shasum -a 256 install.sh uninstall.sh "$(basename "$ARCHIVE")" open_claude_design-*.whl > SHA256SUMS
fi

echo "$ARCHIVE"
echo "$DIST/SHA256SUMS"
