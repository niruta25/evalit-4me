"""Disk cache + CachingProvider wrapper."""

from __future__ import annotations

from pathlib import Path

from evalit_4me.llm.cache import CachingProvider, DiskCache
from evalit_4me.llm.cost import CostTracker
from evalit_4me.llm.protocol import EmbedRequest, LLMRequest
from evalit_4me.llm.stub import StubProvider


def test_disk_cache_miss_then_hit(tmp_path: Path):
    cache = DiskCache(root=tmp_path / "llm")
    inner = StubProvider()
    wrapper = CachingProvider(inner=inner, cache=cache)
    req = LLMRequest(prompt="hello", model="stub-model")

    first = wrapper.complete(req)
    assert first.cache_hit is False

    second = wrapper.complete(req)
    assert second.cache_hit is True
    # Body identical except the cache_hit flag.
    assert second.model_copy(update={"cache_hit": False}) == first


def test_cache_records_cost_only_on_miss(tmp_path: Path):
    cache = DiskCache(root=tmp_path / "llm")
    log = tmp_path / "cost.jsonl"
    tracker = CostTracker(log_path=log)
    wrapper = CachingProvider(
        inner=StubProvider(),
        cache=cache,
        tracker=tracker,
    )

    req = LLMRequest(prompt="hi", model="m")
    wrapper.complete(req)  # miss -> recorded
    wrapper.complete(req)  # hit  -> not recorded
    wrapper.complete(req)  # hit  -> not recorded

    assert len(tracker.entries()) == 1


def test_cache_key_isolation_across_providers(tmp_path: Path):
    """Same request on two providers must not share cache entries."""
    cache = DiskCache(root=tmp_path / "llm")
    a = CachingProvider(inner=StubProvider(name="anthropic"), cache=cache)
    b = CachingProvider(inner=StubProvider(name="openai"), cache=cache)
    req = LLMRequest(prompt="hi", model="m")
    a.complete(req)
    # Miss on the other provider because the cache key includes provider name.
    r = b.complete(req)
    assert r.cache_hit is False


def test_embedding_cache_miss_then_hit(tmp_path: Path):
    cache = DiskCache(root=tmp_path / "llm")
    wrapper = CachingProvider(inner=StubProvider(), cache=cache)
    req = EmbedRequest(texts=["a", "b"], model="stub-embed")

    first = wrapper.embed(req)
    assert first.cache_hit is False
    second = wrapper.embed(req)
    assert second.cache_hit is True
    assert second.vectors == first.vectors


def test_cache_file_layout_is_sharded(tmp_path: Path):
    cache = DiskCache(root=tmp_path / "llm")
    wrapper = CachingProvider(inner=StubProvider(), cache=cache)
    wrapper.complete(LLMRequest(prompt="x", model="m"))

    complete_dir = tmp_path / "llm" / "complete"
    assert complete_dir.exists()
    shard_dirs = list(complete_dir.iterdir())
    assert len(shard_dirs) == 1
    # Shard name must be 2 hex chars.
    assert len(shard_dirs[0].name) == 2
