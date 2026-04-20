"""Input-format dispatcher.

One entry point, `load_paper`, accepts any supported path (`.pdf`, `.md`,
`.docx`) and returns a `Paper`. PDF inputs default to pdfplumber — the
lightweight, in-process path. Marker-pdf is opt-in via either:

* `EVALIT_USE_MARKER=1` env var (respected by every caller, including the
  MCP server), or
* `use_marker=True` passed explicitly (the CLI `--full-fidelity` flag).

When marker is requested but `marker_single` isn't on PATH, we fall back
to pdfplumber and emit a single warning — never a hard failure, so users
without marker still get a result.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from evalit_4me.contracts import Paper
from evalit_4me.ingest.docx_parser import parse_docx
from evalit_4me.ingest.errors import IngestError, MarkerBinaryNotFoundError
from evalit_4me.ingest.parser import parse_markdown, parse_pdf
from evalit_4me.ingest.plumber_parser import (
    PdfPlumberNotInstalledError,
    parse_pdf_with_plumber,
)

log = logging.getLogger("evalit.ingest")


class UnsupportedFormatError(IngestError):
    """The file extension is not one we can parse."""


def load_paper(path: Path | str, *, use_marker: bool | None = None) -> Paper:
    """Dispatch based on file extension.

    Arguments:
        path: path to `.pdf`, `.md`, or `.docx`.
        use_marker: PDF only. `True` → marker_single; `False` → pdfplumber;
            `None` (default) → honor `EVALIT_USE_MARKER=1` env var,
            else pdfplumber.
    """
    p = Path(path)
    suffix = p.suffix.lower()

    if suffix == ".pdf":
        return _load_pdf(p, use_marker=use_marker)
    if suffix == ".docx":
        return parse_docx(p)
    if suffix in {".md", ".markdown", ".txt"}:
        return parse_markdown(p.read_text(encoding="utf-8"), source_name=p.stem)
    raise UnsupportedFormatError(
        f"Unsupported input format: {suffix}. Expected one of .pdf, .md, .docx."
    )


def _load_pdf(path: Path, *, use_marker: bool | None) -> Paper:
    wants_marker = (
        use_marker
        if use_marker is not None
        else os.environ.get("EVALIT_USE_MARKER", "").strip() == "1"
    )
    if wants_marker:
        try:
            return parse_pdf(path)
        except MarkerBinaryNotFoundError:
            log.warning(
                "EVALIT_USE_MARKER=1 (or --full-fidelity) set but marker_single "
                "not on PATH. Falling back to pdfplumber."
            )
    try:
        return parse_pdf_with_plumber(path)
    except PdfPlumberNotInstalledError:
        # pdfplumber missing — try marker as a second-chance fallback. If
        # that also fails, the error surfaces to the caller.
        return parse_pdf(path)
