"""Stage 5 — Orchestrator.

Drives Stages 1-4 in order and assembles an `EvaluationRecord`. The driver
owns all conditional logic (compliance-FAIL short-circuit, optional network
verification, optional LLM) so individual stages stay narrowly-scoped and
side-effect-free.

Call shape:
    run_pipeline(paper, config, *, provider=None, http_client=None)

Network + LLM are BOTH optional. Pass both as None for a full `--dry-run`
that produces a valid `EvaluationRecord` using only deterministic heuristics.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from evalit_4me import __version__
from evalit_4me.config import VenueConfig
from evalit_4me.contracts import (
    ClaimLedger,
    EvaluationRecord,
    Paper,
    Provenance,
    Triage,
    VerificationResult,
    VerificationSource,
)
from evalit_4me.llm.protocol import LLMProvider
from evalit_4me.stages.claims import decompose_claims
from evalit_4me.stages.compliance import check_compliance
from evalit_4me.stages.depth import analyze_depth
from evalit_4me.stages.rubric import score_rubric
from evalit_4me.stages.verify import (
    CitationLookup,
    EntailmentResult,
    EntailmentVerdict,
    HTTPClient,
    LookupStatus,
    MetadataMatch,
    aggregate_verification,
    check_claim_entailments,
    check_temporal_consistency,
    compare_metadata,
    verify_references,
)


@dataclass(frozen=True)
class PipelineOptions:
    """Runtime toggles that don't belong in the venue config."""

    llm_model: str = "claude-sonnet-4-6"
    include_entailment: bool = True


def run_pipeline(
    paper: Paper,
    config: VenueConfig,
    *,
    provider: LLMProvider | None = None,
    http_client: HTTPClient | None = None,
    options: PipelineOptions | None = None,
) -> EvaluationRecord:
    """Run the 5-stage pipeline and return an `EvaluationRecord`.

    Error policy:
    - Compliance FAIL short-circuits the remaining stages. The returned
      record still contains valid (empty) objects for the skipped stages
      so the dashboard / formatter never has to handle partial shapes.
    - Exceptions are propagated — caller decides how to handle them.
    """
    opts = options or PipelineOptions()
    models: dict[str, str] = {}

    # Stage 1: Compliance (LLM-free).
    compliance = check_compliance(paper, config.compliance)

    if compliance.triage == Triage.FAIL:
        return _short_circuit(paper, compliance, config, opts, models)

    # Stage 2a: Decompose claims.
    claims = decompose_claims(paper, provider) if provider is not None else []
    if provider is not None:
        models["decompose"] = opts.llm_model

    # Stage 2b: Citation existence + metadata + temporal.
    if http_client is not None and paper.references:
        lookups = verify_references(paper.references, http_client)
        matches = _build_match_table(paper.references, lookups)
        temporal = check_temporal_consistency(paper)
    else:
        lookups = []
        matches = {}
        temporal = []

    # Stage 2c: Entailment (optional — only with provider + http_client).
    entailments: list[EntailmentResult] = []
    if (
        http_client is not None
        and opts.include_entailment
        and claims
        and any(lu.status == LookupStatus.FOUND for lu in lookups)
    ):
        entailments = check_claim_entailments(
            claims, lookups, http_client, provider, model=opts.llm_model
        )
        if provider is not None:
            models["entailment"] = opts.llm_model

    # Aggregate -> ClaimLedger. Fold entailment into the ledger afterwards
    # so downstream stages see a single consistent view.
    ledger = aggregate_verification(
        claims=claims, lookups=lookups, matches=matches, temporal=temporal
    )
    if entailments:
        ledger = _merge_entailments(ledger, entailments)

    # Stage 3: Depth.
    depth = analyze_depth(paper)

    # Stage 4: Rubric.
    rubric = score_rubric(paper, ledger, depth, config, provider=provider, model=opts.llm_model)
    if provider is not None:
        models["rubric"] = opts.llm_model

    provenance = _build_provenance(config=config, models=models, options=opts)

    return EvaluationRecord(
        paper=paper,
        compliance=compliance,
        claims=ledger,
        depth=depth,
        rubric=rubric,
        provenance=provenance,
    )


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _short_circuit(
    paper: Paper,
    compliance,
    config: VenueConfig,
    opts: PipelineOptions,
    models: dict[str, str],
) -> EvaluationRecord:
    """Produce a minimal EvaluationRecord when compliance triages FAIL.

    We still run the (zero-cost) heuristics — depth is fine and rubric in
    heuristic mode doesn't make network calls — so the reviewer sees a
    complete record rather than a half-empty one.
    """
    depth = analyze_depth(paper)
    rubric = score_rubric(paper, ClaimLedger(), depth, config, provider=None)
    provenance = _build_provenance(config=config, models=models, options=opts)
    return EvaluationRecord(
        paper=paper,
        compliance=compliance,
        claims=ClaimLedger(),
        depth=depth,
        rubric=rubric,
        provenance=provenance,
    )


def _build_match_table(references, lookups: list[CitationLookup]) -> dict[str, MetadataMatch]:
    refs_by_id = {r.id: r for r in references}
    matches: dict[str, MetadataMatch] = {}
    for lu in lookups:
        if lu.status == LookupStatus.FOUND and lu.metadata is not None:
            ref = refs_by_id.get(lu.reference_id)
            if ref is not None:
                matches[lu.reference_id] = compare_metadata(ref, lu.metadata)
    return matches


def _merge_entailments(ledger: ClaimLedger, entailments: list[EntailmentResult]) -> ClaimLedger:
    """Downgrade verified claims whose entailment came back NOT_SUPPORTED.

    Policy:
    - Any entailment with verdict=NOT_SUPPORTED and confidence>=0.7 for a
      (claim, ref) pair → force `verified=False`, add a note, lower the
      confidence to the entailment's confidence.
    - SUPPORTED entailments don't upgrade (the citation-exists + metadata
      match already provide the upgrade path); they just reinforce.
    """
    by_claim: dict[str, list[EntailmentResult]] = {}
    for e in entailments:
        by_claim.setdefault(e.claim_id, []).append(e)

    updated_results: list[VerificationResult] = []
    halluc_count = 0
    verified_count = 0
    confidence_total = 0.0

    for r in ledger.results:
        es = by_claim.get(r.claim_id, [])
        refuted = [
            e for e in es if e.verdict == EntailmentVerdict.NOT_SUPPORTED and e.confidence >= 0.7
        ]
        if refuted:
            # Downgrade.
            note_parts = [r.notes] if r.notes else []
            note_parts.append(
                "Entailment: "
                + "; ".join(f"{e.reference_id} NOT_SUPPORTED ({e.confidence:.2f})" for e in refuted)
            )
            new = r.model_copy(
                update={
                    "verified": False,
                    "confidence": min(r.confidence, min(e.confidence for e in refuted)),
                    "hallucination_flag": True,
                    "notes": " | ".join(note_parts),
                    "source": r.source
                    if r.source != VerificationSource.NONE
                    else VerificationSource.LLM,
                }
            )
        else:
            new = r
        if new.verified:
            verified_count += 1
        if new.hallucination_flag:
            halluc_count += 1
        confidence_total += new.confidence
        updated_results.append(new)

    mean_confidence = confidence_total / len(updated_results) if updated_results else 0.0
    return ClaimLedger(
        claims=ledger.claims,
        results=updated_results,
        total_claims=ledger.total_claims,
        verified_count=verified_count,
        hallucination_count=halluc_count,
        mean_confidence=round(mean_confidence, 4),
    )


def _build_provenance(
    *,
    config: VenueConfig,
    models: dict[str, str],
    options: PipelineOptions,
) -> Provenance:
    config_hash = _hash_config(config)
    return Provenance(
        evalit_version=__version__,
        config_hash=config_hash,
        llm_models=models,
        seeds={"decompose": 0, "entailment": 0, "rubric": 0},
        cost_usd=0.0,  # Chunk 1.12 will plug in the cost tracker.
    )


def _hash_config(config: VenueConfig) -> str:
    payload = json.dumps(config.model_dump(), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
