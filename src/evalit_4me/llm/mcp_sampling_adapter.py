"""MCP sampling adapter — route `LLMRequest`s through the MCP client.

The Claude Code plugin spawns this MCP server as a child process and
owns the LLM credentials. Rather than asking the user for an
`ANTHROPIC_API_KEY` in the server's shell, we use the MCP
`sampling/createMessage` capability: the server asks the client to run
a completion on its behalf, with whatever provider + auth the client
already has.

Not every MCP client supports sampling. When unsupported, the adapter
raises `SamplingUnsupportedError` — callers fall back to heuristic mode.

Concurrency model:
  FastMCP tool handlers run inside the server's asyncio event loop. The
  pipeline code that calls `provider.complete()` is synchronous. To
  bridge the two without rewriting every stage, `complete()` detects
  whether it is already inside a running loop and uses
  `run_coroutine_threadsafe` to dispatch the async sampling call from a
  worker thread. The pipeline thread blocks on the future result.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

from evalit_4me.llm.cost import estimate_cost
from evalit_4me.llm.errors import LLMError, LLMUnsupportedError
from evalit_4me.llm.protocol import (
    EmbedRequest,
    EmbedResponse,
    LLMRequest,
    LLMResponse,
)

log = logging.getLogger("evalit.llm.mcp_sampling")

DEFAULT_TIMEOUT_SEC = 120


class SamplingUnsupportedError(LLMError):
    """The MCP client does not implement `sampling/createMessage`."""


@dataclass
class McpSamplingProvider:
    """Route LLM completions through the MCP host client.

    Constructed once per tool invocation with the tool's `ctx` so every
    request reaches the same client session.
    """

    ctx: Any  # mcp.server.fastmcp.Context — avoided as import to keep tests light
    loop: asyncio.AbstractEventLoop | None = None
    timeout_sec: float = DEFAULT_TIMEOUT_SEC
    name: str = "mcp-sampling"
    _sampling_unavailable: bool = field(default=False, init=False, repr=False)

    def complete(self, request: LLMRequest) -> LLMResponse:
        if self._sampling_unavailable:
            raise SamplingUnsupportedError(
                "MCP client does not support sampling; heuristic fallback in effect."
            )
        try:
            result = self._run_async(self._call_create_message(request))
        except SamplingUnsupportedError:
            self._sampling_unavailable = True
            raise
        return self._to_llm_response(request, result)

    def embed(self, request: EmbedRequest) -> EmbedResponse:
        del request
        # MCP doesn't expose embeddings. This is a hard unsupported —
        # callers should route embed work elsewhere or skip it.
        raise LLMUnsupportedError(
            "MCP sampling does not expose embeddings. Use a direct provider "
            "(OpenAI/Voyage) for embed() if required."
        )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    async def _call_create_message(self, request: LLMRequest):
        """Build the MCP sampling request and await the client response."""
        from mcp.shared.exceptions import McpError
        from mcp.types import ModelHint, ModelPreferences, SamplingMessage, TextContent

        session = self.ctx.session
        messages = [
            SamplingMessage(
                role="user",
                content=TextContent(type="text", text=request.prompt),
            )
        ]
        preferences = ModelPreferences(
            hints=[ModelHint(name=request.model)] if request.model else None,
            intelligencePriority=0.7,
            speedPriority=0.3,
        )
        try:
            return await session.create_message(
                messages=messages,
                max_tokens=request.max_tokens or 1024,
                system_prompt=request.system,
                temperature=request.temperature,
                stop_sequences=request.stop,
                model_preferences=preferences,
            )
        except McpError as exc:
            # -32601 method not found or -32603 unsupported capability
            # both map to "client won't do sampling".
            if _looks_like_unsupported(exc):
                raise SamplingUnsupportedError(str(exc)) from exc
            raise LLMError(str(exc)) from exc

    def _run_async(self, coro):
        """Bridge sync pipeline code to the async sampling call."""
        loop = self.loop or _find_running_loop()
        if loop is None:
            # No event loop anywhere — caller is fully sync (e.g. a test
            # without an asyncio context). Run a fresh loop.
            return asyncio.run(asyncio.wait_for(coro, timeout=self.timeout_sec))

        if _is_current_thread_loop(loop):
            # Rare: the provider is being invoked from inside the loop's
            # own thread. Safe only if the caller is async itself — sync
            # blocking here would deadlock. We refuse loudly.
            raise LLMError(
                "McpSamplingProvider.complete() called from the MCP event-loop "
                "thread; pipeline stages must run in a worker thread."
            )

        future = asyncio.run_coroutine_threadsafe(coro, loop)
        return future.result(timeout=self.timeout_sec)

    def _to_llm_response(self, request: LLMRequest, result) -> LLMResponse:
        text = _extract_text(result.content)
        # MCP sampling responses don't always report token usage. Estimate
        # from character counts so cost tracking has something to show.
        prompt_tokens = len(request.prompt) // 4
        completion_tokens = len(text) // 4
        return LLMResponse(
            text=text,
            model=getattr(result, "model", None) or request.model,
            provider=self.name,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cost_usd=estimate_cost(request.model, prompt_tokens, completion_tokens),
            cache_hit=False,
            finish_reason=getattr(result, "stopReason", None),
        )


def _extract_text(content) -> str:
    """Sampling responses can be a single content block or a list."""
    if content is None:
        return ""
    # Single TextContent
    if hasattr(content, "type") and content.type == "text":
        return getattr(content, "text", "") or ""
    # List of blocks
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if hasattr(block, "type") and block.type == "text":
                parts.append(getattr(block, "text", "") or "")
        return "".join(parts)
    return ""


def _looks_like_unsupported(exc: Exception) -> bool:
    msg = str(exc).lower()
    return (
        "method not found" in msg or "not supported" in msg or ("sampling" in msg and "not" in msg)
    )


def _find_running_loop() -> asyncio.AbstractEventLoop | None:
    try:
        return asyncio.get_running_loop()
    except RuntimeError:
        return None


def _is_current_thread_loop(loop: asyncio.AbstractEventLoop) -> bool:
    try:
        return asyncio.get_running_loop() is loop
    except RuntimeError:
        return False
