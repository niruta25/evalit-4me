"""Tests for `McpSamplingProvider`.

These tests do not spin up a real MCP server — they build a fake
`Context` with a mock `session.create_message` coroutine and verify the
adapter's sync-over-async bridge, unsupported-capability detection, and
response shape.
"""

from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass
from typing import Any

import pytest

from evalit_4me.llm.errors import LLMError, LLMUnsupportedError
from evalit_4me.llm.mcp_sampling_adapter import (
    McpSamplingProvider,
    SamplingUnsupportedError,
)
from evalit_4me.llm.protocol import EmbedRequest, LLMRequest


@dataclass
class _FakeTextContent:
    text: str
    type: str = "text"


@dataclass
class _FakeResult:
    content: Any
    model: str = "claude-sonnet"
    stopReason: str = "endTurn"


class _FakeSession:
    """Minimal stand-in for `mcp.server.session.ServerSession`."""

    def __init__(
        self,
        *,
        text: str = "stub-response",
        raise_unsupported: bool = False,
        raise_other: bool = False,
    ) -> None:
        self.text = text
        self.raise_unsupported = raise_unsupported
        self.raise_other = raise_other
        self.calls: list[dict[str, Any]] = []

    async def create_message(self, **kwargs):
        self.calls.append(kwargs)
        if self.raise_unsupported:
            from mcp.shared.exceptions import McpError
            from mcp.types import ErrorData

            raise McpError(
                ErrorData(code=-32601, message="Method not found: sampling/createMessage")
            )
        if self.raise_other:
            from mcp.shared.exceptions import McpError
            from mcp.types import ErrorData

            raise McpError(ErrorData(code=-32000, message="transient error"))
        return _FakeResult(content=_FakeTextContent(text=self.text))


class _FakeContext:
    def __init__(self, session: _FakeSession) -> None:
        self.session = session


def _req(prompt: str = "hello") -> LLMRequest:
    return LLMRequest(prompt=prompt, model="claude-sonnet", max_tokens=32)


def test_complete_returns_llm_response_from_sampling():
    ctx = _FakeContext(_FakeSession(text="world"))
    provider = McpSamplingProvider(ctx=ctx)

    response = provider.complete(_req("hello"))

    assert response.text == "world"
    assert response.provider == "mcp-sampling"
    assert response.model == "claude-sonnet"
    # Tokens estimated from char counts when sampling doesn't report them.
    assert response.prompt_tokens > 0
    assert response.completion_tokens > 0


def test_complete_raises_sampling_unsupported_when_method_not_found():
    ctx = _FakeContext(_FakeSession(raise_unsupported=True))
    provider = McpSamplingProvider(ctx=ctx)

    with pytest.raises(SamplingUnsupportedError):
        provider.complete(_req())


def test_sampling_unsupported_cached_after_first_failure():
    session = _FakeSession(raise_unsupported=True)
    ctx = _FakeContext(session)
    provider = McpSamplingProvider(ctx=ctx)

    with pytest.raises(SamplingUnsupportedError):
        provider.complete(_req())
    # Second call should short-circuit without touching the session again.
    with pytest.raises(SamplingUnsupportedError):
        provider.complete(_req("another"))

    assert len(session.calls) == 1


def test_other_mcp_error_surfaces_as_llm_error():
    ctx = _FakeContext(_FakeSession(raise_other=True))
    provider = McpSamplingProvider(ctx=ctx)

    with pytest.raises(LLMError):
        provider.complete(_req())


def test_embed_is_unsupported():
    ctx = _FakeContext(_FakeSession())
    provider = McpSamplingProvider(ctx=ctx)
    with pytest.raises(LLMUnsupportedError):
        provider.embed(EmbedRequest(texts=["a"], model="anything"))


def test_sync_complete_works_inside_running_loop_via_worker_thread():
    """Simulates the MCP server topology: a background asyncio loop
    running in thread A, pipeline calling provider.complete() from thread B.
    """
    loop = asyncio.new_event_loop()
    done = threading.Event()

    def _loop_runner():
        asyncio.set_event_loop(loop)
        try:
            loop.run_forever()
        finally:
            done.set()

    t = threading.Thread(target=_loop_runner, daemon=True)
    t.start()
    try:
        ctx = _FakeContext(_FakeSession(text="from-loop"))
        provider = McpSamplingProvider(ctx=ctx, loop=loop)
        response = provider.complete(_req("hi"))
        assert response.text == "from-loop"
    finally:
        loop.call_soon_threadsafe(loop.stop)
        done.wait(timeout=2)
        loop.close()
