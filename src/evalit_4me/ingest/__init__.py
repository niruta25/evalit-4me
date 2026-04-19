"""PDF ingestion via the `marker_single` CLI.

`marker-pdf` itself is GPLv3+ and is never imported or declared as a
dependency of this package. Users install it separately; we invoke it as
an external process from `marker_runner`.
"""

from evalit_4me.ingest.errors import (
    IngestError,
    MarkerBinaryNotFoundError,
    MarkerExecutionError,
    MarkerTimeoutError,
    ParseError,
)
from evalit_4me.ingest.marker_runner import MarkerRunner, run_marker
from evalit_4me.ingest.parser import parse_markdown, parse_pdf
from evalit_4me.ingest.reference_extractor import extract_references

__all__ = [
    "IngestError",
    "MarkerBinaryNotFoundError",
    "MarkerExecutionError",
    "MarkerRunner",
    "MarkerTimeoutError",
    "ParseError",
    "extract_references",
    "parse_markdown",
    "parse_pdf",
    "run_marker",
]
