# Contributing to evalit-4me

Thanks for considering a contribution. This is an academic-review tooling project and the bar for correctness is intentionally high — bug reports and test-first contributions are the most welcome.

## Project shape

- Python 3.11+, managed with [uv](https://docs.astral.sh/uv/).
- Contract-first architecture: every stage reads/writes Pydantic models in `src/evalit_4me/contracts.py`. `extra="forbid"` on those models — changes ripple.
- LLM access is provider-agnostic via `src/evalit_4me/llm/protocol.py`. New providers implement `complete()` + `embed()`.
- Venue-specific behavior lives in YAML configs under `configs/`, not in code.

## Dev setup

```bash
git clone https://github.com/niruta25/evalit-4me
cd evalit-4me
uv sync --all-extras
uv run pre-commit install         # enables ruff + pyright + pytest-fast on commit
```

Optional:

```bash
uv add marker-pdf                 # for real PDF parsing (~2 GB model weights)
export ANTHROPIC_API_KEY=sk-ant-  # for real LLM runs
```

## Running checks

The same commands CI runs:

```bash
uv run ruff check .              # linting
uv run ruff format --check .     # formatting
uv run pyright                   # type checking
uv run pytest -q                 # tests
uv run pytest --cov              # tests with coverage
```

One-liner before opening a PR:

```bash
uv run ruff check . && uv run ruff format --check . && uv run pyright && uv run pytest -q
```

## Pull request checklist

- [ ] `pytest` passes, and new code has tests covering both happy path and at least one failure mode.
- [ ] `ruff check` + `ruff format --check` clean.
- [ ] `pyright` clean (basic mode — see `pyproject.toml`).
- [ ] If you changed a contract (`contracts.py`) or config schema (`config.py`), updated callers and bumped version in `pyproject.toml`.
- [ ] Updated `CHANGELOG.md` under `## [Unreleased]`.
- [ ] README or docstrings updated if user-facing behavior changed.

## What to work on

See `.chunks/` (local) or the roadmap in `README.md` for deferred items. Concrete entry points if you're looking for something to do:

- Promote the `synthesize_abstract_header` helper (currently in `/tmp/evalit_full_report.py` at user machines) into `src/evalit_4me/ingest/parser.py`. Robust IEEE-style abstract detection.
- Add a `configs/ieee-double-blind.yaml` variant for conferences like ICSE / FSE that have moved to double-blind review.
- Extend the heuristic rubric-scoring mapping in `stages/rubric.py` to cover IEEE dimensions (`novelty`, `technical_quality`, `clarity`).
- Build the Phase 2 benchmark harness — see the IEEE chapter and plan for target metrics.

## Commit style

No strict format required. Imperative mood, scope-prefixed where reasonable:

```
fix(ingest): handle IEEE-style inline abstract markers
feat(scoring): allow per-venue composite weights
docs: clarify Claude Desktop MCP install on linux
```

## Reporting bugs

Open an issue with:

- `evalit version`
- Python version (`python --version`)
- The paper that triggered it (or a redacted snippet)
- Full stack trace

## Code of conduct

This project follows the [Contributor Covenant Code of Conduct](CODE_OF_CONDUCT.md). By participating you agree to uphold it.

## License

By submitting a patch, you agree that your contribution will be licensed under Apache-2.0 (the same as the project).
