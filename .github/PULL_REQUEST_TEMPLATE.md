## Summary

<!-- What changes, and which user problem does it solve? -->

## Verification

<!-- List the exact checks and real workflows you ran. -->

- [ ] `uv run pytest -q`
- [ ] `uv run ruff check .`
- [ ] `uv run basedpyright`
- [ ] `uv run python scripts/validate_skills.py`
- [ ] Installed-artifact or runtime behavior was exercised when relevant

## Scope and safety

- [ ] The change is focused and includes affected documentation.
- [ ] Agent skills remain portable and implicitly invokable.
- [ ] No credentials, plan tokens, private project content, or short-lived preview URLs are included.
- [ ] Remote mutation behavior remains explicit, conflict-aware, and verified.
