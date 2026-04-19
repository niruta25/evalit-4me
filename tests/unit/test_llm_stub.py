"""Stub provider: determinism + shape checks."""

from __future__ import annotations

import math

from evalit_4me.llm.protocol import EmbedRequest, LLMRequest
from evalit_4me.llm.stub import StubProvider


def test_stub_completion_is_deterministic():
    p = StubProvider()
    req = LLMRequest(prompt="hello world", model="stub-model")
    a = p.complete(req)
    b = p.complete(req)
    assert a == b
    assert a.provider == "stub"
    assert a.cost_usd == 0.0
    assert a.cache_hit is False
    assert a.prompt_tokens >= 1
    assert a.completion_tokens >= 1


def test_stub_completion_differs_with_system_prompt():
    p = StubProvider()
    a = p.complete(LLMRequest(prompt="hi", model="m"))
    b = p.complete(LLMRequest(prompt="hi", model="m", system="be terse"))
    assert a.text != b.text


def test_stub_embedding_deterministic_and_normalized():
    p = StubProvider(embedding_dim=16)
    req = EmbedRequest(texts=["alpha", "beta"], model="stub-embed")
    r1 = p.embed(req)
    r2 = p.embed(req)
    assert r1 == r2
    assert len(r1.vectors) == 2
    for vec in r1.vectors:
        assert len(vec) == 16
        norm = math.sqrt(sum(v * v for v in vec))
        assert math.isclose(norm, 1.0, abs_tol=1e-9)


def test_stub_embedding_differs_per_text():
    p = StubProvider()
    r = p.embed(EmbedRequest(texts=["alpha", "beta"], model="m"))
    assert r.vectors[0] != r.vectors[1]
