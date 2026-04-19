## Summary

<!-- What changed and why. 1-3 sentences. -->

## Related issues

<!-- Closes #123, relates to #456 -->

## Type of change

- [ ] Bug fix
- [ ] New feature
- [ ] Contract / config schema change (breaking)
- [ ] New venue config
- [ ] Tooling / CI / docs
- [ ] Refactor (no behavior change)

## Checklist

- [ ] `uv run pytest -q` passes locally
- [ ] New code has tests covering happy path + at least one failure mode
- [ ] `uv run ruff check .` clean
- [ ] `uv run ruff format --check .` clean
- [ ] `uv run pyright` clean
- [ ] If a contract (`contracts.py`) or config schema changed: callers updated and version bumped in `pyproject.toml`
- [ ] `CHANGELOG.md` updated under `## [Unreleased]`
- [ ] README / docstrings updated if user-facing behavior changed

## Test plan

<!-- How did you verify this works? Paste command output, screenshots, or sample report snippets. -->
