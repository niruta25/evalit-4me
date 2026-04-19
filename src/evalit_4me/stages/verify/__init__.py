"""Stage 2b/2c — per-citation verification.

Public surface:

* `CitationLookup`, `LookupStatus`        — result types
* `http_client.HTTPClient`                — injectable HTTP wrapper w/ disk cache + backoff
* `citation_exists.lookup_reference`      — CrossRef -> S2 -> OpenAlex cascade
* `citation_exists.verify_references`     — batch wrapper
* `citation_metadata.compare_metadata`    — author/year/title/venue match scoring
* `temporal.check_temporal_consistency`   — no future-dated citations
* `confidence.aggregate_verification`     -> ClaimLedger

Chunk 1.7 (entailment + ORCID) layers on top; Chunk 1.10 orchestrator
runs all of these in sequence.
"""

from evalit_4me.stages.verify.citation_entailment import (
    EntailmentResult,
    EntailmentVerdict,
    check_claim_entailments,
    check_entailment,
    fetch_abstract,
)
from evalit_4me.stages.verify.citation_exists import (
    CitationLookup,
    LookupStatus,
    lookup_reference,
    verify_references,
)
from evalit_4me.stages.verify.citation_metadata import MetadataMatch, compare_metadata
from evalit_4me.stages.verify.confidence import aggregate_verification
from evalit_4me.stages.verify.http_client import HTTPClient, HTTPError
from evalit_4me.stages.verify.orcid import OrcidMatch, lookup_author, lookup_authors
from evalit_4me.stages.verify.temporal import TemporalIssue, check_temporal_consistency

__all__ = [
    "CitationLookup",
    "EntailmentResult",
    "EntailmentVerdict",
    "HTTPClient",
    "HTTPError",
    "LookupStatus",
    "MetadataMatch",
    "OrcidMatch",
    "TemporalIssue",
    "aggregate_verification",
    "check_claim_entailments",
    "check_entailment",
    "check_temporal_consistency",
    "compare_metadata",
    "fetch_abstract",
    "lookup_author",
    "lookup_authors",
    "lookup_reference",
    "verify_references",
]
