"""Disparate-impact ratio computation.

Standard 80% rule: P(positive | protected) / P(positive | reference) < 0.8
is flagged as potentially discriminatory. We frame it generically — caller
supplies group_fn (record -> group label) and score_fn (record -> float),
plus a threshold. The result exposes per-group positive-rate and the
worst-case DI ratio across group pairs.

Used by `evalit audit` to catch e.g. "short papers get rejected at 2x the
rate of long papers" without baking in any specific protected attribute.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from evalit_4me.contracts import EvaluationRecord


@dataclass(frozen=True)
class GroupRates:
    label: str
    n: int
    positive: int
    positive_rate: float


@dataclass(frozen=True)
class DisparateImpactResult:
    group_rates: list[GroupRates]
    reference_group: str | None
    di_ratio: float | None
    flagged_4_5ths_rule: bool
    notes: str = ""


def compute_disparate_impact(
    records: list[EvaluationRecord],
    *,
    group_fn: Callable[[EvaluationRecord], str | None],
    score_fn: Callable[[EvaluationRecord], float],
    threshold: float,
) -> DisparateImpactResult:
    """Return a DI result comparing positive rates across groups.

    - `group_fn(record)` returns a group label, or None to exclude the record.
    - A record is "positive" when `score_fn(record) >= threshold`.
    - `di_ratio = min_positive_rate / max_positive_rate` across groups.
      The 80% rule flags `di_ratio < 0.8`.
    - When only one group exists, `di_ratio` is None and no flag is raised.
    """
    buckets: dict[str, list[EvaluationRecord]] = {}
    for rec in records:
        label = group_fn(rec)
        if label is None:
            continue
        buckets.setdefault(label, []).append(rec)

    if not buckets:
        return DisparateImpactResult(
            group_rates=[],
            reference_group=None,
            di_ratio=None,
            flagged_4_5ths_rule=False,
            notes="No records with group labels.",
        )

    rates: list[GroupRates] = []
    for label, group in sorted(buckets.items()):
        positives = sum(1 for r in group if score_fn(r) >= threshold)
        rate = positives / len(group) if group else 0.0
        rates.append(GroupRates(label=label, n=len(group), positive=positives, positive_rate=rate))

    if len(rates) < 2:
        return DisparateImpactResult(
            group_rates=rates,
            reference_group=rates[0].label,
            di_ratio=None,
            flagged_4_5ths_rule=False,
            notes="Only one group; DI ratio undefined.",
        )

    positive_rates = [g.positive_rate for g in rates]
    max_rate = max(positive_rates)
    min_rate = min(positive_rates)
    di = (min_rate / max_rate) if max_rate > 0 else 1.0
    reference = max(rates, key=lambda g: g.positive_rate).label
    return DisparateImpactResult(
        group_rates=rates,
        reference_group=reference,
        di_ratio=round(di, 4),
        flagged_4_5ths_rule=di < 0.8,
        notes="",
    )


def to_dict(result: DisparateImpactResult) -> dict[str, Any]:
    return {
        "group_rates": [
            {
                "label": g.label,
                "n": g.n,
                "positive": g.positive,
                "positive_rate": round(g.positive_rate, 4),
            }
            for g in result.group_rates
        ],
        "reference_group": result.reference_group,
        "di_ratio": result.di_ratio,
        "flagged_4_5ths_rule": result.flagged_4_5ths_rule,
        "notes": result.notes,
    }
