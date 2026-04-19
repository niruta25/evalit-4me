"""Tests for the marker_single subprocess wrapper.

We never touch a real `marker_single` binary. `subprocess.run` and
`shutil.which` are mocked, and the test populates a fake markdown file
in the output dir so the runner's file-discovery path is exercised.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from evalit_4me.ingest.errors import (
    MarkerBinaryNotFoundError,
    MarkerExecutionError,
    MarkerTimeoutError,
)
from evalit_4me.ingest.marker_runner import MarkerRunner, run_marker


def _make_pdf(tmp_path: Path, name: str = "sample.pdf", content: bytes = b"%PDF-1.4") -> Path:
    pdf = tmp_path / name
    pdf.write_bytes(content)
    return pdf


def test_marker_not_found_raises(tmp_path: Path):
    pdf = _make_pdf(tmp_path)
    with patch("evalit_4me.ingest.marker_runner.shutil.which", return_value=None):
        runner = MarkerRunner(binary="marker_single")
        with pytest.raises(MarkerBinaryNotFoundError):
            runner.run(pdf)


def test_missing_pdf_raises(tmp_path: Path):
    runner = MarkerRunner()
    with pytest.raises(MarkerExecutionError, match="PDF not found"):
        runner.run(tmp_path / "does_not_exist.pdf")


def test_success_reads_markdown(tmp_path: Path):
    pdf = _make_pdf(tmp_path)

    def fake_run(cmd, *args, **kwargs):
        # cmd = [binary, pdf, --output_dir, out_dir, --output_format, markdown]
        out_dir = Path(cmd[cmd.index("--output_dir") + 1])
        sub = out_dir / "sample"
        sub.mkdir(parents=True, exist_ok=True)
        (sub / "sample.md").write_text("# Hello\n\nbody", encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    with (
        patch(
            "evalit_4me.ingest.marker_runner.shutil.which",
            return_value="/fake/bin/marker_single",
        ),
        patch("evalit_4me.ingest.marker_runner.subprocess.run", side_effect=fake_run),
    ):
        runner = MarkerRunner()
        md = runner.run(pdf)

    assert md.startswith("# Hello")


def test_nonzero_exit_raises(tmp_path: Path):
    pdf = _make_pdf(tmp_path)

    def fake_run(cmd, *args, **kwargs):
        return subprocess.CompletedProcess(cmd, 2, stdout="", stderr="boom")

    with (
        patch(
            "evalit_4me.ingest.marker_runner.shutil.which",
            return_value="/fake/bin/marker_single",
        ),
        patch("evalit_4me.ingest.marker_runner.subprocess.run", side_effect=fake_run),
        pytest.raises(MarkerExecutionError, match="boom"),
    ):
        MarkerRunner().run(pdf)


def test_no_markdown_produced_raises(tmp_path: Path):
    pdf = _make_pdf(tmp_path)

    def fake_run(cmd, *args, **kwargs):
        # Return success but write nothing.
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    with (
        patch(
            "evalit_4me.ingest.marker_runner.shutil.which",
            return_value="/fake/bin/marker_single",
        ),
        patch("evalit_4me.ingest.marker_runner.subprocess.run", side_effect=fake_run),
        pytest.raises(MarkerExecutionError, match="no markdown"),
    ):
        MarkerRunner().run(pdf)


def test_timeout_raises(tmp_path: Path):
    pdf = _make_pdf(tmp_path)

    def fake_run(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=["marker_single"], timeout=1)

    with (
        patch(
            "evalit_4me.ingest.marker_runner.shutil.which",
            return_value="/fake/bin/marker_single",
        ),
        patch("evalit_4me.ingest.marker_runner.subprocess.run", side_effect=fake_run),
    ):
        runner = MarkerRunner(timeout_sec=1)
        with pytest.raises(MarkerTimeoutError):
            runner.run(pdf)


def test_run_marker_convenience_wrapper(tmp_path: Path):
    pdf = _make_pdf(tmp_path)

    def fake_run(cmd, *args, **kwargs):
        out_dir = Path(cmd[cmd.index("--output_dir") + 1])
        (out_dir / "out.md").write_text("# Convenience", encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    with (
        patch(
            "evalit_4me.ingest.marker_runner.shutil.which",
            return_value="/fake/bin/marker_single",
        ),
        patch("evalit_4me.ingest.marker_runner.subprocess.run", side_effect=fake_run),
    ):
        md = run_marker(pdf)

    assert "Convenience" in md
