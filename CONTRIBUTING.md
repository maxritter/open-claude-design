# Contributing

Open an issue before starting large changes. Keep skills portable, descriptions concise, references progressively disclosed, and agent-specific installation behavior inside the pinned Vercel `skills` CLI.

Install the local commit hooks once:

```bash
uv sync --all-groups
uv run pre-commit install --hook-type pre-commit --hook-type pre-push
```

Run the full check suite before opening a pull request:

```bash
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
uv run basedpyright
uv run python scripts/validate_skills.py
sh scripts/check-shell.sh
bash scripts/build-release.sh
bash scripts/security-check.sh
```

Never commit credentials, capability tokens, private artifact content, or machine-local paths in issues, fixtures, commits, or pull requests.

By submitting a contribution, you grant Max Ritter a perpetual, worldwide, irrevocable, royalty-free right to use, modify, distribute, sublicense, and relicense the contribution as part of Open Claude Artifacts. Third-party material keeps its original license and attribution.

Use conventional commits (`feat:`, `fix:`, `docs:`, `refactor:`, `test:`, `build:`, `ci:`). Releases run via the `Manual Release` workflow after bumping `pyproject.toml`, `src/open_claude_artifacts/config.py`, `uv.lock` (`uv lock`), and `CHANGELOG.md`.
