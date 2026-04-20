"""PDF / markdown / docx ingestion.

Three paths, one dispatcher:

* `.pdf` (default) → pdfplumber, via the `[pdf-lite]` extra (~10 MB).
* `.pdf` (opt-in)  → marker_single, via the `[pdf]` extra (~2 GB weights).
                     Enable with `EVALIT_USE_MARKER=1` or `--full-fidelity`.
* `.docx`          → mammoth, via the `[docx]` extra (~2 MB).
* `.md` / `.txt`   → markdown straight through.

marker-pdf is GPLv3+ and invoked as an external subprocess only; it's
never imported from this package.
"""

from evalit_4me.ingest.dispatch import (
    UnsupportedFormatError,
    load_paper,
)
from evalit_4me.ingest.docx_parser import MammothNotInstalledError, parse_docx
from evalit_4me.ingest.errors import (
    IngestError,
    MarkerBinaryNotFoundError,
    MarkerExecutionError,
    MarkerTimeoutError,
    ParseError,
)
from evalit_4me.ingest.marker_runner import MarkerRunner, run_marker
from evalit_4me.ingest.parser import parse_markdown, parse_pdf
from evalit_4me.ingest.plumber_parser import (
    PdfPlumberNotInstalledError,
    parse_pdf_with_plumber,
)
from evalit_4me.ingest.reference_extractor import extract_references

__all__ = [
    "IngestError",
    "MammothNotInstalledError",
    "MarkerBinaryNotFoundError",
    "MarkerExecutionError",
    "MarkerRunner",
    "MarkerTimeoutError",
    "ParseError",
    "PdfPlumberNotInstalledError",
    "UnsupportedFormatError",
    "extract_references",
    "load_paper",
    "parse_docx",
    "parse_markdown",
    "parse_pdf",
    "parse_pdf_with_plumber",
    "run_marker",
]
