#!/bin/sh
set -eu

shellcheck -s sh install.sh uninstall.sh scripts/check-shell.sh
shellcheck scripts/build-release.sh scripts/security-check.sh
shfmt -d -i 2 -ci -sr install.sh uninstall.sh scripts/check-shell.sh scripts/build-release.sh scripts/security-check.sh
checkbashisms -f install.sh uninstall.sh scripts/check-shell.sh
/bin/sh -n install.sh
/bin/sh -n uninstall.sh
/bin/sh -n scripts/check-shell.sh
bash -n scripts/build-release.sh
bash -n scripts/security-check.sh

if command -v dash > /dev/null 2>&1; then
  dash -n install.sh
  dash -n uninstall.sh
  dash -n scripts/check-shell.sh
elif [ -x /opt/homebrew/bin/dash ]; then
  /opt/homebrew/bin/dash -n install.sh
  /opt/homebrew/bin/dash -n uninstall.sh
  /opt/homebrew/bin/dash -n scripts/check-shell.sh
else
  echo "dash is required for the POSIX shell compatibility gate" >&2
  exit 1
fi

if command -v shellharden > /dev/null 2>&1; then
  shellharden --check install.sh uninstall.sh scripts/check-shell.sh
fi
