#!/bin/sh
set -eu

REPOSITORY="maxritter/open-claude-design"
CHECKSUM_NAME="SHA256SUMS"
REQUESTED_VERSION="${VERSION:-}"
INSTALL_SOURCE="${OPEN_CLAUDE_DESIGN_PACKAGE:-${OPEN_CLAUDE_DESIGN_ARCHIVE:-}}"
SKILLS_NODE_VERSION="22.20.0"
SKILLS_NODE_ROOT="$HOME/.local/share/open-claude-design/node"
UV_VERSION="0.12.7"
UV_ROOT="$HOME/.local/share/open-claude-design/uv"
RULE="────────────────────────────────────────────────────────────"

# The CLI is installed into uv's isolated tools directory. Ignore ambient
# project/user configuration and private indexes so bootstrap resolution cannot
# touch a project virtualenv or inherit unrelated package credentials.
unset UV_INDEX UV_INDEX_URL UV_EXTRA_INDEX_URL UV_FIND_LINKS UV_CONFIG_FILE UV_KEYRING_PROVIDER
UV_NO_CONFIG=1
UV_DEFAULT_INDEX="https://pypi.org/simple"
export UV_NO_CONFIG UV_DEFAULT_INDEX
ORIGINAL_PATH="${PATH:-}"

if [ -t 1 ] && [ "${NO_COLOR:-}" = "" ]; then
  CYAN='\033[38;5;44m'
  CORAL='\033[38;5;203m'
  GREEN='\033[38;5;42m'
  MUTED='\033[38;5;245m'
  BOLD='\033[1m'
  RESET='\033[0m'
else
  CYAN=''
  CORAL=''
  GREEN=''
  MUTED=''
  BOLD=''
  RESET=''
fi

line() {
  printf '%b\n' "$*"
}

banner() {
  terminal_columns="${COLUMNS:-0}"
  case "$terminal_columns" in
    '' | *[!0-9]*) terminal_columns=0 ;;
  esac
  if [ "$terminal_columns" -eq 0 ] && command -v tput > /dev/null 2>&1; then
    terminal_columns="$(tput cols 2> /dev/null || printf '0')"
    case "$terminal_columns" in
      '' | *[!0-9]*) terminal_columns=0 ;;
    esac
  fi

  line ""
  if [ "$terminal_columns" -ge 92 ]; then
    printf '%b' "${CYAN}${BOLD}"
    # shellcheck disable=SC2016
    printf '%s\n' \
      '  ___  ___ ___ _  _    ___ _      _  _   _ ___  ___   ___  ___ ___ ___ ___ _  _ ' \
      ' / _ \| _ \ __| \| |  / __| |    /_\| | | |   \| __| |   \| __/ __|_ _/ __| \| |' \
      '| (_) |  _/ _|| .` | | (__| |__ / _ \ |_| | |) | _|  | |) | _|\__ \| | (_ | .` |' \
      ' \___/|_| |___|_|\_|  \___|____/_/ \_\___/|___/|___| |___/|___|___/___\___|_|\_|'
    printf '%b' "$RESET"
  else
    line "  ${CYAN}${BOLD}< OPEN CLAUDE DESIGN >${RESET}"
  fi
  line ""
  line "  ${CORAL}>${RESET} ${BOLD}Design intelligence for coding agents${RESET}"
  line "    ${MUTED}Claude Design's visual workflow, inside the agent you already use.${RESET}"
  line ""
}

step() {
  line "${MUTED}${RULE}${RESET}"
  line "${CORAL}${BOLD}[$1/5]${RESET} ${BOLD}$2${RESET}"
}

info() {
  line "  ${MUTED}·${RESET} $*"
}

success() {
  line "  ${GREEN}✓${RESET} $*"
}

fail() {
  line "${CORAL}Open Claude Design:${RESET} $*" >&2
  exit 1
}

is_sha256() {
  [ "${#1}" -eq 64 ] || return 1
  case "$1" in
    *[!0-9a-fA-F]*) return 1 ;;
    *) return 0 ;;
  esac
}

sha256_file() {
  if command -v sha256sum > /dev/null 2>&1; then
    sha256sum "$1" | awk '{print $1}'
  else
    shasum -a 256 "$1" | awk '{print $1}'
  fi
}

case "${HOME:-}" in
  /*) ;;
  *) fail "HOME must be an absolute user directory" ;;
esac

case "$(uname -s)" in
  Darwin | Linux) ;;
  *) fail "supported platforms are macOS, Linux, and WSL2" ;;
esac

banner
step 1 "Checking this machine"
command -v curl > /dev/null 2>&1 || fail "curl is required"
command -v tar > /dev/null 2>&1 || fail "tar is required"
success "$(uname -s) $(uname -m) is supported"

STAGING_DIR="$(mktemp -d)"
cleanup() {
  rm -rf "$STAGING_DIR"
}
trap cleanup 0
trap 'cleanup; exit 1' HUP INT TERM

step 2 "Preparing private runtimes"
uv_is_compatible() {
  command -v uv > /dev/null 2>&1 &&
    uv tool install --help < /dev/null 2> /dev/null | grep -q -- '--default-index' &&
    uv tool install --help < /dev/null 2> /dev/null | grep -q -- '--no-sources' &&
    uv tool dir --bin < /dev/null > /dev/null 2>&1
}

if ! uv_is_compatible; then
  case "$(uname -s):$(uname -m)" in
    Darwin:arm64) uv_target="aarch64-apple-darwin" ;;
    Darwin:x86_64) uv_target="x86_64-apple-darwin" ;;
    Linux:arm64 | Linux:aarch64)
      if command -v ldd > /dev/null 2>&1 && ldd --version 2>&1 | grep -qi musl; then
        uv_target="aarch64-unknown-linux-musl"
      else
        uv_target="aarch64-unknown-linux-gnu"
      fi
      ;;
    Linux:x86_64 | Linux:amd64)
      if command -v ldd > /dev/null 2>&1 && ldd --version 2>&1 | grep -qi musl; then
        uv_target="x86_64-unknown-linux-musl"
      else
        uv_target="x86_64-unknown-linux-gnu"
      fi
      ;;
    *) fail "unsupported platform for managed uv: $(uname -s) $(uname -m)" ;;
  esac
  uv_archive="uv-${uv_target}.tar.gz"
  uv_base="https://github.com/astral-sh/uv/releases/download/${UV_VERSION}"
  info "Installing checksummed uv $UV_VERSION"
  curl -fsSL "$uv_base/$uv_archive" -o "$STAGING_DIR/$uv_archive"
  curl -fsSL "$uv_base/$uv_archive.sha256" -o "$STAGING_DIR/$uv_archive.sha256"
  uv_expected="$(awk '{print $1; exit}' "$STAGING_DIR/$uv_archive.sha256")"
  is_sha256 "$uv_expected" || fail "uv checksum is missing or malformed"
  uv_actual="$(sha256_file "$STAGING_DIR/$uv_archive")"
  [ "$uv_actual" = "$uv_expected" ] || fail "uv archive checksum mismatch"
  mkdir -p "$STAGING_DIR/uv-extracted"
  tar -xzf "$STAGING_DIR/$uv_archive" -C "$STAGING_DIR/uv-extracted"
  uv_binary="$(find "$STAGING_DIR/uv-extracted" -type f -name uv -print -quit)"
  uvx_binary="$(find "$STAGING_DIR/uv-extracted" -type f -name uvx -print -quit)"
  if [ "$uv_binary" = "" ] || [ ! -x "$uv_binary" ]; then
    fail "uv archive is incomplete"
  fi
  case "$UV_ROOT" in
    "$HOME/.local/share/open-claude-design/uv") ;;
    *) fail "refusing unexpected managed uv destination" ;;
  esac
  rm -rf "$UV_ROOT"
  mkdir -p "$UV_ROOT/bin"
  cp "$uv_binary" "$UV_ROOT/bin/uv"
  chmod 0755 "$UV_ROOT/bin/uv"
  if [ "$uvx_binary" != "" ] && [ -x "$uvx_binary" ]; then
    cp "$uvx_binary" "$UV_ROOT/bin/uvx"
    chmod 0755 "$UV_ROOT/bin/uvx"
  fi
  PATH="$UV_ROOT/bin:$PATH"
  export PATH
else
  success "Using uv $(uv --version | awk '{print $2}')"
fi

uv_is_compatible || fail "compatible uv setup did not complete"

node_is_compatible() {
  command -v node > /dev/null 2>&1 &&
    command -v npx > /dev/null 2>&1 &&
    node -e 'const [major, minor] = process.versions.node.split(".").map(Number); process.exit(major > 22 || (major === 22 && minor >= 20) ? 0 : 1)' < /dev/null
}

if ! node_is_compatible && [ -x "$SKILLS_NODE_ROOT/bin/node" ] && [ -x "$SKILLS_NODE_ROOT/bin/npx" ]; then
  PATH="$SKILLS_NODE_ROOT/bin:$PATH"
  export PATH
fi

if ! node_is_compatible; then
  case "$(uname -s)" in
    Darwin) node_platform="darwin" ;;
    Linux) node_platform="linux" ;;
    *) fail "managed Node.js supports macOS, Linux, and WSL2" ;;
  esac
  case "$(uname -m)" in
    arm64 | aarch64) node_arch="arm64" ;;
    x86_64 | amd64) node_arch="x64" ;;
    *) fail "unsupported CPU architecture for managed Node.js: $(uname -m)" ;;
  esac

  node_archive="node-v${SKILLS_NODE_VERSION}-${node_platform}-${node_arch}.tar.gz"
  node_base="https://nodejs.org/dist/v${SKILLS_NODE_VERSION}"
  info "Installing private Node.js $SKILLS_NODE_VERSION for Agent Skills"
  curl -fsSL "$node_base/SHASUMS256.txt" -o "$STAGING_DIR/node-SHASUMS256.txt"
  curl -fsSL "$node_base/$node_archive" -o "$STAGING_DIR/$node_archive"
  node_expected="$(awk -v name="$node_archive" '$2 == name {print $1}' "$STAGING_DIR/node-SHASUMS256.txt")"
  is_sha256 "$node_expected" || fail "Node.js checksum is missing or malformed"
  node_actual="$(sha256_file "$STAGING_DIR/$node_archive")"
  [ "$node_actual" = "$node_expected" ] || fail "Node.js archive checksum mismatch"
  tar -xzf "$STAGING_DIR/$node_archive" -C "$STAGING_DIR"
  node_extracted="$STAGING_DIR/node-v${SKILLS_NODE_VERSION}-${node_platform}-${node_arch}"
  if [ ! -x "$node_extracted/bin/node" ] || [ ! -x "$node_extracted/bin/npx" ]; then
    fail "Node.js archive is incomplete"
  fi
  case "$SKILLS_NODE_ROOT" in
    "$HOME/.local/share/open-claude-design/node") ;;
    *) fail "refusing unexpected managed Node.js destination" ;;
  esac
  mkdir -p "$(dirname "$SKILLS_NODE_ROOT")"
  rm -rf "$SKILLS_NODE_ROOT"
  mv "$node_extracted" "$SKILLS_NODE_ROOT"
  PATH="$SKILLS_NODE_ROOT/bin:$PATH"
  export PATH
else
  success "Using Node.js $(node --version)"
fi

node_is_compatible || fail "compatible Node.js and npx setup did not complete"

step 3 "Installing the CLI"
if [ "$INSTALL_SOURCE" != "" ]; then
  PACKAGE_NAME="$(basename "$INSTALL_SOURCE")"
  cp "$INSTALL_SOURCE" "$STAGING_DIR/$PACKAGE_NAME"
else
  if [ "$REQUESTED_VERSION" != "" ]; then
    RELEASE_BASE="https://github.com/$REPOSITORY/releases/download/v$REQUESTED_VERSION"
    info "Downloading Open Claude Design v$REQUESTED_VERSION"
  else
    RELEASE_BASE="https://github.com/$REPOSITORY/releases/latest/download"
    info "Downloading the latest Open Claude Design release"
  fi
  curl -fsSL "$RELEASE_BASE/$CHECKSUM_NAME" -o "$STAGING_DIR/$CHECKSUM_NAME"
  PACKAGE_NAME="$(awk '$2 ~ /^open_claude_design-[^\/]*-py3-none-any\.whl$/ {print $2; exit}' "$STAGING_DIR/$CHECKSUM_NAME")"
  [ "$PACKAGE_NAME" != "" ] || fail "release wheel is missing from the checksum manifest"
  curl -fsSL "$RELEASE_BASE/$PACKAGE_NAME" -o "$STAGING_DIR/$PACKAGE_NAME"
  EXPECTED="$(awk -v name="$PACKAGE_NAME" '$2 == name {print $1}' "$STAGING_DIR/$CHECKSUM_NAME")"
  is_sha256 "$EXPECTED" || fail "release checksum is missing or malformed"
  ACTUAL="$(sha256_file "$STAGING_DIR/$PACKAGE_NAME")"
  [ "$ACTUAL" = "$EXPECTED" ] || fail "release wheel checksum mismatch"
fi

uv tool install --no-config --default-index "$UV_DEFAULT_INDEX" --no-sources --force --quiet \
  "$STAGING_DIR/$PACKAGE_NAME" < /dev/null
# NO_COLOR keeps the captured path free of ANSI codes when a parent process
# (uv run, some CI systems) exports FORCE_COLOR/CLICOLOR_FORCE.
UV_TOOL_BIN="$(NO_COLOR=1 uv tool dir --bin < /dev/null)"
case "$UV_TOOL_BIN" in
  /*) ;;
  *) fail "uv returned an invalid tool executable directory" ;;
esac
PATH="$UV_TOOL_BIN:$PATH"
export PATH
command -v open-claude-design > /dev/null 2>&1 || fail "installed CLI is not on PATH; add $UV_TOOL_BIN"
success "CLI $(open-claude-design --version) installed"
case ":$ORIGINAL_PATH:" in
  *":$UV_TOOL_BIN:"*) ;;
  *)
    info "New terminals need $UV_TOOL_BIN on PATH before open-claude-design resolves"
    info "Add to your shell profile: export PATH=\"$UV_TOOL_BIN:\$PATH\""
    ;;
esac

step 4 "Connecting your coding agents"
has_yes=0
dry_run=0
for argument; do
  case "$argument" in
    --yes | -y) has_yes=1 ;;
    --dry-run) dry_run=1 ;;
  esac
done
if [ "$has_yes" -eq 0 ]; then
  set -- "$@" --yes
fi
if ! open-claude-design install "$@" --json < /dev/null > "$STAGING_DIR/agent-install.json"; then
  cat "$STAGING_DIR/agent-install.json" >&2
  fail "coding-agent integration failed; remove the partial install with uninstall.sh"
fi
if [ "$dry_run" -eq 1 ]; then
  info "Dry run: no agent files were changed"
else
  success "Automatic design workflows installed"
fi

step 5 "Connecting Claude Design"
if open-claude-design status --json > /dev/null 2>&1; then
  success "Claude Design is already connected"
elif [ "${OPEN_CLAUDE_DESIGN_SKIP_LOGIN:-0}" = "1" ] || [ "${CI:-}" = "true" ]; then
  info "Login skipped for this non-interactive install"
  info "Run: open-claude-design login"
elif { : < /dev/tty; } 2> /dev/null; then
  if open-claude-design login < /dev/tty && open-claude-design status --json > /dev/null 2>&1; then
    success "Claude Design connected"
  else
    info "The CLI and agent workflows are installed"
    info "Finish later with: open-claude-design login"
    info "Claude Design currently requires Pro, Max, Team, or Enterprise access"
  fi
elif open-claude-design login < /dev/null && open-claude-design status --json > /dev/null 2>&1; then
  success "Claude Design connected"
else
  info "The CLI and agent workflows are installed"
  info "Finish later with: open-claude-design login"
  info "Claude Design currently requires Pro, Max, Team, or Enterprise access"
fi

line "${MUTED}${RULE}${RESET}"
line ""
line "  ${GREEN}${BOLD}✓ Open Claude Design is ready${RESET}"
line "    ${MUTED}Create, inspect, and sync without leaving your coding agent.${RESET}"
line ""
line "  ${BOLD}Try it${RESET}"
line "    Ask your agent: ${CYAN}Create a settings screen and open it in Claude Design.${RESET}"
line ""
line "  ${CORAL}${BOLD}★ Star Open Claude Design${RESET}"
line "    https://github.com/$REPOSITORY"
line ""
line "  ${CYAN}${BOLD}↗ Go further with Pilot Shell${RESET}"
line "    ${MUTED}Context and harness engineering for Claude Code and Codex${RESET}"
line "    https://github.com/maxritter/pilot-shell"
line ""
line "${MUTED}${RULE}${RESET}"
line ""
