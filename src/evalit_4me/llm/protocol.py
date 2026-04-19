"""Provider-agnostic LLM protocol + request/response contracts.

All adapters (Anthropic, OpenAI, Stub) conform to `LLMProvider`. Pipeline
code depends only on this module — never on vendor SDKs directly.
"""

from __future__ import annotations

import hashlib
import json
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, NonNegativeInt


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=False, validate_assignment=True)


# ---------------------------------------------------------------------------
# Request / response
# ---------------------------------------------------------------------------


class LLMRequest(_Strict):
    """A single completion request.

    `stop` is a list (not a single string) so all providers get a uniform
    shape; adapters convert to whatever the SDK expects.
    """

    prompt: str
    model: str
    system: str | None = None
    temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    max_tokens: NonNegativeInt = 1024
    stop: list[str] | None = None
    seed: int | None = None

    def cache_key(self, provider_name: str) -> str:
        """Stable content hash. Any field change invalidates the cache."""
        payload = {
            "provider": provider_name,
            "prompt": self.prompt,
            "model": self.model,
            "system": self.system,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "stop": self.stop,
            "seed": self.seed,
        }
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class LLMResponse(_Strict):
    text: str
    model: str
    provider: str
    prompt_tokens: NonNegativeInt
    completion_tokens: NonNegativeInt
    cost_usd: float = Field(default=0.0, ge=0.0)
    cache_hit: bool = False
    finish_reason: str | None = None


class EmbedRequest(_Strict):
    texts: list[str]
    model: str

    def cache_key(self, provider_name: str) -> str:
        payload = {
            "provider": provider_name,
            "texts": self.texts,
            "model": self.model,
            "kind": "embed",
        }
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class EmbedResponse(_Strict):
    vectors: list[list[float]]
    model: str
    provider: str
    prompt_tokens: NonNegativeInt = 0
    cost_usd: float = Field(default=0.0, ge=0.0)
    cache_hit: bool = False


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class LLMProvider(Protocol):
    """Minimal surface every adapter must implement.

    Adapters may raise `LLMUnsupportedError` from `.embed()` if the vendor
    does not offer embeddings (e.g., Anthropic).
    """

    name: str

    def complete(self, request: LLMRequest) -> LLMResponse: ...

    def embed(self, request: EmbedRequest) -> EmbedResponse: ...
