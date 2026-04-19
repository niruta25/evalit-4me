"""Ingest-layer error hierarchy."""

from __future__ import annotations


class IngestError(Exception):
    """Base class for ingest failures."""


class MarkerBinaryNotFoundError(IngestError):
    """`marker_single` is not on PATH. User must install marker-pdf separately."""


class MarkerExecutionError(IngestError):
    """marker_single exited non-zero or produced no markdown output."""


class MarkerTimeoutError(IngestError):
    """marker_single did not finish within the configured timeout."""


class ParseError(IngestError):
    """Markdown parser could not produce a valid Paper."""
