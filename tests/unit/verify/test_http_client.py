"""HTTPClient tests — cache, 404 handling, 5xx backoff."""

from __future__ import annotations

from pathlib import Path

import pytest

from evalit_4me.stages.verify.http_client import HTTPClient, HTTPError


def _make_client(tmp_path: Path, *, fetcher, sleeper=None) -> HTTPClient:
    client = HTTPClient(cache_dir=tmp_path / "http", fetcher=fetcher)
    if sleeper is not None:
        client.sleeper = sleeper
    client.backoff_base = 0.0  # fast tests
    return client


def test_get_json_200(tmp_path: Path):
    calls = []

    def fetcher(url, headers):
        calls.append(url)
        return 200, '{"ok": true}'

    client = _make_client(tmp_path, fetcher=fetcher)
    assert client.get_json("https://example.com/a") == {"ok": True}


def test_get_json_404_returns_none(tmp_path: Path):
    client = _make_client(tmp_path, fetcher=lambda u, h: (404, "not found"))
    assert client.get_json("https://example.com/missing") is None


def test_get_json_4xx_raises(tmp_path: Path):
    client = _make_client(tmp_path, fetcher=lambda u, h: (400, "bad request"))
    with pytest.raises(HTTPError) as exc_info:
        client.get_json("https://example.com/broken")
    assert exc_info.value.status == 400


def test_cache_hit_avoids_refetch(tmp_path: Path):
    calls: list[str] = []

    def fetcher(url, headers):
        calls.append(url)
        return 200, '{"hit": 1}'

    client = _make_client(tmp_path, fetcher=fetcher)
    client.get_json("https://example.com/a")
    client.get_json("https://example.com/a")
    assert len(calls) == 1


def test_cache_roundtrips_404(tmp_path: Path):
    calls: list[int] = []

    def fetcher(url, headers):
        calls.append(1)
        return 404, ""

    client = _make_client(tmp_path, fetcher=fetcher)
    assert client.get_json("https://example.com/m") is None
    assert client.get_json("https://example.com/m") is None
    # Second call should be cached.
    assert len(calls) == 1


def test_5xx_triggers_backoff_then_success(tmp_path: Path):
    sleeps: list[float] = []
    # Return 500, 500, 200.
    responses = iter([(500, ""), (500, ""), (200, '{"ok": 1}')])

    def fetcher(url, headers):
        return next(responses)

    client = _make_client(tmp_path, fetcher=fetcher, sleeper=sleeps.append)
    assert client.get_json("https://example.com/flaky") == {"ok": 1}
    # Two sleeps between three attempts.
    assert len(sleeps) == 2


def test_5xx_exhausts_retries(tmp_path: Path):
    sleeps: list[float] = []
    client = _make_client(
        tmp_path,
        fetcher=lambda u, h: (503, "down"),
        sleeper=sleeps.append,
    )
    with pytest.raises(HTTPError) as exc_info:
        client.get_json("https://example.com/500")
    assert exc_info.value.status == 503


def test_invalid_json_raises(tmp_path: Path):
    client = _make_client(tmp_path, fetcher=lambda u, h: (200, "not json"))
    with pytest.raises(HTTPError):
        client.get_json("https://example.com/bad")


def test_sends_user_agent_and_accept_headers(tmp_path: Path):
    recorded: list[dict[str, str]] = []

    def fetcher(url, headers):
        recorded.append(headers)
        return 200, "{}"

    client = _make_client(tmp_path, fetcher=fetcher)
    client.get_json("https://example.com/h")
    assert "User-Agent" in recorded[0]
    assert recorded[0]["Accept"] == "application/json"
