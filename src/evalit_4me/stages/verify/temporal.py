"""Temporal consistency: flag citations that predate or post-date what
the paper could plausibly cite.

Two failure modes:
1. **Future citation** — the cited paper's year is later than the paper's
   own publication year. This is almost always a fabrication or a sloppy
   bibliography.
2. **Suspiciously old** — optional bound (`max_age_years`) for fields where
   a 50-year-old citation is improbable.

We don't flag "cited year > current year" here because `Paper.metadata.year`
may be None; the orchestrator is the right layer to fall back to "today".
"""

from __future__ import annotations

from dataclasses import dataclass

from evalit_4me.contracts import Paper, Reference


@dataclass(frozen=True)
class TemporalIssue:
    reference_id: str
    reason: str
    reference_year: int | None
    paper_year: int | None


def check_temporal_consistency(
    paper: Paper,
    *,
    current_year: int | None = None,
    max_age_years: int | None = None,
) -> list[TemporalIssue]:
    """Return one `TemporalIssue` per reference that fails a check.

    `current_year` is used when `paper.metadata.year` is None — pass the
    current calendar year. `max_age_years` triggers a "suspiciously old"
    check; when None, that check is skipped.
    """
    cutoff = paper.metadata.year or current_year
    issues: list[TemporalIssue] = []
    for ref in paper.references:
        issue = _check_one(ref, cutoff=cutoff, max_age_years=max_age_years)
        if issue is not None:
            issues.append(issue)
    return issues


def _check_one(
    ref: Reference,
    *,
    cutoff: int | None,
    max_age_years: int | None,
) -> TemporalIssue | None:
    if ref.year is None:
        return None
    if cutoff is not None and ref.year > cutoff:
        return TemporalIssue(
            reference_id=ref.id,
            reason=f"Citation year {ref.year} is after paper year {cutoff}",
            reference_year=ref.year,
            paper_year=cutoff,
        )
    if max_age_years is not None and cutoff is not None and ref.year < cutoff - max_age_years:
        return TemporalIssue(
            reference_id=ref.id,
            reason=(
                f"Citation year {ref.year} is more than {max_age_years} years "
                f"older than paper year {cutoff}"
            ),
            reference_year=ref.year,
            paper_year=cutoff,
        )
    return None
