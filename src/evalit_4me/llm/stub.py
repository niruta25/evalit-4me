"""Deterministic stub provider for `--dry-run` mode and unit tests.

Completion output is a fixed template keyed on the prompt hash, so repeated
calls with the same request yield byte-identical responses (required for
snapshot tests). Embedding vectors are seeded from the text hash.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass

from evalit_4me.llm.protocol import (
    EmbedRequest,
    EmbedResponse,
    LLMRequest,
    LLMResponse,
)


def _seed(text: str) -> int:
    return int(hashlib.sha256(text.encode("utf-8")).hexdigest()[:16], 16)


def _fake_vector(text: str, dim: int = 16) -> list[float]:
    """Normalized pseudo-vector deterministic in `text`.

    We build a vector from the text's SHA-256 digest (stretched as needed)
    and L2-normalize it so downstream cosine math behaves sanely.
    """
    raw = hashlib.sha256(text.encode("utf-8")).digest()
    # Stretch: repeat digest until we have >= dim bytes.
    while len(raw) < dim:
        raw += hashlib.sha256(raw).digest()
    values = [(b - 127.5) / 127.5 for b in raw[:dim]]
    norm = math.sqrt(sum(v * v for v in values)) or 1.0
    return [v / norm for v in values]


@dataclass
class StubProvider:
    """Zero-cost, zero-network, fully deterministic provider."""

    name: str = "stub"
    default_model: str = "stub-model"
    embedding_dim: int = 16

    def complete(self, request: LLMRequest) -> LLMResponse:
        digest = hashlib.sha256(f"{request.system or ''}\n{request.prompt}".encode()).hexdigest()[
            :12
        ]
        text = f"STUB[{digest}] {request.prompt[:120]}"
        prompt_tokens = max(1, len(request.prompt) // 4)
        completion_tokens = max(1, len(text) // 4)
        return LLMResponse(
            text=text,
            model=request.model,
            provider=self.name,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cost_usd=0.0,
            cache_hit=False,
            finish_reason="stop",
        )

    def embed(self, request: EmbedRequest) -> EmbedResponse:
        vectors = [_fake_vector(t, self.embedding_dim) for t in request.texts]
        return EmbedResponse(
            vectors=vectors,
            model=request.model,
            provider=self.name,
            prompt_tokens=sum(max(1, len(t) // 4) for t in request.texts),
            cost_usd=0.0,
            cache_hit=False,
        )
