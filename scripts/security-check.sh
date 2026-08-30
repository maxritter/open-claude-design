#!/usr/bin/env bash
set -euo pipefail

if ! command -v trivy >/dev/null 2>&1; then
  echo "Trivy is not installed; skipping the local scan. CI remains the security gate."
  echo "Install locally with: brew install trivy"
  exit 0
fi

trivy fs . \
  --scanners vuln,secret,misconfig \
  --severity CRITICAL,HIGH \
  --exit-code 1 \
  --ignore-unfixed \
  --skip-dirs .git,.venv,dist \
  --ignorefile .trivyignore \
  --quiet
