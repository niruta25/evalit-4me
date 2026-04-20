#!/usr/bin/env bash
# Manual plugin smoke test — exercises the 8 sample papers through the
# CLI as a proxy for what Claude Code would do via the MCP tools.
#
# Preconditions:
#   - uv installed and on PATH
#   - repo synced: `uv sync --extra pdf-lite --extra docx --extra mcp`
#   - ANTHROPIC_API_KEY unset (`unset ANTHROPIC_API_KEY`) to confirm
#     heuristic mode works without it
#
# Exits non-zero on first failure.

set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
EXAMPLES="$ROOT/plugin/examples"

echo "=== evalit plugin smoke test ==="
echo "repo: $ROOT"
echo

if [[ -n "${ANTHROPIC_API_KEY:-}" ]]; then
  echo "WARNING: ANTHROPIC_API_KEY is set. Unset it to verify the no-key path."
fi

pass() { echo "  ok: $1"; }
fail() { echo "  FAIL: $1"; exit 1; }

run_review() {
  local sample="$1"
  local config="$2"
  local tmp
  tmp="$(mktemp -d)"
  local out="$tmp/record.json"
  cd "$ROOT"
  uv run evalit review "$EXAMPLES/$sample" \
    --config "$ROOT/configs/${config}.yaml" \
    --output "$out" >/dev/null 2>&1 \
    || fail "pipeline crashed on $sample under $config"
  [[ -s "$out" ]] || fail "empty record for $sample"
  pass "$sample under $config → $out"
  rm -rf "$tmp"
}

echo "--- markdown samples ---"
run_review "sample_neurips.md" "neurips"
run_review "sample_ieee.md" "ieee"
run_review "sample_arxiv.md" "arxiv"
run_review "sample_failing.md" "neurips"
run_review "sample_fabricated.md" "neurips"

echo
echo "--- PDF samples (pdfplumber) ---"
run_review "sample.pdf" "arxiv"
run_review "sample_twocol.pdf" "ieee"

echo
echo "--- DOCX sample (mammoth) ---"
run_review "sample.docx" "neurips"

echo
echo "--- interactive HTML report check ---"
cd "$ROOT"
tmp="$(mktemp -d)"
uv run python -c "
import json, sys
from pathlib import Path
from evalit_4me.config import load_venue_config
from evalit_4me.ingest import load_paper
from evalit_4me.stages.orchestrate import run_pipeline
from evalit_4me.formatters.html import render_report_html

paper = load_paper(Path('$EXAMPLES/sample_neurips.md'))
cfg = load_venue_config(Path('$ROOT/configs/neurips.yaml'))
record = run_pipeline(paper, cfg, provider=None, http_client=None)
html = render_report_html(record)
out = Path('$tmp/report.html')
out.write_text(html, encoding='utf-8')
# Assert the interactive bits are present.
assert 'weight-compliance' in html, 'missing compliance slider'
assert 'weight-verification' in html, 'missing verification slider'
assert 'weight-depth' in html, 'missing depth slider'
assert 'weight-rubric' in html, 'missing rubric slider'
assert 'evalit-record' in html, 'missing embedded record blob'
assert 'copy-review-md' in html, 'missing copy-markdown button'
print('interactive HTML report ok:', out)
" || fail "HTML report generation failed"
pass "interactive HTML report contains sliders + embedded record"
rm -rf "$tmp"

echo
echo "=== smoke test passed ==="
