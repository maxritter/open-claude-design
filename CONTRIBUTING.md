# Contributing

Open issues before large changes. Keep skills portable, descriptions discriminating, references progressively disclosed, and provider-specific behavior in the installer or provider metadata.

Install the local commit and push gates once:

```bash
uv sync --all-groups
uv run pre-commit install --hook-type pre-commit --hook-type pre-push
```

Run before submitting a change:

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

Exercise the changed CLI, installer, synchronization, or agent workflow through the built artifact when behavior changed. Keep pull requests focused, update affected documentation, and use the repository pull-request template.

Never include Claude Design credentials, plan tokens, short-lived preview URLs, private project content, or machine-local paths in an issue, test fixture, commit, or pull request.

By submitting a contribution, you grant Max Ritter a perpetual, worldwide, irrevocable, royalty-free right to use, modify, distribute, sublicense, and relicense the contribution as part of Open Claude Design. Third-party material must retain its original license and attribution.

Use conventional commits (`feat:`, `fix:`, `docs:`, `refactor:`, `test:`, `build:`, `ci:`). Releases are manual: a maintainer bumps the version in `pyproject.toml` and `src/open_claude_design/config.py`, updates `CHANGELOG.md`, and dispatches the `Manual Release` workflow, which rebuilds, re-verifies, attests provenance, and publishes the GitHub Release. The `release` environment must approve publication after all test and security gates pass.
