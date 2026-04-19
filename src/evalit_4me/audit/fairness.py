"""High-level fairness report builder.

Aggregates three metrics:

1. **Length-score correlation** — Pearson correlation between paper word
   count and rubric score. Strong positive correlation suggests length bias
   (longer papers systematically score higher independent of content).
2. **Position-bias** — placeholder for reviewer-assist (single-paper runs).
   In editor-triage mode (v0.2), this would correlate a paper's appearance
   order in a session with its score.
3. **Disparate impact** — on a built-in split (word count above/below the
   median in this audit run) using the accept/reject threshold. Additional
   group_fns can be layered in by callers who want e.g. venue or year splits.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from evalit_4me.audit.disparate_impact import compute_disparate_impact, to_dict
from evalit_4me.contracts import EvaluationRecord
from evalit_4me.storage.sqlite_log import SqliteLog


@dataclass(frozen=True)
class FairnessReport:
    n_records: int
    length_score_pearson: float | None
    length_score_rationale: str
    position_bias: dict[str, Any] = field(default_factory=dict)
    length_disparate_impact: dict[str, Any] = field(default_factory=dict)
    accept_threshold: float = 0.55


def build_fairness_report(
    records: list[EvaluationRecord],
    *,
    accept_threshold: float = 0.55,
) -> FairnessReport:
    length_corr, length_note = _length_score_correlation(records)
    di = _length_di(records, accept_threshold=accept_threshold)
    return FairnessReport(
        n_records=len(records),
        length_score_pearson=length_corr,
        length_score_rationale=length_note,
        position_bias={
            "note": "Position bias requires session ordering (v0.2 editor-triage).",
        },
        length_disparate_impact=to_dict(di),
        accept_threshold=accept_threshold,
    )


def build_fairness_report_from_db(
    db_path: Path | str,
    *,
    accept_threshold: float = 0.55,
) -> FairnessReport:
    log = SqliteLog(db_path)
    records = list(log.iter_records())
    return build_fairness_report(records, accept_threshold=accept_threshold)


def report_to_dict(report: FairnessReport) -> dict[str, Any]:
    return asdict(report)


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _length_score_correlation(
    records: list[EvaluationRecord],
) -> tuple[float | None, str]:
    pairs: list[tuple[float, float]] = []
    for rec in records:
        if rec.rubric is None:
            continue
        wc = _word_count(rec)
        pairs.append((float(wc), float(rec.rubric.bias_adjusted_total)))
    if len(pairs) < 3:
        return None, "Too few records with rubric scores for correlation."
    xs = [p[0] for p in pairs]
    ys = [p[1] for p in pairs]
    return round(_pearson(xs, ys), 4), f"Pearson over {len(pairs)} records."


def _length_di(records, *, accept_threshold: float):
    if not records:
        return compute_disparate_impact(
            [],
            group_fn=lambda r: None,
            score_fn=lambda r: 0.0,
            threshold=accept_threshold,
        )
    word_counts = sorted(_word_count(r) for r in records)
    median = word_counts[len(word_counts) // 2]

    def group(rec):
        return "long" if _word_count(rec) > median else "short"

    def score(rec):
        return rec.rubric.bias_adjusted_total if rec.rubric else 0.0

    return compute_disparate_impact(
        records,
        group_fn=group,
        score_fn=score,
        threshold=accept_threshold,
    )


def _word_count(record: EvaluationRecord) -> int:
    total = 0
    if record.paper.metadata.abstract:
        total += len(record.paper.metadata.abstract.split())
    for section in record.paper.sections:
        total += len(section.text.split())
    return total


def _pearson(xs: list[float], ys: list[float]) -> float:
    n = len(xs)
    if n == 0:
        return 0.0
    mx = sum(xs) / n
    my = sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True))
    dx = sum((x - mx) ** 2 for x in xs) ** 0.5
    dy = sum((y - my) ** 2 for y in ys) ** 0.5
    if dx == 0 or dy == 0:
        return 0.0
    return num / (dx * dy)
