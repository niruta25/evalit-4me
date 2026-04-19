#!/usr/bin/env python3
"""Print the recommended config for a paper. Used by SKILL.md.

usage: detect_config.py <pdf-or-markdown-path>

prints one line of JSON: {"recommended": "...", "confidence": 0.xx, "rationale": "..."}
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def _load_markdown(path: Path) -> str:
    if path.suffix.lower() == ".pdf":
        # Lazy import — marker is a heavy dep; we only need it for PDFs.
        from evalit_4me.ingest.parser import parse_pdf

        paper = parse_pdf(path)
        # Reconstruct markdown from sections for detection purposes.
        body = "\n\n".join(f"## {s.title}\n\n{s.text}" for s in paper.sections)
        return f"# {paper.metadata.title}\n\n{body}"
    return path.read_text(encoding="utf-8")


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: detect_config.py <path>", file=sys.stderr)
        return 2
    from evalit_4me.skill_helpers import detect_best_config

    markdown = _load_markdown(Path(sys.argv[1]))
    guess = detect_best_config(markdown)
    print(
        json.dumps(
            {
                "recommended": guess.recommended,
                "confidence": round(guess.confidence, 3),
                "rationale": guess.rationale,
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
