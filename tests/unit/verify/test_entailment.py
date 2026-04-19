"""Entailment tests: LLM path, keyword fallback, abstract fetch, gold set."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from evalit_4me.contracts import Claim, ClaimType, Severity, SourceSpan, VerificationSource
from evalit_4me.llm.protocol import EmbedRequest, EmbedResponse, LLMRequest, LLMResponse
from evalit_4me.stages.verify.citation_entailment import (
    EntailmentVerdict,
    _parse_entailment_json,
    check_claim_entailments,
    check_entailment,
    fetch_abstract,
)
from evalit_4me.stages.verify.citation_exists import (
    CitationLookup,
    ExternalMetadata,
    LookupStatus,
)
from evalit_4me.stages.verify.http_client import HTTPClient


def _claim(cid: str, text: str, refs: list[str] | None = None) -> Claim:
    return Claim(
        id=cid,
        text=text,
        claim_type=ClaimType.CITATION,
        severity=Severity.HIGH,
        source_span=SourceSpan(section_id="s", char_start=0, char_end=1),
        referenced_citation_ids=refs or [],
    )


@dataclass
class ScriptedLLM:
    """Returns canned JSON keyed on a substring in the claim text."""

    name: str = "scripted"
    script: dict[str, str] = field(default_factory=dict)
    default: str = '{"supported": false, "confidence": 0.1, "rationale": "default"}'

    def complete(self, request: LLMRequest) -> LLMResponse:
        text = self.default
        for cue, resp in self.script.items():
            if cue in request.prompt:
                text = resp
                break
        return LLMResponse(
            text=text,
            model=request.model,
            provider=self.name,
            prompt_tokens=max(1, len(request.prompt) // 4),
            completion_tokens=max(1, len(text) // 4),
        )

    def embed(self, request: EmbedRequest) -> EmbedResponse:
        return EmbedResponse(
            vectors=[[0.0] * 4 for _ in request.texts], model=request.model, provider=self.name
        )


# ---------------------------------------------------------------------------
# _parse_entailment_json
# ---------------------------------------------------------------------------


def test_parse_plain_json():
    assert _parse_entailment_json('{"supported": true, "confidence": 0.9, "rationale": "r"}') == (
        True,
        0.9,
        "r",
    )


def test_parse_fenced_json():
    assert _parse_entailment_json('```json\n{"supported": false}\n```') == (False, 0.5, "")


def test_parse_embedded_in_prose():
    out = _parse_entailment_json('Answer: {"supported": true, "confidence": 0.7}')
    assert out == (True, 0.7, "")


def test_parse_malformed_returns_none():
    assert _parse_entailment_json("not json") is None
    assert _parse_entailment_json("") is None


def test_parse_requires_supported_key():
    assert _parse_entailment_json('{"confidence": 0.8}') is None


# ---------------------------------------------------------------------------
# check_entailment — LLM + fallback paths
# ---------------------------------------------------------------------------


def test_llm_supported():
    claim = _claim("c1", "CLAIM A is established.")
    provider = ScriptedLLM(
        script={
            "CLAIM A": '{"supported": true, "confidence": 0.92, "rationale": "abstract says A."}'
        }
    )
    out = check_entailment(claim, "r1", "Abstract body", provider)
    assert out.verdict == EntailmentVerdict.SUPPORTED
    assert out.method == "llm"
    assert out.confidence > 0.9


def test_llm_not_supported():
    claim = _claim("c2", "CLAIM B is refuted.")
    provider = ScriptedLLM(
        script={"CLAIM B": '{"supported": false, "confidence": 0.88, "rationale": "no support."}'}
    )
    out = check_entailment(claim, "r2", "Abstract text.", provider)
    assert out.verdict == EntailmentVerdict.NOT_SUPPORTED
    assert out.method == "llm"


def test_llm_malformed_falls_back_to_keyword():
    claim = _claim("c3", "transformer attention mechanism for translation")
    provider = ScriptedLLM(default="not json at all")
    abstract = "We introduce the transformer and its attention mechanism for machine translation."
    out = check_entailment(claim, "r", abstract, provider)
    assert out.method == "keyword"
    assert out.verdict == EntailmentVerdict.SUPPORTED


def test_no_abstract_returns_insufficient():
    claim = _claim("c", "anything")
    out = check_entailment(claim, "r", None, ScriptedLLM())
    assert out.verdict == EntailmentVerdict.INSUFFICIENT
    assert out.method == "no_abstract"


def test_no_provider_uses_keyword():
    claim = _claim("c", "graph neural networks molecular prediction")
    out = check_entailment(
        claim, "r", "Graph neural networks for molecular property prediction.", None
    )
    assert out.method == "keyword"
    assert out.verdict == EntailmentVerdict.SUPPORTED


def test_keyword_rejects_unrelated_abstract():
    claim = _claim("c", "we propose a novel transformer architecture")
    out = check_entailment(
        claim, "r", "Cosmology of exoplanets and planetary formation processes.", None
    )
    assert out.verdict == EntailmentVerdict.NOT_SUPPORTED
    assert out.method == "keyword"


# ---------------------------------------------------------------------------
# fetch_abstract
# ---------------------------------------------------------------------------


def test_fetch_abstract_via_doi(tmp_path: Path):
    payload = json.dumps({"abstract": "Sample abstract text.", "title": "T"})

    def fetcher(url, headers):
        if "DOI:" in url:
            return 200, payload
        return 404, ""

    client = HTTPClient(cache_dir=tmp_path / "http", fetcher=fetcher)
    client.backoff_base = 0.0
    out = fetch_abstract("10.1/abc", None, client)
    assert out == "Sample abstract text."


def test_fetch_abstract_via_arxiv(tmp_path: Path):
    payload = json.dumps({"abstract": "arxiv abstract.", "title": "T"})

    def fetcher(url, headers):
        if "arXiv:" in url:
            return 200, payload
        return 404, ""

    client = HTTPClient(cache_dir=tmp_path / "http", fetcher=fetcher)
    client.backoff_base = 0.0
    assert fetch_abstract(None, "1706.03762", client) == "arxiv abstract."


def test_fetch_abstract_missing_returns_none(tmp_path: Path):
    client = HTTPClient(cache_dir=tmp_path / "http", fetcher=lambda u, h: (404, ""))
    client.backoff_base = 0.0
    assert fetch_abstract("10.1/nope", None, client) is None


# ---------------------------------------------------------------------------
# 20-pair gold set — exit gate
# ---------------------------------------------------------------------------


def _gold_pairs() -> list[tuple[str, str, bool]]:
    """(claim_text, abstract_text, is_actually_supported).

    10 SUPPORTED + 10 MISCITED. Our keyword fallback should handle most;
    the LLM path in production should exceed 80%. We test the fallback
    here because it's deterministic — the LLM branch is exercised by
    the scripted tests above.
    """
    supported = [
        (
            "Deep residual networks enable training of very deep architectures.",
            "We present a residual learning framework that eases the training of deep networks.",
        ),
        (
            "Transformers replace recurrence with self-attention.",
            "The Transformer is based solely on attention mechanisms, dispensing with recurrence.",
        ),
        (
            "BERT uses masked language modeling for pretraining.",
            "BERT is pretrained on a masked language model objective.",
        ),
        (
            "Adam combines momentum with adaptive learning rates.",
            "Adam is an algorithm for first-order gradient-based optimization using adaptive estimates.",
        ),
        (
            "Graph neural networks learn representations of nodes.",
            "Graph neural networks propagate and aggregate node representations via message passing.",
        ),
        (
            "Dropout regularization reduces overfitting.",
            "Dropout prevents overfitting by randomly dropping units during training.",
        ),
        (
            "Word2vec learns distributed word representations.",
            "Word2vec produces vector representations of words from large corpora.",
        ),
        (
            "ResNet achieves state-of-the-art ImageNet performance.",
            "ResNet obtains state-of-the-art results on ImageNet classification.",
        ),
        (
            "Variational autoencoders use the reparameterization trick.",
            "VAEs optimize an ELBO using the reparameterization trick for gradient estimation.",
        ),
        (
            "GAN training is an adversarial two-player game.",
            "Generative adversarial networks are trained via a two-player minimax game between generator and discriminator.",
        ),
    ]
    miscited = [
        (
            "Transformers replace recurrence with self-attention.",
            "This paper describes medieval agricultural techniques in the Iberian peninsula.",
        ),
        (
            "BERT uses masked language modeling for pretraining.",
            "We survey 20th-century jazz improvisation traditions.",
        ),
        (
            "Adam combines momentum with adaptive learning rates.",
            "Economic forecasting for coastal fisheries in West Africa.",
        ),
        (
            "GAN training is an adversarial two-player game.",
            "Mineralogical analysis of lunar basalts from the Apollo missions.",
        ),
        (
            "Dropout regularization reduces overfitting.",
            "Cognitive effects of prolonged microgravity on astronauts.",
        ),
        (
            "Variational autoencoders use the reparameterization trick.",
            "Behavioral ecology of migratory songbirds in South America.",
        ),
        (
            "Graph neural networks learn representations of nodes.",
            "A corpus-based study of Shakespearean sonnet rhyme schemes.",
        ),
        (
            "Word2vec learns distributed word representations.",
            "Hydrodynamics of supersonic jets in experimental wind tunnels.",
        ),
        (
            "ResNet achieves state-of-the-art ImageNet performance.",
            "Historical development of constitutional law in ancient Rome.",
        ),
        (
            "Deep residual networks enable training of very deep architectures.",
            "Impacts of climate change on Mediterranean olive cultivation.",
        ),
    ]
    return [(c, a, True) for c, a in supported] + [(c, a, False) for c, a in miscited]


def test_keyword_fallback_hits_80pct_on_gold():
    """Exit gate surrogate: ≥80% accuracy on 20 claim-citation gold pairs
    using the keyword fallback (the LLM path would do better; we can't test
    that deterministically in CI)."""
    pairs = _gold_pairs()
    correct = 0
    for idx, (claim_text, abstract, expected) in enumerate(pairs):
        claim = _claim(f"c{idx}", claim_text)
        out = check_entailment(claim, "r", abstract, None)
        got = out.verdict == EntailmentVerdict.SUPPORTED
        if got == expected:
            correct += 1
    accuracy = correct / len(pairs)
    assert accuracy >= 0.80, f"accuracy={accuracy:.0%} below 80% floor"


# ---------------------------------------------------------------------------
# check_claim_entailments — batch
# ---------------------------------------------------------------------------


def test_check_claim_entailments_batch(tmp_path: Path):
    def fetcher(url, headers):
        if "DOI:" in url:
            return 200, json.dumps({"abstract": "We present a transformer model for translation."})
        return 404, ""

    client = HTTPClient(cache_dir=tmp_path / "http", fetcher=fetcher)
    client.backoff_base = 0.0

    claims = [
        _claim("c1", "we propose a transformer model for translation", refs=["r1"]),
        _claim("c2", "unrelated claim about biology and genetics", refs=["r1"]),
    ]
    lookups = [
        CitationLookup(
            reference_id="r1",
            status=LookupStatus.FOUND,
            source=VerificationSource.CROSSREF,
            metadata=ExternalMetadata(doi="10.1/x", title="T"),
        )
    ]
    out = check_claim_entailments(claims, lookups, client, None)  # keyword fallback
    assert len(out) == 2
    assert out[0].verdict == EntailmentVerdict.SUPPORTED
    assert out[1].verdict == EntailmentVerdict.NOT_SUPPORTED


def test_check_claim_entailments_skips_missing_citations(tmp_path: Path):
    client = HTTPClient(cache_dir=tmp_path / "http", fetcher=lambda u, h: (404, ""))
    client.backoff_base = 0.0
    claims = [_claim("c1", "x", refs=["missing"])]
    lookups = [
        CitationLookup(
            reference_id="missing",
            status=LookupStatus.NOT_FOUND,
            source=VerificationSource.NONE,
        )
    ]
    assert check_claim_entailments(claims, lookups, client, None) == []
