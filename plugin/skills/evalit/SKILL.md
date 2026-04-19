---
name: evalit
description: Review an academic paper using the evalit 5-stage reviewer-assist pipeline. Triggers on PDF/markdown paths plus phrases like "review this paper", "evaluate this paper", "score this paper", "check this submission". Can compare multiple venue configs in parallel and tweak composite-score weights interactively.
allowed-tools: [mcp__evalit__detect_config, mcp__evalit__review_paper, mcp__evalit__compare, mcp__evalit__reweight, Read, Glob]
---

# evalit — academic-paper review skill

Use this skill when the user gives you a paper (PDF or markdown) and asks for a review, evaluation, or score. Works for conference submissions (NeurIPS, IEEE), arXiv preprints, or any academic paper the user provides a local filesystem path to.

## Scope

**evalit is reviewer-assist, not a reviewer.** The pipeline produces structured signals (citation verification, depth heuristics, rubric breakdown, compliance triage) so a human reviewer can spend their limited time where it matters. A `compliance: FAIL` means "a human should look at this first," not "auto-reject." The composite score is a sort aid, not a threshold. There is no AI-text-detection — the project evaluates a paper's substance, not its authorship style.

When you relay results to the user, keep this framing. Don't describe composite scores as decisions.

## When to trigger

- User drops a local path ending in `.pdf` or `.md` and says anything like *"review this"*, *"evaluate this"*, *"score this paper"*, *"can you check this paper"*, *"run evalit on this"*.
- User says *"compare this paper under different configs"*.
- User says *"reweight the score"* / *"what if I give rubric more weight"* against a previously-evaluated paper.
- User invokes `/evalit:evalit` explicitly.

Don't trigger if the user means "review my code" or similar — this skill is paper-review specifically.

## Playbook — new paper

1. **Confirm the paper path.** The user must have given a local filesystem path. Don't invent one. If they haven't, ask: *"What's the path to the paper?"*

2. **Detect the best config** by calling the MCP tool `detect_config` with `paper_path`. It returns `{recommended, confidence, rationale}`.

   Relay to the user: *"I detected this as most likely a **\<recommended>** paper — \<rationale>. Do you want me to run just \<recommended>, or all three configs (neurips, arxiv, ieee) and compare?"*

3. **Wait for the user's answer.** Likely replies: *"just ieee"*, *"all three"*, *"use neurips"*.

4. **Run the pipeline** by calling the MCP tool `review_paper` with `paper_path` and a `configs` list (e.g. `["ieee"]` or `["neurips","arxiv","ieee"]`). Response shape:

   ```
   {
     "out_dir": "/Users/.../evalit-reports/2026-04-19-some-title/",
     "runs": [
       {"config": "ieee", "record": "...record.json", "html": "...ieee.html",
        "review_md": "...review.md", "composite": 0.7321, "recommendation": "ACCEPT"}
     ],
     "comparison": "<optional path when multiple configs>"
   }
   ```

5. **Present the result.** For each config, show: compliance triage, composite score, recommendation, hallucination count. If multiple configs, show a small markdown table and offer to share `comparison`. Always surface file paths so the user can open the HTML reports.

   Frame scores as reviewer signals, not verdicts. Example: *"Under IEEE the composite is 0.73 (recommendation: ACCEPT as a reviewer-queue sort signal). Compliance flagged two warnings; 1 citation couldn't be verified."*

6. **Offer follow-ups:**
   - *"Want me to explain any specific score?"*
   - *"Want to tweak the composite weights?"* → reweight playbook below.

## Playbook — reweight composite

Use when the user says things like *"give rubric more weight"*, *"what if compliance counted less"*, *"halve verification"*, *"try weights X/Y/Z"*.

1. **Find the saved record.** Either the user names one, or list the most recent under `~/evalit-reports/` via Glob and pick the newest `record.json`.

2. **Translate the user's request into explicit weights.** The four knobs:
   - `compliance` (default 0.15)
   - `verification` (default 0.20)
   - `depth` (default 0.20)
   - `rubric` (default 0.45)

   Missing keys inherit defaults. Negative weights are rejected. Sum doesn't have to be 1.0. If the user is vague, propose a concrete set and confirm before running.

3. **Call the MCP tool `reweight`** with `record_path` and a `weights` dict. Response:

   ```
   {
     "original_composite": 0.7321,
     "new_composite": 0.6840,
     "delta": -0.0481,
     "recommendation_before": "ACCEPT",
     "recommendation_after": "WEAK_ACCEPT",
     "breakdown": {...}
   }
   ```

4. **Show the delta** — the two composites, the change in recommendation (if any), and the new per-stage contributions. No LLM calls, no network, no cost.

5. **Offer another iteration** — users often want to try 2-3 weight sets to find one that feels right.

## Playbook — compare existing records

Use when the user says *"compare these two records"* or *"show me the comparison again"*.

Call the MCP tool `compare` with a list of record paths. It returns a markdown string — relay it verbatim to the user; it's already formatted.

## Things to do and not do

- **Do** relay file paths so the user can open HTML reports (`/path/to/ieee.html`, etc.).
- **Do** mention costs when a run triggers LLM calls — typical paper is $0.30–0.50 on Sonnet.
- **Do** frame compliance `FAIL` as "a human should look at this first," not auto-reject.
- **Don't** invent paths or rerun a paper automatically without asking — compute time + API cost matters.
- **Don't** interpret reweight requests as full rerun requests — `reweight` is free (no LLM, no network).
- **Don't** describe the composite score as a decision. It's a reviewer-queue sort signal.

## API key note

The pipeline works without an API key (heuristic fallback path), but rubric scoring is less informative. If `ANTHROPIC_API_KEY` isn't set, mention this and let the user choose: proceed with heuristics, or export a key and retry.

## Timing notes

- `detect_config` is near-instant on any paper (uses `pypdf` to sample the first three pages). Safe to call proactively in step 2 without warning the user.
- `review_paper` is the slow step on PDFs — `marker_single` may take 1–10 minutes depending on length and whether model weights are cached. Before step 4, warn the user: *"Parsing this PDF can take several minutes — first time even longer because marker downloads ~2 GB of model weights."*
- If the user plans to iterate (reweight, try different configs), suggest pre-converting the PDF once: `uvx --with marker-pdf marker_single paper.pdf ~/tmp/` and then giving you the resulting `.md` path. Review runs on markdown are seconds, not minutes.
- The first MCP-server invocation after plugin install also spends ~30s for `uv run --with` to prepare the ephemeral env. One-time cost.
