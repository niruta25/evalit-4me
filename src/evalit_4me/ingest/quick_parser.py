"""Fast, partial PDF text extraction for venue-config detection.

The full `ingest.parser.parse_pdf` path shells out to `marker_single` for
high-fidelity parsing - that can take 5-10 minutes on the first run and
well over a minute on later runs for large papers. Venue-config detection
(IEEE vs NeurIPS vs arXiv) doesn't need any of that fidelity; a handful
of pages of extracted text is enough for the heuristics in
`skill_helpers.detect_best_config`.

This module provides a second path using `pypdf` - pure Python,
subsecond on most papers, no model weights.
"""

from __future__ import annotations

from pathlib import Path

DEFAULT_SAMPLE_PAGES = 3


def quick_extract_first_pages(
    pdf_path: Path | str,
    n: int = DEFAULT_SAMPLE_PAGES,
) -> str:
    """Return concatenated text from the first `n` pages of `pdf_path`.

    If the PDF has fewer than `n` pages, all available pages are read.
    Page separators are double newlines so downstream heuristics that
    look for section headers still work.

    Raises `FileNotFoundError` if the path doesn't exist and propagates
    `pypdf` errors (e.g. `PdfReadError` for corrupt files).
    """
    from pypdf import PdfReader

    path = Path(pdf_path)
    if not path.exists():
        raise FileNotFoundError(f"PDF not found: {path}")

    reader = PdfReader(str(path))
    pages = reader.pages[:n]
    extracted = [p.extract_text() or "" for p in pages]
    return "\n\n".join(extracted)
