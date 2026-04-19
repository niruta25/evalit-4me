"""SQLite audit log for `EvaluationRecord`s.

Schema (single table + index):

    CREATE TABLE evaluations (
        id                    INTEGER PRIMARY KEY AUTOINCREMENT,
        paper_id              TEXT    NOT NULL,
        created_at            TEXT    NOT NULL,   -- ISO-8601 UTC
        evalit_version        TEXT    NOT NULL,
        config_hash           TEXT    NOT NULL,
        cost_usd              REAL    NOT NULL DEFAULT 0.0,
        rubric_raw_total      REAL,
        rubric_adjusted_total REAL,
        compliance_triage     TEXT,
        total_claims          INTEGER NOT NULL DEFAULT 0,
        hallucination_count   INTEGER NOT NULL DEFAULT 0,
        record_json           TEXT    NOT NULL    -- full record, round-trips
    );
    CREATE INDEX idx_eval_paper ON evaluations(paper_id);
    CREATE INDEX idx_eval_config ON evaluations(config_hash);

The flat columns are for audit queries; `record_json` is the source of
truth. Keeping both lets fairness/analysis code stay SQL-only for simple
queries, while `iter_records()` reconstructs typed `EvaluationRecord`s on
demand.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from evalit_4me.contracts import EvaluationRecord

_SCHEMA = """
CREATE TABLE IF NOT EXISTS evaluations (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    paper_id              TEXT    NOT NULL,
    created_at            TEXT    NOT NULL,
    evalit_version        TEXT    NOT NULL,
    config_hash           TEXT    NOT NULL,
    cost_usd              REAL    NOT NULL DEFAULT 0.0,
    rubric_raw_total      REAL,
    rubric_adjusted_total REAL,
    compliance_triage     TEXT,
    total_claims          INTEGER NOT NULL DEFAULT 0,
    hallucination_count   INTEGER NOT NULL DEFAULT 0,
    record_json           TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_eval_paper ON evaluations(paper_id);
CREATE INDEX IF NOT EXISTS idx_eval_config ON evaluations(config_hash);
"""


class SqliteLog:
    """Append-only audit log. Callers open once, save many."""

    def __init__(self, db_path: Path | str) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path)
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    # --- Write ------------------------------------------------------------

    def save(self, record: EvaluationRecord) -> int:
        row = _to_row(record)
        with self._connect() as conn:
            cur = conn.execute(
                """INSERT INTO evaluations (
                    paper_id, created_at, evalit_version, config_hash,
                    cost_usd, rubric_raw_total, rubric_adjusted_total,
                    compliance_triage, total_claims, hallucination_count,
                    record_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                row,
            )
            new_id = cur.lastrowid
        assert new_id is not None
        return int(new_id)

    # --- Read -------------------------------------------------------------

    def load(self, evaluation_id: int) -> EvaluationRecord:
        with self._connect() as conn:
            cur = conn.execute("SELECT record_json FROM evaluations WHERE id = ?", (evaluation_id,))
            row = cur.fetchone()
        if row is None:
            raise KeyError(f"No evaluation with id={evaluation_id}")
        return EvaluationRecord.model_validate_json(row[0])

    def iter_records(self) -> Iterator[EvaluationRecord]:
        with self._connect() as conn:
            cur = conn.execute("SELECT record_json FROM evaluations ORDER BY id")
            for (raw,) in cur.fetchall():
                yield EvaluationRecord.model_validate_json(raw)

    def count(self) -> int:
        with self._connect() as conn:
            cur = conn.execute("SELECT COUNT(*) FROM evaluations")
            return int(cur.fetchone()[0])

    def query_scores(self) -> list[dict[str, object]]:
        """Return flat score rows — useful for ad-hoc analysis / fairness audit."""
        with self._connect() as conn:
            cur = conn.execute(
                """SELECT id, paper_id, created_at, rubric_raw_total,
                          rubric_adjusted_total, compliance_triage,
                          total_claims, hallucination_count, cost_usd
                   FROM evaluations
                   ORDER BY id"""
            )
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, r, strict=True)) for r in cur.fetchall()]


def _to_row(record: EvaluationRecord) -> tuple:
    rubric_raw = record.rubric.raw_total if record.rubric else None
    rubric_adj = record.rubric.bias_adjusted_total if record.rubric else None
    triage = record.compliance.triage.value if record.compliance else None
    created = record.created_at.isoformat()
    return (
        record.paper.id,
        created,
        record.provenance.evalit_version,
        record.provenance.config_hash,
        record.provenance.cost_usd,
        rubric_raw,
        rubric_adj,
        triage,
        record.claims.total_claims,
        record.claims.hallucination_count,
        record.model_dump_json(),
    )


def dump_as_jsonl(db_path: Path | str, out_path: Path | str) -> int:
    """Export every record to JSON Lines. Returns number of records written."""
    log = SqliteLog(db_path)
    count = 0
    with Path(out_path).open("w", encoding="utf-8") as f:
        for rec in log.iter_records():
            f.write(rec.model_dump_json() + "\n")
            count += 1
    return count


__all__ = ["SqliteLog", "dump_as_jsonl"]
