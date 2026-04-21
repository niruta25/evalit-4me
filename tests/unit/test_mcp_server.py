"""Unit tests for the MCP server's provider-fallback cascade.

The full end-to-end review_paper invocation is exercised by ad-hoc live
tests in /tmp/test_sampling.py. These unit tests pin the small pure-
helper behaviors that govern which provider the server picks and the
stable field names it returns.
"""

from __future__ import annotations

import pytest

from evalit_4me.llm.cache import CachingProvider
from evalit_4me.mcp_server.server import (
    LLM_MODE_ANTHROPIC,
    LLM_MODE_HEURISTIC,
    LLM_MODE_SAMPLING,
    _build_anthropic_provider_from_env,
)


def test_llm_mode_constants_are_stable_strings():
    """The skill + downstream consumers key on these; don't rename without a
    coordinated skill update."""
    assert LLM_MODE_SAMPLING == "mcp_sampling"
    assert LLM_MODE_ANTHROPIC == "anthropic_api"
    assert LLM_MODE_HEURISTIC == "heuristic"


def test_anthropic_provider_none_without_env_key(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert _build_anthropic_provider_from_env() is None


def test_anthropic_provider_built_when_env_key_present(monkeypatch: pytest.MonkeyPatch):
    """The adapter should construct a CachingProvider when the key is set.

    We don't validate the key here (the real validation is on the first
    call, which raises LLMAuthError — handled separately by the cascade).
    """
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-key")
    provider = _build_anthropic_provider_from_env()
    assert isinstance(provider, CachingProvider)
    # The underlying adapter is the Anthropic one, wrapped by caching.
    assert provider.inner.__class__.__name__ == "AnthropicProvider"
