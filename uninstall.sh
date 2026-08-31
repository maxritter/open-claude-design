#!/bin/sh
set -eu

PACKAGE_NAME="open-claude-design"
RUNTIME_ROOT="$HOME/.local/share/open-claude-design"
MANAGED_UV="$RUNTIME_ROOT/uv/bin/uv"
MANAGED_NPX="$RUNTIME_ROOT/node/bin/npx"

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

step() {
  line "${CORAL}${BOLD}[$1/3]${RESET} ${BOLD}$2${RESET}"
}

success() {
  line "  ${GREEN}✓${RESET} $*"
}

info() {
  line "  ${MUTED}·${RESET} $*"
}

fail() {
  line "${CORAL}Open Claude Design:${RESET} $*" >&2
  exit 1
}

case "${HOME:-}" in
  /*) ;;
  *) fail "HOME must be an absolute user directory" ;;
esac
case "$RUNTIME_ROOT" in
  "$HOME/.local/share/open-claude-design") ;;
  *) fail "refusing unexpected runtime directory" ;;
esac

confirmed=0
SCOPE="global"
while [ "$#" -gt 0 ]; do
  case "$1" in
    --yes | -y) confirmed=1 ;;
    --scope)
      [ "$#" -ge 2 ] || fail "--scope requires a value: global or project"
      SCOPE="$2"
      shift
      ;;
    --scope=*) SCOPE="${1#--scope=}" ;;
    *) fail "unknown option: $1 (supported: --yes, --scope global|project)" ;;
  esac
  shift
done
case "$SCOPE" in
  global | project) ;;
  *) fail "scope must be global or project" ;;
esac

line ""
line "${CYAN}╭──────────────────────────────────────────────────────────╮${RESET}"
line "${CYAN}│${RESET}  ${BOLD}Uninstall Open Claude Design${RESET}                            ${CYAN}│${RESET}"
line "${CYAN}╰──────────────────────────────────────────────────────────╯${RESET}"
line ""

if [ "$confirmed" -ne 1 ]; then
  if [ ! -r /dev/tty ]; then
    fail "rerun with --yes when no terminal is available"
  fi
  printf 'Remove Open Claude Design, its five skills, and managed runtimes? [y/N] ' > /dev/tty
  read -r answer < /dev/tty
  case "$answer" in
    y | Y | yes | YES) ;;
    *)
      line "Nothing removed."
      exit 0
      ;;
  esac
fi

step 1 "Removing agent integrations"
cli_skills_removed=0
if command -v open-claude-design > /dev/null 2>&1; then
  if open-claude-design uninstall --scope "$SCOPE" --yes < /dev/null > /dev/null 2>&1; then
    cli_skills_removed=1
    success "Five Open Claude Design skills removed ($SCOPE scope)"
  else
    info "The CLI could not remove every skill; trying the Agent Skills backend"
  fi
  open-claude-design logout --yes < /dev/null > /dev/null 2>&1 || true
fi

fallback_skills_removed=0
if [ "$cli_skills_removed" -ne 1 ]; then
  if [ "$SCOPE" = "global" ]; then
    set -- --global --yes
  else
    set -- --yes
  fi
  if command -v npx > /dev/null 2>&1; then
    if npx --yes skills@1.5.23 remove \
      open-claude-design \
      open-claude-design-quality \
      open-claude-design-system \
      open-claude-ui-design \
      open-claude-ui-review \
      "$@" < /dev/null > /dev/null 2>&1; then
      fallback_skills_removed=1
    fi
  elif [ -x "$MANAGED_NPX" ]; then
    PATH="$(dirname "$MANAGED_NPX"):$PATH"
    export PATH
    if "$MANAGED_NPX" --yes skills@1.5.23 remove \
      open-claude-design \
      open-claude-design-quality \
      open-claude-design-system \
      open-claude-ui-design \
      open-claude-ui-review \
      "$@" < /dev/null > /dev/null 2>&1; then
      fallback_skills_removed=1
    fi
  fi
fi
if [ "$cli_skills_removed" -eq 1 ] || [ "$fallback_skills_removed" -eq 1 ]; then
  success "Agent integrations are clean"
else
  info "Could not confirm skill removal for the $SCOPE scope"
  info "Re-run this uninstaller once open-claude-design or npx can reach the Agent Skills backend"
fi

step 2 "Removing the CLI"
uv_bin_dir=""
if command -v uv > /dev/null 2>&1; then
  uv tool uninstall "$PACKAGE_NAME" < /dev/null > /dev/null 2>&1 || true
  uv_bin_dir="$(NO_COLOR=1 uv tool dir --bin < /dev/null 2> /dev/null || true)"
elif [ -x "$MANAGED_UV" ]; then
  "$MANAGED_UV" tool uninstall "$PACKAGE_NAME" < /dev/null > /dev/null 2>&1 || true
  uv_bin_dir="$(NO_COLOR=1 "$MANAGED_UV" tool dir --bin < /dev/null 2> /dev/null || true)"
fi
case "$uv_bin_dir" in
  /*) rm -f "$uv_bin_dir/open-claude-design" ;;
esac
rm -f "$HOME/.local/bin/open-claude-design"
if command -v open-claude-design > /dev/null 2>&1; then
  info "An open-claude-design executable remains at $(command -v open-claude-design); remove it manually"
else
  success "CLI removed"
fi

step 3 "Removing owned runtime data"
case "$(uname -s)" in
  Darwin)
    /usr/bin/security delete-generic-password \
      -a open-claude-design \
      -s "Open Claude Design-credentials" > /dev/null 2>&1 || true
    ;;
esac
# The refresh lock directory is created on every platform, so clean it everywhere.
rm -f "$HOME/.config/open-claude-design/credentials.json"
rm -f "$HOME/.config/open-claude-design/.refresh.lock"
rmdir "$HOME/.config/open-claude-design" > /dev/null 2>&1 || true
rm -rf "$RUNTIME_ROOT"
success "Managed uv, Node.js, and credential data removed"

line ""
line "${GREEN}${BOLD}Open Claude Design was removed.${RESET}"
line "${MUTED}Your Claude Design projects and coding-agent configuration outside this package were not changed.${RESET}"
line ""
