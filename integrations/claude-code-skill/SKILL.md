---
name: evalit
description: Review an academic paper using the evalit-4me 5-stage pipeline — triggers on PDFs and on phrases like "review this paper", "evaluate this paper", "score this paper". Can compare multiple venue configs in parallel and tweak composite-score weights interactively.
allowed-tools: [Bash, Read, Write, Glob, Grep]
---

# evalit — academic-paper review skill

Use this skill whenever the user gives you a paper (PDF or markdown) and asks for a review, evaluation, or score. Works for conference submissions (IEEE, NeurIPS), arXiv preprints, or any academic paper the user provides a local path to.

## When to trigger

- User drops a local path ending in `.pdf` or `.md` and says anything like *"review this"*, *"evaluate this"*, *"score this paper"*, *"can you check this paper"*, *"run evalit on this"*.
- User says *"compare this paper under different configs"*.
- User says *"reweight the score"* / *"what if I give rubric more weight"* against a previously-evaluated paper.
- User invokes `/evalit` explicitly.

If the user says *"review my code"* or otherwise is clearly not asking about an academic paper, don't trigger — this is a paper-review skill specifically.

## Playbook — new paper

1. **Confirm the paper path** — the user must have given a local filesystem path. Don't invent one. If they haven't, ask: *"What's the path to the paper?"*

2. **Detect the best config** — run:

   ```bash
   uv run --project /path/to/evalit-4me python \
     integrations/claude-code-skill/helpers/detect_config.py <paper-path>
   ```

   The helper prints one JSON line `{"recommended": "ieee"|"arxiv"|"neurips", "confidence": 0..1, "rationale": "..."}`.

   Parse it and say, verbatim: *"I detected this as most likely a **\<config>** paper — \<rationale>. Do you want me to run just \<config>, or all three configs (neurips, arxiv, ieee) and compare?"*

3. **Wait for the user's answer.** Don't assume. Likely answers: *"just ieee"*, *"all three"*, *"use neurips"*.

4. **Run the pipeline.** Build a comma-separated list of the user's chosen configs and invoke:

   ```bash
   uv run --project /path/to/evalit-4me python \
     integrations/claude-code-skill/helpers/run_multi_config.py <paper-path> <configs>
   ```

   Each completed run prints a JSON line; the final line is `{"summary": {...}}` with `out_dir` and (if N>1) `comparison`.

   Runs land in `~/evalit-reports/<YYYY-MM-DD>-<paper-slug>/`.

5. **Present the result.** For each config, show: compliance triage, composite score, recommendation, hallucination count. If N > 1, show a small markdown table + offer to share `comparison.md`. Always mention the file paths so the user can open the HTML reports.

6. **Offer follow-ups:**
   - *"Want me to explain any specific score?"*
   - *"Want to tweak the composite weights?"* — if yes, move to the reweight playbook.

## Playbook — reweight composite

Use when the user says things like *"give rubric more weight"*, *"what if compliance counted less"*, *"halve verification"*, *"try weights X/Y/Z"*.

1. **Find the saved record.** Either the user names one, or pick the most recent in `~/evalit-reports/` (use the Bash/Glob tool to list the directory).

2. **Translate the user's request into explicit weights.** The four knobs are:
   - `compliance` (default 0.15)
   - `verification` (default 0.20)
   - `depth` (default 0.20)
   - `rubric` (default 0.45)

   Missing weights inherit defaults. Negative weights are rejected. Sum doesn't have to be 1.0.

   If the user is vague ("give more weight to verification"), propose a concrete set and confirm.

3. **Run:**

   ```bash
   uv run --project /path/to/evalit-4me python \
     integrations/claude-code-skill/helpers/recompute_composite.py \
     <record.json> compliance=0.10 verification=0.35 depth=0.10 rubric=0.45
   ```

   Helper prints JSON with `original_composite`, `new_composite`, `delta`, `recommendation_before`, `recommendation_after`, full `breakdown`.

4. **Show the delta** — the two composite values, the change in recommendation (if any), and the new per-stage contributions.

5. **Offer another iteration** — users often want to try 2-3 weight sets to find one that feels right.

## Playbook — compare existing records

Use when the user says *"compare these two records"* or *"show me the comparison again"*.

```bash
uv run --project /path/to/evalit-4me python \
  integrations/claude-code-skill/helpers/compare_records.py \
  <record1.json> [<record2.json> ...]
```

Prints a markdown table to stdout. Relay it to the user verbatim (it's already formatted).

## Things to do and not do

- **Do** relay file paths so the user can open HTML reports (`/path/to/ieee.html`, etc.).
- **Do** mention costs when a run triggers LLM calls — typical paper is $0.30-0.50 on Sonnet.
- **Do** warn on compliance FAIL: since chunk 1.14, FAIL no longer forces STRONG_REJECT, but the composite still reflects the pass-rate so a failing paper will score lower.
- **Don't** invent paths or rerun a paper automatically without asking — compute time + API cost matters.
- **Don't** interpret "reweight" requests as full rerun requests — the recompute helper is free (no LLM, no network).
- **Don't** try to install marker or any dependency yourself — assume the user already has the venv set up. If a helper fails with ImportError, surface the error and ask the user to `uv sync --extra dashboard` in the repo.

## How to find the repo

The helper paths above assume the user's evalit-4me clone. Before running, determine the repo root:

1. If the user mentioned the repo path explicitly, use it.
2. Otherwise, check `~/Documents/GitHub/evalit-4me` (the common location) or ask.
3. Run `uv run --project <root> python <helper>` so you pick up the right venv.

## API key note

The pipeline works without an API key (heuristic fallback path), but rubric scoring will be less informative. If `ANTHROPIC_API_KEY` isn't set, mention this and the user can either proceed with heuristics or export a key and retry.
