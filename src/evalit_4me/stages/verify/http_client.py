"""Minimal HTTP client with disk cache + exponential backoff.

Why roll our own instead of `requests` + `cachecontrol` + `tenacity`?

1. We only hit three APIs (CrossRef, Semantic Scholar, OpenAlex) with
   simple GET semantics. A 60-line wrapper is less surface area than three
   third-party deps.
2. The resolver unit tests need a deterministic transport without monkey-
   patching `requests`. Here we pass a custom `fetcher` callable into the
   constructor — tests inject a dict-driven stub, production uses urllib.
3. On-disk cache keys are content-hashed URLs, consistent with how
   `llm/cache.py` works. This lets `evalit bench` replay runs without
   network.

HTTP errors > 500 are retried with jittered exponential backoff; 404s are
returned as `None` (callers treat that as "not found"); other 4xx raise
`HTTPError` and surface to the caller.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import random
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


class HTTPError(RuntimeError):
    def __init__(self, url: str, status: int, body: str = "") -> None:
        super().__init__(f"HTTP {status} from {url}: {body[:200]}")
        self.url = url
        self.status = status
        self.body = body


Fetcher = Callable[[str, dict[str, str]], tuple[int, str]]
"""fetcher(url, headers) -> (status_code, body). Status 0 indicates not-found."""


def _urllib_fetcher(url: str, headers: dict[str, str]) -> tuple[int, str]:
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status, resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        body = ""
        with contextlib.suppress(Exception):
            body = exc.read().decode("utf-8", errors="replace")
        return exc.code, body
    except urllib.error.URLError as exc:
        raise HTTPError(url, 0, str(exc)) from exc


def _default_cache_dir() -> Path:
    override = os.environ.get("EVALIT_HTTP_CACHE_DIR")
    if override:
        return Path(override)
    base = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
    return base / "evalit_4me" / "http"


@dataclass
class HTTPClient:
    """Injectable HTTP client with on-disk JSON cache and backoff-on-5xx.

    Cache format: one JSON file per URL SHA-256 under `cache_dir`. The file
    holds `{"status": int, "body": str}` so we can distinguish a cached 404
    from a cached 200 with empty body.
    """

    cache_dir: Path = field(default_factory=_default_cache_dir)
    user_agent: str = "evalit-4me/0.0.1 (https://github.com/niruta25/evalit-4me)"
    max_retries: int = 3
    backoff_base: float = 0.5
    fetcher: Fetcher = field(default=_urllib_fetcher)
    sleeper: Callable[[float], None] = field(default=time.sleep)
    # Deterministic jitter for tests.
    rng: random.Random = field(default_factory=lambda: random.Random(0))

    def __post_init__(self) -> None:
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def get_json(self, url: str, *, extra_headers: dict[str, str] | None = None) -> Any | None:
        """GET `url`, parse JSON, cache the raw body. Returns None on 404."""
        cached = self._read_cache(url)
        if cached is not None:
            status, body = cached
        else:
            status, body = self._fetch_with_retry(url, extra_headers or {})
            self._write_cache(url, status, body)

        if status == 404:
            return None
        if status >= 400:
            raise HTTPError(url, status, body)
        if not body.strip():
            return None
        try:
            return json.loads(body)
        except json.JSONDecodeError as exc:
            raise HTTPError(url, status, f"invalid JSON: {exc}") from exc

    # --- Cache IO ---------------------------------------------------------

    def _cache_path(self, url: str) -> Path:
        h = hashlib.sha256(url.encode("utf-8")).hexdigest()
        return self.cache_dir / h[:2] / f"{h}.json"

    def _read_cache(self, url: str) -> tuple[int, str] | None:
        p = self._cache_path(url)
        if not p.exists():
            return None
        data = json.loads(p.read_text(encoding="utf-8"))
        return int(data["status"]), str(data["body"])

    def _write_cache(self, url: str, status: int, body: str) -> None:
        p = self._cache_path(url)
        p.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps({"status": status, "body": body}, separators=(",", ":"))
        tmp = p.with_suffix(p.suffix + ".tmp")
        tmp.write_text(payload, encoding="utf-8")
        os.replace(tmp, p)

    # --- Fetch + retry ----------------------------------------------------

    def _fetch_with_retry(self, url: str, extra_headers: dict[str, str]) -> tuple[int, str]:
        headers = {
            "User-Agent": self.user_agent,
            "Accept": "application/json",
            **extra_headers,
        }
        last_status = 0
        last_body = ""
        for attempt in range(self.max_retries):
            status, body = self.fetcher(url, headers)
            if status < 500 or status == 0:
                return status, body
            last_status, last_body = status, body
            if attempt < self.max_retries - 1:
                delay = self.backoff_base * (2**attempt) + self.rng.uniform(0.0, 0.2)
                self.sleeper(delay)
        return last_status, last_body
