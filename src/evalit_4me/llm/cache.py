"""On-disk content-addressed cache + provider wrapper.

`DiskCache` stores one JSON file per cache key under a cache directory.
`CachingProvider` wraps any `LLMProvider` to add read-through caching and
optional cost tracking; it is itself an `LLMProvider`.

Why file-per-key: simple, inspectable, no SQLite dependency, and hash keys
avoid collisions. For O(millions) entries we would switch to SQLite; for
a typical reviewer-assist run this stays under ~10k files.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from evalit_4me.llm.cost import CostTracker
from evalit_4me.llm.protocol import (
    EmbedRequest,
    EmbedResponse,
    LLMProvider,
    LLMRequest,
    LLMResponse,
)


def _default_cache_dir() -> Path:
    override = os.environ.get("EVALIT_LLM_CACHE_DIR")
    if override:
        return Path(override)
    base = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
    return base / "evalit_4me" / "llm"


@dataclass
class DiskCache:
    root: Path = field(default_factory=_default_cache_dir)

    def __post_init__(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)

    def _path_for(self, key: str, kind: str) -> Path:
        # Shard by first 2 chars to avoid giant single directory.
        return self.root / kind / key[:2] / f"{key}.json"

    def get_completion(self, key: str) -> LLMResponse | None:
        path = self._path_for(key, "complete")
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return LLMResponse.model_validate(data)

    def set_completion(self, key: str, response: LLMResponse) -> None:
        path = self._path_for(key, "complete")
        path.parent.mkdir(parents=True, exist_ok=True)
        # Persist with cache_hit=False so the next read doesn't leak state.
        payload = response.model_copy(update={"cache_hit": False})
        self._atomic_write(path, payload.model_dump_json())

    def get_embedding(self, key: str) -> EmbedResponse | None:
        path = self._path_for(key, "embed")
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return EmbedResponse.model_validate(data)

    def set_embedding(self, key: str, response: EmbedResponse) -> None:
        path = self._path_for(key, "embed")
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = response.model_copy(update={"cache_hit": False})
        self._atomic_write(path, payload.model_dump_json())

    @staticmethod
    def _atomic_write(path: Path, content: str) -> None:
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(content, encoding="utf-8")
        os.replace(tmp, path)


@dataclass
class CachingProvider:
    """Wraps an inner provider with disk cache + optional cost tracking.

    Cache hits are NOT logged to the cost tracker, since no new tokens were
    spent. The returned response has `cache_hit=True`.
    """

    inner: LLMProvider
    cache: DiskCache = field(default_factory=DiskCache)
    tracker: CostTracker | None = None

    @property
    def name(self) -> str:
        return self.inner.name

    def complete(self, request: LLMRequest) -> LLMResponse:
        key = request.cache_key(self.inner.name)
        hit = self.cache.get_completion(key)
        if hit is not None:
            return hit.model_copy(update={"cache_hit": True})
        response = self.inner.complete(request)
        self.cache.set_completion(key, response)
        if self.tracker is not None:
            self.tracker.record(
                provider=response.provider,
                model=response.model,
                prompt_tokens=response.prompt_tokens,
                completion_tokens=response.completion_tokens,
                cost_usd=response.cost_usd,
                kind="complete",
            )
        return response

    def embed(self, request: EmbedRequest) -> EmbedResponse:
        key = request.cache_key(self.inner.name)
        hit = self.cache.get_embedding(key)
        if hit is not None:
            return hit.model_copy(update={"cache_hit": True})
        response = self.inner.embed(request)
        self.cache.set_embedding(key, response)
        if self.tracker is not None:
            self.tracker.record(
                provider=response.provider,
                model=response.model,
                prompt_tokens=response.prompt_tokens,
                completion_tokens=0,
                cost_usd=response.cost_usd,
                kind="embed",
            )
        return response
