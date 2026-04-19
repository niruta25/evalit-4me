"""Subprocess wrapper around the `marker_single` CLI.

`marker_single INPUT_PDF OUTPUT_DIR [options]` writes a markdown file and
extracted images into a per-paper subdirectory of OUTPUT_DIR. We locate
the resulting `.md` file, read it, and return the text.

Why subprocess and not import: `marker-pdf` is GPLv3+ and we ship under
Apache-2. Keeping it out of our dependency graph means users install it
separately (like `pandoc` or `ffmpeg`), and our package remains clean.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from evalit_4me.ingest.errors import (
    MarkerBinaryNotFoundError,
    MarkerExecutionError,
    MarkerTimeoutError,
)

DEFAULT_BINARY = "marker_single"
DEFAULT_TIMEOUT_SEC = 600  # 10 min — marker can be slow on large PDFs


@dataclass
class MarkerRunner:
    """Invokes `marker_single` and returns the extracted markdown.

    `binary` is configurable so tests (and users with a non-standard
    install) can point at a specific path.
    """

    binary: str = DEFAULT_BINARY
    timeout_sec: int = DEFAULT_TIMEOUT_SEC

    def run(self, pdf_path: Path | str) -> str:
        pdf = Path(pdf_path)
        if not pdf.exists():
            raise MarkerExecutionError(f"PDF not found: {pdf}")

        resolved = shutil.which(self.binary)
        if resolved is None:
            raise MarkerBinaryNotFoundError(
                f"Could not find `{self.binary}` on PATH. "
                "Install marker-pdf with `pip install marker-pdf` "
                "(note: marker-pdf is GPLv3+ and is installed separately)."
            )

        with tempfile.TemporaryDirectory(prefix="evalit-marker-") as tmpdir:
            out_dir = Path(tmpdir)
            try:
                completed = subprocess.run(
                    [
                        resolved,
                        str(pdf),
                        "--output_dir",
                        str(out_dir),
                        "--output_format",
                        "markdown",
                    ],
                    capture_output=True,
                    text=True,
                    timeout=self.timeout_sec,
                    check=False,
                )
            except subprocess.TimeoutExpired as exc:
                raise MarkerTimeoutError(
                    f"marker_single timed out after {self.timeout_sec}s on {pdf.name}"
                ) from exc
            except FileNotFoundError as exc:  # race: binary vanished after which()
                raise MarkerBinaryNotFoundError(str(exc)) from exc

            if completed.returncode != 0:
                raise MarkerExecutionError(
                    f"marker_single exited {completed.returncode}: "
                    f"{completed.stderr.strip() or completed.stdout.strip()}"
                )

            md = _find_markdown(out_dir)
            if md is None:
                raise MarkerExecutionError(
                    f"marker_single produced no markdown output in {out_dir}. "
                    f"stderr: {completed.stderr.strip()}"
                )
            return md.read_text(encoding="utf-8")


def _find_markdown(out_dir: Path) -> Path | None:
    """Return the first `.md` file under out_dir, or None if absent.

    marker_single typically writes `<out_dir>/<stem>/<stem>.md`.
    """
    candidates = sorted(out_dir.rglob("*.md"))
    return candidates[0] if candidates else None


def run_marker(
    pdf_path: Path | str,
    *,
    binary: str = DEFAULT_BINARY,
    timeout_sec: int = DEFAULT_TIMEOUT_SEC,
) -> str:
    """Convenience wrapper for one-off callers."""
    return MarkerRunner(binary=binary, timeout_sec=timeout_sec).run(pdf_path)
