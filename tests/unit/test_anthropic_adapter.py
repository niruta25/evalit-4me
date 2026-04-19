"""Anthropic adapter tests using an injected mock client.

We mock at the SDK level (the `client` argument) rather than HTTP — this
keeps tests stable across `anthropic-py` minor bumps and focused on our
transformation logic.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import anthropic
import pytest

from evalit_4me.llm.anthropic_adapter import AnthropicProvider
from evalit_4me.llm.errors import LLMAuthError, LLMRateLimitError, LLMUnsupportedError
from evalit_4me.llm.protocol import EmbedRequest, LLMRequest


def _fake_message(text: str, input_tokens: int = 42, output_tokens: int = 17) -> object:
    return SimpleNamespace(
        content=[SimpleNamespace(type="text", text=text)],
        usage=SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens),
        stop_reason="end_turn",
    )


def _client_with_response(response: object) -> MagicMock:
    client = MagicMock()
    client.messages.create.return_value = response
    return client


def test_anthropic_complete_happy_path():
    client = _client_with_response(_fake_message("hello from claude"))
    provider = AnthropicProvider(client=client)

    req = LLMRequest(
        prompt="Say hi",
        model="claude-sonnet-4-6",
        system="be terse",
        temperature=0.0,
        max_tokens=256,
        stop=["\n\n"],
    )
    resp = provider.complete(req)

    assert resp.text == "hello from claude"
    assert resp.provider == "anthropic"
    assert resp.model == "claude-sonnet-4-6"
    assert resp.prompt_tokens == 42
    assert resp.completion_tokens == 17
    assert resp.finish_reason == "end_turn"
    assert resp.cost_usd > 0  # known pricing for sonnet

    # Verify we passed the right arguments to the SDK.
    kwargs = client.messages.create.call_args.kwargs
    assert kwargs["model"] == "claude-sonnet-4-6"
    assert kwargs["max_tokens"] == 256
    assert kwargs["temperature"] == 0.0
    assert kwargs["system"] == "be terse"
    assert kwargs["stop_sequences"] == ["\n\n"]
    assert kwargs["messages"] == [{"role": "user", "content": "Say hi"}]


def test_anthropic_complete_omits_system_when_none():
    client = _client_with_response(_fake_message("ok"))
    provider = AnthropicProvider(client=client)
    provider.complete(LLMRequest(prompt="hi", model="claude-sonnet-4-6"))
    assert "system" not in client.messages.create.call_args.kwargs


def test_anthropic_auth_error_wrapped():
    client = MagicMock()
    client.messages.create.side_effect = anthropic.AuthenticationError(
        message="bad key",
        response=MagicMock(status_code=401),
        body=None,
    )
    provider = AnthropicProvider(client=client)
    with pytest.raises(LLMAuthError):
        provider.complete(LLMRequest(prompt="hi", model="claude-sonnet-4-6"))


def test_anthropic_rate_limit_wrapped():
    client = MagicMock()
    client.messages.create.side_effect = anthropic.RateLimitError(
        message="slow down",
        response=MagicMock(status_code=429),
        body=None,
    )
    provider = AnthropicProvider(client=client)
    with pytest.raises(LLMRateLimitError):
        provider.complete(LLMRequest(prompt="hi", model="claude-sonnet-4-6"))


def test_anthropic_embed_raises_unsupported():
    provider = AnthropicProvider(client=MagicMock())
    with pytest.raises(LLMUnsupportedError):
        provider.embed(EmbedRequest(texts=["hi"], model="irrelevant"))
