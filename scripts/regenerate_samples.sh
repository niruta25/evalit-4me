#!/usr/bin/env bash
# Regenerate the binary sample papers (PDFs and DOCX) from the markdown
# sources in plugin/examples/. Run this whenever the .md samples change.
#
# Requirements:
#   - uv (to bring in reportlab ephemerally)
#   - pandoc (for the .docx)

set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
EXAMPLES="$ROOT/plugin/examples"

echo "Regenerating PDFs via reportlab..."
cd "$ROOT"
uv run --with reportlab python "$HERE/regenerate_samples.py"

echo "Regenerating sample.docx via pandoc..."
pandoc "$EXAMPLES/sample_neurips.md" -o "$EXAMPLES/sample.docx"

echo "Done. Files:"
ls -l "$EXAMPLES"/*.{pdf,docx}
