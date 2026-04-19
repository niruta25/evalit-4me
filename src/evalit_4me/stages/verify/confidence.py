"""Aggregate per-claim `VerificationResult`s from lookup + metadata + temporal.

Reads:
    claims       — list[Claim] from Stage 2a
    lookups      — per-reference CitationLookup outcomes
    matches      — per-reference MetadataMatch scores (keyed by reference_id)
    temporal     — list[TemporalIssue] (by reference_id)

Emits one `VerificationResult` per `Claim`. Claims with no cited refs are
marked unverified at Stage 2b (no signal yet — Chunk 1.7 entailment may
upgrade them); claims whose referenced refs all resolve cleanly are
verified with confidence = mean(match_overall).

Hallucination flag is set when at least one referenced ref is NOT_FOUND —
§4.2 of the IEEE chapter: a single unresolvable citation attached to a
claim is enough to flag that claim.
"""

from __future__ import annotations

from evalit_4me.contracts import (
    Claim,
    ClaimLedger,
    ClaimType,
    VerificationResult,
    VerificationSource,
)
from evalit_4me.stages.verify.citation_exists import CitationLookup, LookupStatus
from evalit_4me.stages.verify.citation_metadata import MetadataMatch
from evalit_4me.stages.verify.temporal import TemporalIssue


def aggregate_verification(
    *,
    claims: list[Claim],
    lookups: list[CitationLookup],
    matches: dict[str, MetadataMatch],
    temporal: list[TemporalIssue],
) -> ClaimLedger:
    lookups_by_id = {lu.reference_id: lu for lu in lookups}
    temporal_by_id = {t.reference_id: t for t in temporal}

    results: list[VerificationResult] = []
    for claim in claims:
        result = _verify_claim(
            claim=claim,
            lookups_by_id=lookups_by_id,
            matches=matches,
            temporal_by_id=temporal_by_id,
        )
        results.append(result)

    return _build_ledger(claims=claims, results=results)


def _verify_claim(
    *,
    claim: Claim,
    lookups_by_id: dict[str, CitationLookup],
    matches: dict[str, MetadataMatch],
    temporal_by_id: dict[str, TemporalIssue],
) -> VerificationResult:
    # Claims with no referenced citations: Stage 2b has no signal. Mark
    # unverified, confidence=0, but do NOT flag as hallucination.
    if not claim.referenced_citation_ids:
        notes = None
        if claim.claim_type == ClaimType.CITATION:
            notes = "Categorized CITATION but no referenced citation ids; check extraction."
        return VerificationResult(
            claim_id=claim.id,
            verified=False,
            confidence=0.0,
            source=VerificationSource.NONE,
            evidence=None,
            hallucination_flag=False,
            notes=notes,
        )

    ref_outcomes = [lookups_by_id.get(rid) for rid in claim.referenced_citation_ids]
    missing = [
        rid
        for rid, lu in zip(claim.referenced_citation_ids, ref_outcomes, strict=True)
        if lu is None or lu.status == LookupStatus.NOT_FOUND
    ]
    errored = [
        rid
        for rid, lu in zip(claim.referenced_citation_ids, ref_outcomes, strict=True)
        if lu is not None and lu.status == LookupStatus.ERROR
    ]
    temporal_hits = [rid for rid in claim.referenced_citation_ids if rid in temporal_by_id]

    if missing:
        evidence = _format_missing_evidence(missing)
        return VerificationResult(
            claim_id=claim.id,
            verified=False,
            confidence=0.0,
            source=_dominant_source(ref_outcomes),
            evidence=evidence,
            hallucination_flag=True,
            notes=f"{len(missing)}/{len(claim.referenced_citation_ids)} citations unresolved",
        )

    if errored:
        return VerificationResult(
            claim_id=claim.id,
            verified=False,
            confidence=0.0,
            source=VerificationSource.NONE,
            evidence=None,
            hallucination_flag=False,
            notes=f"Resolver errored on refs: {', '.join(errored)}",
        )

    # Everything found. Use metadata match as confidence.
    match_scores: list[float] = []
    for rid in claim.referenced_citation_ids:
        m = matches.get(rid)
        if m is not None:
            match_scores.append(m.overall)
    confidence = sum(match_scores) / len(match_scores) if match_scores else 1.0

    notes = None
    if temporal_hits:
        notes = f"Temporal issue on refs: {', '.join(temporal_hits)}"
        confidence = min(confidence, 0.3)

    verified = confidence >= 0.6 and not temporal_hits
    hallucination_flag = bool(temporal_hits)

    return VerificationResult(
        claim_id=claim.id,
        verified=verified,
        confidence=round(confidence, 4),
        source=_dominant_source(ref_outcomes),
        evidence=_format_evidence(ref_outcomes),
        hallucination_flag=hallucination_flag,
        notes=notes,
    )


def _dominant_source(outcomes: list[CitationLookup | None]) -> VerificationSource:
    for lu in outcomes:
        if lu is not None and lu.status == LookupStatus.FOUND:
            return lu.source
    return VerificationSource.NONE


def _format_evidence(outcomes: list[CitationLookup | None]) -> str:
    parts: list[str] = []
    for lu in outcomes:
        if lu is None or lu.metadata is None:
            continue
        md = lu.metadata
        parts.append(f"{lu.reference_id}: {md.title or '?'} ({md.year or '?'}) via {lu.source}")
    return " | ".join(parts) if parts else ""


def _format_missing_evidence(missing_ids: list[str]) -> str:
    return "Unresolvable citations: " + ", ".join(missing_ids)


def _build_ledger(*, claims: list[Claim], results: list[VerificationResult]) -> ClaimLedger:
    verified_count = sum(1 for r in results if r.verified)
    halluc_count = sum(1 for r in results if r.hallucination_flag)
    mean_confidence = sum(r.confidence for r in results) / len(results) if results else 0.0
    return ClaimLedger(
        claims=claims,
        results=results,
        total_claims=len(claims),
        verified_count=verified_count,
        hallucination_count=halluc_count,
        mean_confidence=round(mean_confidence, 4),
    )
