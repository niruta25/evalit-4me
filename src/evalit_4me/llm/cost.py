"""Pricing table + persistent cost tracker.

Prices are USD per 1M tokens. Values are approximate and will drift; they
are intentionally overridable at runtime via `PRICING.update(...)` or by
constructing a `CostTracker` with a custom pricing dict.

Cost log format: one JSON object per line at `log_path`, written with
`os.O_APPEND` so concurrent writers don't clobber each other. Totals are
rebuilt by reading the file.
"""

from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path


@dataclass(frozen=True)
class ModelPrice:
    input_per_mtok: float
    output_per_mtok: float


# Approximate pricing snapshot — override via PRICING.update() if stale.
PRICING: dict[str, ModelPrice] = {
    # Anthropic
    "claude-opus-4-6": ModelPrice(15.0, 75.0),
    "claude-sonnet-4-6": ModelPrice(3.0, 15.0),
    "claude-haiku-4-5": ModelPrice(1.0, 5.0),
    # OpenAI
    "gpt-4o": ModelPrice(2.50, 10.0),
    "gpt-4o-mini": ModelPrice(0.15, 0.60),
    "gpt-4.1": ModelPrice(2.0, 8.0),
    "gpt-4.1-mini": ModelPrice(0.40, 1.60),
    # OpenAI embeddings (output tokens are unused)
    "text-embedding-3-small": ModelPrice(0.02, 0.0),
    "text-embedding-3-large": ModelPrice(0.13, 0.0),
}


def estimate_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    """Return USD cost for a call. Unknown models -> 0.0 (callers should log)."""
    price = PRICING.get(model)
    if price is None:
        return 0.0
    return (
        prompt_tokens * price.input_per_mtok / 1_000_000
        + completion_tokens * price.output_per_mtok / 1_000_000
    )


def _default_log_path() -> Path:
    override = os.environ.get("EVALIT_COST_LOG")
    if override:
        return Path(override)
    base = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
    return base / "evalit_4me" / "cost.jsonl"


@dataclass
class CostEntry:
    timestamp: str
    provider: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    cost_usd: float
    kind: str  # "complete" | "embed"

    def to_json(self) -> str:
        return json.dumps(self.__dict__, separators=(",", ":"))

    @classmethod
    def from_dict(cls, raw: dict[str, object]) -> CostEntry:
        return cls(
            timestamp=str(raw["timestamp"]),
            provider=str(raw["provider"]),
            model=str(raw["model"]),
            prompt_tokens=int(raw["prompt_tokens"]),  # type: ignore[arg-type]
            completion_tokens=int(raw["completion_tokens"]),  # type: ignore[arg-type]
            cost_usd=float(raw["cost_usd"]),  # type: ignore[arg-type]
            kind=str(raw["kind"]),
        )


@dataclass
class CostTracker:
    """Append-only cost log backed by JSONL.

    Totals are rebuilt by scanning the file — no in-memory state to drift.
    Thread-safe for a single process via a `threading.Lock`; the file open
    uses `os.O_APPEND` so POSIX writes from multiple processes are safe for
    lines up to PIPE_BUF (~4 KiB), which cost entries always are.
    """

    log_path: Path = field(default_factory=_default_log_path)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def __post_init__(self) -> None:
        self.log_path.parent.mkdir(parents=True, exist_ok=True)

    def record(
        self,
        *,
        provider: str,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        cost_usd: float | None = None,
        kind: str = "complete",
    ) -> CostEntry:
        if cost_usd is None:
            cost_usd = estimate_cost(model, prompt_tokens, completion_tokens)
        entry = CostEntry(
            timestamp=datetime.now(UTC).isoformat(),
            provider=provider,
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cost_usd=cost_usd,
            kind=kind,
        )
        line = entry.to_json() + "\n"
        with self._lock:
            fd = os.open(
                self.log_path,
                os.O_WRONLY | os.O_CREAT | os.O_APPEND,
                0o644,
            )
            try:
                os.write(fd, line.encode("utf-8"))
            finally:
                os.close(fd)
        return entry

    def entries(self) -> list[CostEntry]:
        if not self.log_path.exists():
            return []
        out: list[CostEntry] = []
        with self.log_path.open("r", encoding="utf-8") as f:
            for raw in f:
                raw = raw.strip()
                if not raw:
                    continue
                out.append(CostEntry.from_dict(json.loads(raw)))
        return out

    def total_cost_usd(self) -> float:
        return sum(e.cost_usd for e in self.entries())

    def totals_by_model(self) -> dict[str, float]:
        out: dict[str, float] = {}
        for e in self.entries():
            out[e.model] = out.get(e.model, 0.0) + e.cost_usd
        return out
