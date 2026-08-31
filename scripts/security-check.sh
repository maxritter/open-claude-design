#!/usr/bin/env bash
set -euo pipefail

if ! command -v trivy > /dev/null 2>&1; then
  echo "WARNING: Trivy is not installed, so the local security scan DID NOT RUN." >&2
  echo "WARNING: CI remains the security gate. Install locally with: brew install trivy" >&2
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
