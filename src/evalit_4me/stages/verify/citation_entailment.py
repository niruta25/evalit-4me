"""Stage 2c-a: entailment check between a claim and its cited paper's abstract.

Two modes:

* **LLM mode** (default) — Sonnet-tier prompt asks whether the abstract
  supports the claim. Returns a structured `EntailmentResult`.
* **Keyword fallback** — triggered when the LLM call fails, when the caller
  asks for it explicitly, or when `provider is None`. Jaccard on stopword-
  filtered tokens. Cheap, deterministic, graceful-degradation surface for
  the plan's top risk ("if entailment accuracy is too low, degrade...").

Abstract fetching uses Semantic Scholar (DOI or arXiv). Callers pass an
`HTTPClient` so we stay consistent with the rest of the verify package.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from enum import StrEnum
from urllib.parse import quote

from evalit_4me.contracts import Claim
from evalit_4me.llm.protocol import LLMProvider, LLMRequest
from evalit_4me.stages.verify.citation_exists import CitationLookup, LookupStatus
from evalit_4me.stages.verify.http_client import HTTPClient, HTTPError

DEFAULT_MODEL = "claude-sonnet-4-6"

S2_ABSTRACT_DOI = "https://api.semanticscholar.org/graph/v1/paper/DOI:{doi}?fields=abstract,title"
S2_ABSTRACT_ARXIV = (
    "https://api.semanticscholar.org/graph/v1/paper/arXiv:{arxiv}?fields=abstract,title"
)


class EntailmentVerdict(StrEnum):
    SUPPORTED = "SUPPORTED"
    NOT_SUPPORTED = "NOT_SUPPORTED"
    INSUFFICIENT = "INSUFFICIENT"  # no abstract available / unable to decide


@dataclass(frozen=True)
class EntailmentResult:
    claim_id: str
    reference_id: str
    verdict: EntailmentVerdict
    confidence: float  # 0..1
    rationale: str
    method: str  # "llm" | "keyword" | "no_abstract"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def fetch_abstract(
    reference_doi: str | None, reference_arxiv: str | None, client: HTTPClient
) -> str | None:
    """Fetch an abstract from Semantic Scholar. Returns None on miss/error."""
    for url_template, key in (
        (S2_ABSTRACT_DOI, reference_doi),
        (S2_ABSTRACT_ARXIV, reference_arxiv),
    ):
        if not key:
            continue
        try:
            data = client.get_json(
                url_template.format(doi=quote(key, safe=""), arxiv=quote(key, safe=""))
            )
        except HTTPError:
            continue
        if not data:
            continue
        abstract = data.get("abstract")
        if isinstance(abstract, str) and abstract.strip():
            return abstract.strip()
    return None


def check_entailment(
    claim: Claim,
    reference_id: str,
    abstract: str | None,
    provider: LLMProvider | None,
    *,
    model: str = DEFAULT_MODEL,
) -> EntailmentResult:
    """Single-pair entailment check.

    If `abstract is None`: return INSUFFICIENT with method="no_abstract".
    If `provider is None`: fall back to keyword.
    Otherwise try LLM, and on any parse failure downgrade to keyword.
    """
    if abstract is None or not abstract.strip():
        return EntailmentResult(
            claim_id=claim.id,
            reference_id=reference_id,
            verdict=EntailmentVerdict.INSUFFICIENT,
            confidence=0.0,
            rationale="No abstract available for cited paper.",
            method="no_abstract",
        )
    if provider is None:
        return _keyword_entailment(claim, reference_id, abstract)

    llm_result = _llm_entailment(claim, reference_id, abstract, provider, model=model)
    if llm_result is not None:
        return llm_result
    # LLM failed to produce parseable output -> graceful fallback.
    return _keyword_entailment(claim, reference_id, abstract)


def check_claim_entailments(
    claims: list[Claim],
    lookups: list[CitationLookup],
    client: HTTPClient,
    provider: LLMProvider | None,
    *,
    model: str = DEFAULT_MODEL,
) -> list[EntailmentResult]:
    """Run entailment for every (claim, referenced_citation) pair.

    Only FOUND citations are checked. Each claim may produce multiple
    results (one per referenced citation).
    """
    lookups_by_id = {lu.reference_id: lu for lu in lookups}
    results: list[EntailmentResult] = []
    abstract_cache: dict[str, str | None] = {}
    for claim in claims:
        for rid in claim.referenced_citation_ids:
            lookup = lookups_by_id.get(rid)
            if lookup is None or lookup.status != LookupStatus.FOUND or lookup.metadata is None:
                continue
            if rid not in abstract_cache:
                abstract_cache[rid] = fetch_abstract(lookup.metadata.doi, None, client)
            abstract = abstract_cache[rid]
            results.append(check_entailment(claim, rid, abstract, provider, model=model))
    return results


# ---------------------------------------------------------------------------
# LLM path
# ---------------------------------------------------------------------------


ENTAILMENT_SYSTEM = """You are a careful scientific reviewer.
Given a claim from a paper and the abstract of the paper it cites, decide
whether the abstract SUPPORTS the claim.

Output rules:
- Return ONLY JSON, no prose.
- Schema: {"supported": true|false, "confidence": 0..1, "rationale": "..."}
- "supported" is true ONLY if the abstract clearly endorses the claim.
- "confidence" reflects how sure you are, not how true the claim is in the world.
- "rationale" is one sentence max, quoting the relevant span if possible.
"""

ENTAILMENT_USER = """Claim: {claim_text}

Abstract of cited paper:
---
{abstract}
---

Return JSON now."""


_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE | re.MULTILINE)
_JSON_OBJ_RE = re.compile(r"\{.*\}", re.DOTALL)


def _llm_entailment(
    claim: Claim,
    reference_id: str,
    abstract: str,
    provider: LLMProvider,
    *,
    model: str,
) -> EntailmentResult | None:
    request = LLMRequest(
        prompt=ENTAILMENT_USER.format(claim_text=claim.text, abstract=abstract),
        system=ENTAILMENT_SYSTEM,
        model=model,
        temperature=0.0,
        max_tokens=256,
        seed=0,
    )
    response = provider.complete(request)
    parsed = _parse_entailment_json(response.text)
    if parsed is None:
        return None
    supported, confidence, rationale = parsed
    verdict = EntailmentVerdict.SUPPORTED if supported else EntailmentVerdict.NOT_SUPPORTED
    return EntailmentResult(
        claim_id=claim.id,
        reference_id=reference_id,
        verdict=verdict,
        confidence=max(0.0, min(1.0, confidence)),
        rationale=rationale[:500],
        method="llm",
    )


def _parse_entailment_json(text: str) -> tuple[bool, float, str] | None:
    """Parse `{"supported": bool, "confidence": 0..1, "rationale": str}`."""
    candidate = _FENCE_RE.sub("", text).strip()
    if not candidate:
        return None
    obj: dict | None = None
    try:
        loaded = json.loads(candidate)
        if isinstance(loaded, dict):
            obj = loaded
    except json.JSONDecodeError:
        m = _JSON_OBJ_RE.search(candidate)
        if m:
            try:
                loaded = json.loads(m.group(0))
                if isinstance(loaded, dict):
                    obj = loaded
            except json.JSONDecodeError:
                return None
    if obj is None:
        return None
    if "supported" not in obj:
        return None
    supported = bool(obj.get("supported"))
    confidence = float(obj.get("confidence", 0.5))
    rationale = str(obj.get("rationale", ""))
    return supported, confidence, rationale


# ---------------------------------------------------------------------------
# Keyword fallback
# ---------------------------------------------------------------------------


_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9\-]+")
# Tiny stopword list — we only need to strip the most common noise words,
# not do serious NLP. Keeping this hardcoded avoids an NLTK dep.
_STOPWORDS = {
    "the",
    "a",
    "an",
    "and",
    "or",
    "of",
    "in",
    "on",
    "at",
    "to",
    "for",
    "with",
    "from",
    "by",
    "is",
    "are",
    "was",
    "were",
    "be",
    "been",
    "being",
    "this",
    "that",
    "these",
    "those",
    "we",
    "our",
    "us",
    "it",
    "its",
    "as",
    "can",
    "may",
    "has",
    "have",
    "had",
}

KEYWORD_SUPPORT_THRESHOLD = 0.25


def _keyword_entailment(claim: Claim, reference_id: str, abstract: str) -> EntailmentResult:
    claim_tokens = _content_tokens(claim.text)
    abstract_tokens = _content_tokens(abstract)
    if not claim_tokens or not abstract_tokens:
        return EntailmentResult(
            claim_id=claim.id,
            reference_id=reference_id,
            verdict=EntailmentVerdict.INSUFFICIENT,
            confidence=0.0,
            rationale="Keyword fallback: empty tokenization.",
            method="keyword",
        )
    overlap = claim_tokens & abstract_tokens
    jaccard = len(overlap) / len(claim_tokens | abstract_tokens)
    # Recall-on-claim: what fraction of the claim's keywords appear?
    recall = len(overlap) / len(claim_tokens)
    score = max(jaccard, recall / 2)
    supported = recall >= KEYWORD_SUPPORT_THRESHOLD
    verdict = EntailmentVerdict.SUPPORTED if supported else EntailmentVerdict.NOT_SUPPORTED
    return EntailmentResult(
        claim_id=claim.id,
        reference_id=reference_id,
        verdict=verdict,
        confidence=round(min(1.0, score), 4),
        rationale=(
            f"Keyword fallback: {len(overlap)}/{len(claim_tokens)} claim tokens "
            f"found in abstract (recall={recall:.2f})"
        ),
        method="keyword",
    )


def _content_tokens(text: str) -> set[str]:
    return {
        t.lower() for t in _TOKEN_RE.findall(text) if t.lower() not in _STOPWORDS and len(t) > 2
    }
