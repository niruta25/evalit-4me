"""Protocol-level tests: request/response validation + cache-key stability."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from evalit_4me.llm.protocol import (
    EmbedRequest,
    EmbedResponse,
    LLMRequest,
    LLMResponse,
)


def test_llm_request_defaults():
    req = LLMRequest(prompt="hi", model="claude-sonnet-4-6")
    assert req.temperature == 0.0
    assert req.max_tokens == 1024
    assert req.stop is None


def test_llm_request_rejects_bad_temperature():
    with pytest.raises(ValidationError):
        LLMRequest(prompt="hi", model="m", temperature=-0.1)
    with pytest.raises(ValidationError):
        LLMRequest(prompt="hi", model="m", temperature=2.5)


def test_llm_request_extra_field_rejected():
    with pytest.raises(ValidationError):
        LLMRequest.model_validate({"prompt": "hi", "model": "m", "mystery_flag": True})


def test_cache_key_is_stable_and_sensitive():
    a = LLMRequest(prompt="hi", model="m", system="s", temperature=0.0)
    b = LLMRequest(prompt="hi", model="m", system="s", temperature=0.0)
    assert a.cache_key("anthropic") == b.cache_key("anthropic")

    # any field change flips the key
    c = LLMRequest(prompt="hi", model="m", system="s", temperature=0.1)
    assert a.cache_key("anthropic") != c.cache_key("anthropic")

    # provider name is part of the key (Anthropic "hi" != OpenAI "hi")
    assert a.cache_key("anthropic") != a.cache_key("openai")


def test_llm_response_cost_non_negative():
    with pytest.raises(ValidationError):
        LLMResponse(
            text="hi",
            model="m",
            provider="p",
            prompt_tokens=1,
            completion_tokens=1,
            cost_usd=-0.01,
        )


def test_embed_request_cache_key_stable():
    a = EmbedRequest(texts=["a", "b"], model="text-embedding-3-small")
    b = EmbedRequest(texts=["a", "b"], model="text-embedding-3-small")
    assert a.cache_key("openai") == b.cache_key("openai")
    c = EmbedRequest(texts=["a", "c"], model="text-embedding-3-small")
    assert a.cache_key("openai") != c.cache_key("openai")


def test_embed_response_round_trip():
    r = EmbedResponse(
        vectors=[[0.1, 0.2], [0.3, 0.4]],
        model="m",
        provider="p",
        prompt_tokens=4,
        cost_usd=0.0001,
    )
    assert EmbedResponse.model_validate_json(r.model_dump_json()) == r
