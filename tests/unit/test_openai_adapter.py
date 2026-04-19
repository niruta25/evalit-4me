"""OpenAI adapter tests using an injected mock client."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import openai
import pytest

from evalit_4me.llm.errors import LLMAuthError, LLMRateLimitError
from evalit_4me.llm.openai_adapter import OpenAIProvider
from evalit_4me.llm.protocol import EmbedRequest, LLMRequest


def _fake_chat(text: str, prompt_tokens: int = 10, completion_tokens: int = 5) -> object:
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content=text),
                finish_reason="stop",
            )
        ],
        usage=SimpleNamespace(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        ),
    )


def _fake_embeddings(vectors: list[list[float]], prompt_tokens: int = 4) -> object:
    return SimpleNamespace(
        data=[SimpleNamespace(embedding=v) for v in vectors],
        usage=SimpleNamespace(prompt_tokens=prompt_tokens),
    )


def _client_with_chat(response: object) -> MagicMock:
    client = MagicMock()
    client.chat.completions.create.return_value = response
    return client


def test_openai_complete_happy_path():
    client = _client_with_chat(_fake_chat("hi back", prompt_tokens=11, completion_tokens=3))
    provider = OpenAIProvider(client=client)
    req = LLMRequest(
        prompt="hello",
        model="gpt-4o-mini",
        system="be helpful",
        temperature=0.0,
        max_tokens=128,
        stop=["\n"],
        seed=7,
    )
    resp = provider.complete(req)
    assert resp.text == "hi back"
    assert resp.provider == "openai"
    assert resp.prompt_tokens == 11
    assert resp.completion_tokens == 3
    assert resp.finish_reason == "stop"
    assert resp.cost_usd > 0

    kwargs = client.chat.completions.create.call_args.kwargs
    assert kwargs["model"] == "gpt-4o-mini"
    assert kwargs["messages"][0] == {"role": "system", "content": "be helpful"}
    assert kwargs["messages"][1] == {"role": "user", "content": "hello"}
    assert kwargs["stop"] == ["\n"]
    assert kwargs["seed"] == 7


def test_openai_complete_omits_system_when_none():
    client = _client_with_chat(_fake_chat("ok"))
    provider = OpenAIProvider(client=client)
    provider.complete(LLMRequest(prompt="hi", model="gpt-4o-mini"))
    messages = client.chat.completions.create.call_args.kwargs["messages"]
    assert len(messages) == 1
    assert messages[0]["role"] == "user"


def test_openai_auth_error_wrapped():
    client = MagicMock()
    client.chat.completions.create.side_effect = openai.AuthenticationError(
        message="bad key",
        response=MagicMock(status_code=401),
        body=None,
    )
    provider = OpenAIProvider(client=client)
    with pytest.raises(LLMAuthError):
        provider.complete(LLMRequest(prompt="hi", model="gpt-4o-mini"))


def test_openai_rate_limit_wrapped():
    client = MagicMock()
    client.chat.completions.create.side_effect = openai.RateLimitError(
        message="slow down",
        response=MagicMock(status_code=429),
        body=None,
    )
    provider = OpenAIProvider(client=client)
    with pytest.raises(LLMRateLimitError):
        provider.complete(LLMRequest(prompt="hi", model="gpt-4o-mini"))


def test_openai_embed_happy_path():
    client = MagicMock()
    client.embeddings.create.return_value = _fake_embeddings(
        [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]], prompt_tokens=8
    )
    provider = OpenAIProvider(client=client)
    resp = provider.embed(EmbedRequest(texts=["alpha", "beta"], model="text-embedding-3-small"))
    assert len(resp.vectors) == 2
    assert resp.vectors[0] == [0.1, 0.2, 0.3]
    assert resp.provider == "openai"
    assert resp.prompt_tokens == 8
    # known embedding pricing -> non-zero but small
    assert resp.cost_usd > 0
