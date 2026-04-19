"""Anthropic provider adapter.

Uses the official `anthropic` SDK. The client is injectable so unit tests
can pass a mock with the same shape — we never touch HTTP directly, which
keeps tests stable across SDK minor-version bumps.

Anthropic does not offer first-party embeddings; `embed()` raises
`LLMUnsupportedError` so callers fail fast and can route embedding work
through an OpenAI (or future Voyage) adapter instead.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from evalit_4me.llm.cost import estimate_cost
from evalit_4me.llm.errors import (
    LLMAuthError,
    LLMError,
    LLMRateLimitError,
    LLMUnsupportedError,
)
from evalit_4me.llm.protocol import (
    EmbedRequest,
    EmbedResponse,
    LLMRequest,
    LLMResponse,
)


def _default_client() -> Any:
    import anthropic  # imported lazily so tests without the env var still run

    return anthropic.Anthropic()


@dataclass
class AnthropicProvider:
    client: Any = field(default_factory=_default_client)
    name: str = "anthropic"

    def complete(self, request: LLMRequest) -> LLMResponse:
        try:
            import anthropic

            kwargs: dict[str, Any] = {
                "model": request.model,
                "max_tokens": request.max_tokens or 1024,
                "temperature": request.temperature,
                "messages": [{"role": "user", "content": request.prompt}],
            }
            if request.system is not None:
                kwargs["system"] = request.system
            if request.stop:
                kwargs["stop_sequences"] = request.stop

            message = self.client.messages.create(**kwargs)
        except anthropic.AuthenticationError as exc:  # type: ignore[attr-defined]
            raise LLMAuthError(str(exc)) from exc
        except anthropic.RateLimitError as exc:  # type: ignore[attr-defined]
            raise LLMRateLimitError(str(exc)) from exc
        except anthropic.APIError as exc:  # type: ignore[attr-defined]
            raise LLMError(str(exc)) from exc

        text = _extract_text(message)
        prompt_tokens = int(getattr(message.usage, "input_tokens", 0) or 0)
        completion_tokens = int(getattr(message.usage, "output_tokens", 0) or 0)
        return LLMResponse(
            text=text,
            model=request.model,
            provider=self.name,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cost_usd=estimate_cost(request.model, prompt_tokens, completion_tokens),
            cache_hit=False,
            finish_reason=getattr(message, "stop_reason", None),
        )

    def embed(self, request: EmbedRequest) -> EmbedResponse:
        del request
        raise LLMUnsupportedError(
            "Anthropic does not offer first-party embeddings. "
            "Use OpenAIProvider or a dedicated Voyage adapter for embed()."
        )


def _extract_text(message: Any) -> str:
    """Concatenate all text blocks in an Anthropic message."""
    parts: list[str] = []
    for block in getattr(message, "content", []) or []:
        # block may be a pydantic model or a dict depending on SDK version.
        block_type = getattr(block, "type", None) or (
            block.get("type") if isinstance(block, dict) else None
        )
        if block_type != "text":
            continue
        text = getattr(block, "text", None) or (
            block.get("text") if isinstance(block, dict) else None
        )
        if text:
            parts.append(text)
    return "".join(parts)
