"""OpenAI provider adapter.

Uses the official `openai` SDK. Client is injectable for testing. Supports
both `.complete()` (via chat completions) and `.embed()`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from evalit_4me.llm.cost import estimate_cost
from evalit_4me.llm.errors import LLMAuthError, LLMError, LLMRateLimitError
from evalit_4me.llm.protocol import (
    EmbedRequest,
    EmbedResponse,
    LLMRequest,
    LLMResponse,
)


def _default_client() -> Any:
    import openai

    return openai.OpenAI()


@dataclass
class OpenAIProvider:
    client: Any = field(default_factory=_default_client)
    name: str = "openai"

    def complete(self, request: LLMRequest) -> LLMResponse:
        try:
            import openai

            messages: list[dict[str, str]] = []
            if request.system is not None:
                messages.append({"role": "system", "content": request.system})
            messages.append({"role": "user", "content": request.prompt})

            kwargs: dict[str, Any] = {
                "model": request.model,
                "messages": messages,
                "temperature": request.temperature,
                "max_tokens": request.max_tokens or 1024,
            }
            if request.stop:
                kwargs["stop"] = request.stop
            if request.seed is not None:
                kwargs["seed"] = request.seed

            completion = self.client.chat.completions.create(**kwargs)
        except openai.AuthenticationError as exc:  # type: ignore[attr-defined]
            raise LLMAuthError(str(exc)) from exc
        except openai.RateLimitError as exc:  # type: ignore[attr-defined]
            raise LLMRateLimitError(str(exc)) from exc
        except openai.APIError as exc:  # type: ignore[attr-defined]
            raise LLMError(str(exc)) from exc

        choice = completion.choices[0]
        text = choice.message.content or ""
        usage = getattr(completion, "usage", None)
        prompt_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
        completion_tokens = int(getattr(usage, "completion_tokens", 0) or 0)
        return LLMResponse(
            text=text,
            model=request.model,
            provider=self.name,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cost_usd=estimate_cost(request.model, prompt_tokens, completion_tokens),
            cache_hit=False,
            finish_reason=getattr(choice, "finish_reason", None),
        )

    def embed(self, request: EmbedRequest) -> EmbedResponse:
        try:
            import openai

            response = self.client.embeddings.create(
                model=request.model,
                input=request.texts,
            )
        except openai.AuthenticationError as exc:  # type: ignore[attr-defined]
            raise LLMAuthError(str(exc)) from exc
        except openai.RateLimitError as exc:  # type: ignore[attr-defined]
            raise LLMRateLimitError(str(exc)) from exc
        except openai.APIError as exc:  # type: ignore[attr-defined]
            raise LLMError(str(exc)) from exc

        vectors = [list(item.embedding) for item in response.data]
        usage = getattr(response, "usage", None)
        prompt_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
        return EmbedResponse(
            vectors=vectors,
            model=request.model,
            provider=self.name,
            prompt_tokens=prompt_tokens,
            cost_usd=estimate_cost(request.model, prompt_tokens, 0),
            cache_hit=False,
        )
