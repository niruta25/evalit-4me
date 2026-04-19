---
description: Review an academic paper using the evalit 5-stage reviewer-assist pipeline (compliance, citation verification, depth, rubric, composite). Works on PDF or markdown.
argument-hint: "[paper-path]"
allowed-tools: [mcp__evalit__detect_config, mcp__evalit__review_paper, mcp__evalit__compare, mcp__evalit__reweight, Bash, Read, Glob, Write]
---

Invoke the evalit paper-review skill. $ARGUMENTS should be a local filesystem path to a PDF or `.md` file. If no path is given, ask the user for one before calling any tools.

Follow the playbook in `skills/evalit/SKILL.md` step-by-step:

1. Confirm the paper path.
2. Call `detect_config` to auto-detect the best venue config and ask the user whether to run just that config or all three (neurips / arxiv / ieee) in parallel.
3. Call `review_paper` with the chosen configs and relay the structured results as reviewer signals, not decisions.
4. Offer follow-ups — explain a score, reweight the composite via `reweight`, or compare records via `compare`.

Keep the reviewer-assist framing throughout: composite scores are queue-sort signals, compliance `FAIL` means "a human should look at this first," never auto-reject.
