"""Stage 1 — Compliance validator.

Deterministic, LLM-free checks that screen obvious submission-policy
violations before any expensive downstream processing happens. Driven
by a YAML config so each venue (NeurIPS / ICLR / blog / journal) can
override the ruleset without code changes.

Triage semantics:
  FAIL         — critical violation; the orchestrator (Chunk 1.10) should
                 short-circuit and skip the remaining pipeline.
  CONDITIONAL  — soft violation; pipeline continues but the issue is
                 surfaced to the reviewer.
  PASS         — no violations.

Critical (FAIL) checks: required sections missing, references section
missing when `min_references > 0`.

Soft (CONDITIONAL) checks: word-count bounds, ethics section absence,
anonymization violations.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, NonNegativeInt

from evalit_4me.contracts import ComplianceCheck, ComplianceReport, Paper, Triage


class ComplianceConfig(BaseModel):
    """Compliance block of a venue config.

    Extra fields are forbidden so rubric / other blocks don't silently
    pollute this model when the full config is parsed loosely elsewhere.
    """

    model_config = ConfigDict(extra="forbid")

    required_sections: list[list[str]] = Field(default_factory=list)
    word_count_min: NonNegativeInt | None = None
    word_count_max: NonNegativeInt | None = None
    min_references: NonNegativeInt | None = None
    require_ethics: bool = False
    ethics_aliases: list[str] = Field(default_factory=list)
    require_anonymization: bool = False


def load_compliance_config(path: Path | str) -> ComplianceConfig:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    compliance_block = data.get("compliance")
    if compliance_block is None:
        raise ValueError(f"Config at {path} has no 'compliance' block.")
    return ComplianceConfig.model_validate(compliance_block)


def check_compliance(paper: Paper, config: ComplianceConfig) -> ComplianceReport:
    """Run all compliance checks and return a `ComplianceReport`.

    The function never raises on policy violations — those surface as
    report entries. It only raises on programmer errors (bad input
    shapes), which Pydantic catches upstream.
    """
    section_checks: list[ComplianceCheck] = []
    format_checks: list[ComplianceCheck] = []
    issues: list[str] = []
    has_critical = False
    has_soft = False

    # --- Required sections ------------------------------------------------
    normalized_titles = [_normalize(s.title) for s in paper.sections]
    for aliases in config.required_sections:
        label = aliases[0] if aliases else "unknown"
        matched = _any_alias_matches(aliases, normalized_titles)
        section_checks.append(
            ComplianceCheck(
                name=f"section_present:{label}",
                passed=matched,
                detail=None if matched else f"No section matches any of {aliases}",
            )
        )
        if not matched:
            has_critical = True
            issues.append(f"Missing required section: {label}")

    # --- References section -----------------------------------------------
    ref_count = len(paper.references)
    min_refs = config.min_references or 0
    refs_ok = ref_count >= min_refs
    section_checks.append(
        ComplianceCheck(
            name="references_present",
            passed=refs_ok,
            detail=f"{ref_count} references found (min {min_refs})",
        )
    )
    if not refs_ok:
        has_critical = True
        issues.append(f"Too few references: {ref_count} < required {min_refs}")

    # --- Word count -------------------------------------------------------
    word_count = _count_words(paper)
    lo = config.word_count_min
    hi = config.word_count_max
    within = (lo is None or word_count >= lo) and (hi is None or word_count <= hi)
    format_checks.append(
        ComplianceCheck(
            name="word_count",
            passed=within,
            detail=f"{word_count} words (min {lo}, max {hi})",
        )
    )
    if not within:
        has_soft = True
        issues.append(f"Word count {word_count} outside [{lo}, {hi}]")

    # --- Ethics section ---------------------------------------------------
    if config.require_ethics:
        ethics_ok = _any_alias_matches(config.ethics_aliases, normalized_titles)
        section_checks.append(
            ComplianceCheck(
                name="ethics_section",
                passed=ethics_ok,
                detail=None if ethics_ok else f"None of {config.ethics_aliases} found",
            )
        )
        if not ethics_ok:
            has_soft = True
            issues.append("Ethics / broader-impact section missing")

    # --- Anonymization ----------------------------------------------------
    if config.require_anonymization:
        anonymized = _looks_anonymized(paper)
        format_checks.append(
            ComplianceCheck(
                name="anonymization",
                passed=anonymized,
                detail=None if anonymized else f"Authors present: {paper.metadata.authors}",
            )
        )
        if not anonymized:
            has_soft = True
            issues.append("Paper does not appear to be anonymized")

    # --- Triage -----------------------------------------------------------
    if has_critical:
        triage = Triage.FAIL
    elif has_soft:
        triage = Triage.CONDITIONAL
    else:
        triage = Triage.PASS

    return ComplianceReport(
        triage=triage,
        section_checks=section_checks,
        format_checks=format_checks,
        issues=issues,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _normalize(title: str) -> str:
    return title.strip().lower()


def _any_alias_matches(aliases: list[str], normalized_titles: list[str]) -> bool:
    """Substring match: an alias is satisfied if it appears in any title."""
    lowered_aliases = [a.strip().lower() for a in aliases if a.strip()]
    for title in normalized_titles:
        for alias in lowered_aliases:
            if alias in title:
                return True
    return False


def _count_words(paper: Paper) -> int:
    total = 0
    if paper.metadata.abstract:
        total += len(paper.metadata.abstract.split())
    for section in paper.sections:
        total += len(section.text.split())
    return total


_ANONYMOUS_MARKERS = {"anonymous", "anon", "anonymized"}


def _looks_anonymized(paper: Paper) -> bool:
    authors = [a.strip().lower() for a in paper.metadata.authors if a.strip()]
    if not authors:
        return True
    return any(marker in author for author in authors for marker in _ANONYMOUS_MARKERS)
