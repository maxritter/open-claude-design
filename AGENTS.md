# Open Claude Artifacts repository instructions

## Project

Open Claude Artifacts is a free, source-available Claude Artifacts CLI and portable Agent Skills package for coding agents. `skills/` is the portable source of truth. `src/open_claude_artifacts/` contains the cross-platform Python CLI, authenticated Claude Artifacts client, local headless renderer (Design artboards, Slides decks, and plain pages), central configuration, and pinned Vercel skills adapter.

## Commands

- `uv sync --all-groups` — install the Python development environment.
- `uv run ruff check .` — lint Python sources and tests.
- `uv run ruff format --check .` — verify formatting; CI gates on it.
- `uv run basedpyright` — type-check the package with the repository configuration.
- `uv run pytest -q` — run the isolated CLI, installer, credential, API, renderer, and sync tests.
- `uv run python scripts/validate_skills.py` — validate every canonical skill and implicit-invocation manifest.
- `sh scripts/check-shell.sh` — verify both public scripts with ShellCheck, shfmt, checkbashisms, dash, and `/bin/sh`.
- `bash scripts/security-check.sh` — run the local Trivy vulnerability, secret, and misconfiguration gate when Trivy is installed.
- `uv run pre-commit run --all-files` — run the local commit-equivalent formatting, validation, and security hooks.
- `bash scripts/build-release.sh` — build the local wheel, fixed-name release archive, and SHA-256 manifest.

## Repository rules

- Keep each skill portable and Agent Skills compliant. Agent-specific paths and detection belong to the pinned Vercel skills CLI, not this repository.
- Preserve progressive disclosure: `SKILL.md` routes; references hold mode-specific detail.
- Never print, persist, or reconstruct credentials or capability URLs. Writes require explicit `--allow-write` (and `--allow-destructive` / `--allow-public` where applicable).
- All agents receive the same five skills through one skills CLI mechanism; do not add a special installation path for one harness.
- Keep central package, artifact, platform, skill, runtime, and installer constants in `src/open_claude_artifacts/config.py`.
