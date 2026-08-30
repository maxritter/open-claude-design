# Open Claude Design repository instructions

## Project

Open Claude Design is a free, source-available design layer for coding agents. `skills/` is the portable source of truth. `src/open_claude_design/` contains the cross-platform Python CLI, authenticated Claude Design client, central configuration, and pinned Vercel skills adapter.

## Commands

- `uv sync --all-groups` — install the Python development environment.
- `uv run ruff check .` — lint Python sources and tests.
- `uv run basedpyright` — type-check the package with the repository configuration.
- `uv run pytest -q` — run the isolated CLI, installer, credential, and bridge tests.
- `uv run python scripts/validate_skills.py` — validate every canonical skill and implicit-invocation manifest.
- `sh scripts/check-shell.sh` — verify both public scripts with ShellCheck, shfmt, checkbashisms, dash, and `/bin/sh`.
- `bash scripts/security-check.sh` — run the local Trivy vulnerability, secret, and misconfiguration gate when Trivy is installed.
- `uv run pre-commit run --all-files` — run the local commit-equivalent formatting, validation, and security hooks.
- `bash scripts/build-release.sh` — build the local wheel, fixed-name release archive, and SHA-256 manifest.

## Repository rules

- Keep each skill portable and Agent Skills compliant. Agent-specific paths and detection belong to the pinned Vercel skills CLI, not this repository.
- Preserve progressive disclosure: `SKILL.md` routes; references hold mode-specific detail.
- Never print, persist, or reconstruct Claude Design credentials. The bridge remains read-only unless the current user explicitly authorizes a remote write.
- All agents receive the same five skills through one skills CLI mechanism; do not add a special installation path for one harness.
- Open Claude Design and Impeccable are complementary: this project owns product-design workflow and Claude Design access; Impeccable owns its named refinement workflows, detector, and hooks.
- Keep central package, bridge, platform, skill, runtime, and installer constants in `src/open_claude_design/config.py`.
- Before the first local commit, audit `.gitignore`, the complete candidate file list, generated artifacts, private paths, and secrets. Do not create a public commit, GitHub remote, push, tag, GitHub Release, npm publication, or PyPI publication without Max Ritter's explicit approval.

## Release boundary

The repository can be built and packed locally. External publication is a separate, approval-gated step.
