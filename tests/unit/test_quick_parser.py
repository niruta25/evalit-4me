"""Tests for `ingest.quick_parser` — the pypdf-backed fast sample path."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from evalit_4me.ingest.quick_parser import DEFAULT_SAMPLE_PAGES, quick_extract_first_pages


def _mock_page(text: str | None) -> MagicMock:
    page = MagicMock()
    page.extract_text.return_value = text
    return page


def _mock_reader(pages: list[MagicMock]) -> MagicMock:
    reader = MagicMock()
    reader.pages = pages
    return reader


def test_extracts_first_n_pages(tmp_path: Path):
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"not-a-real-pdf")  # file only needs to exist

    reader = _mock_reader(
        [
            _mock_page("page one text"),
            _mock_page("page two text"),
            _mock_page("page three text"),
            _mock_page("page four should be skipped"),
        ]
    )
    with patch("pypdf.PdfReader", return_value=reader):
        out = quick_extract_first_pages(pdf, n=3)

    assert "page one text" in out
    assert "page two text" in out
    assert "page three text" in out
    assert "page four" not in out


def test_uses_default_sample_page_count(tmp_path: Path):
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"x")

    many_pages = [_mock_page(f"p{i}") for i in range(10)]
    reader = _mock_reader(many_pages)
    with patch("pypdf.PdfReader", return_value=reader):
        out = quick_extract_first_pages(pdf)

    for i in range(DEFAULT_SAMPLE_PAGES):
        assert f"p{i}" in out
    assert f"p{DEFAULT_SAMPLE_PAGES}" not in out


def test_handles_fewer_pages_than_requested(tmp_path: Path):
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"x")

    reader = _mock_reader([_mock_page("only page")])
    with patch("pypdf.PdfReader", return_value=reader):
        out = quick_extract_first_pages(pdf, n=5)

    assert out.strip() == "only page"


def test_handles_page_with_no_extractable_text(tmp_path: Path):
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"x")

    reader = _mock_reader([_mock_page(None), _mock_page("text on page 2")])
    with patch("pypdf.PdfReader", return_value=reader):
        out = quick_extract_first_pages(pdf, n=2)

    assert "text on page 2" in out


def test_raises_on_missing_file(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        quick_extract_first_pages(tmp_path / "does-not-exist.pdf")
