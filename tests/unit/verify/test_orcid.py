"""ORCID lookup tests. 5 known authors mapped to canned responses."""

from __future__ import annotations

import json
from pathlib import Path

from evalit_4me.stages.verify.http_client import HTTPClient
from evalit_4me.stages.verify.orcid import lookup_author, lookup_authors


def _canned_hit(*, orcid: str, given: str, family: str, institution: str | None = None) -> dict:
    return {
        "orcid-id": orcid,
        "given-names": given,
        "family-names": family,
        "institution-name": [institution] if institution else [],
    }


def _client(tmp_path: Path, routes: dict[str, str]) -> HTTPClient:
    def fetcher(url: str, headers: dict[str, str]) -> tuple[int, str]:
        for key, payload in routes.items():
            if key in url:
                return 200, payload
        return 404, ""

    c = HTTPClient(cache_dir=tmp_path / "http", fetcher=fetcher)
    c.backoff_base = 0.0
    return c


def test_single_exact_name_match(tmp_path: Path):
    payload = json.dumps(
        {
            "expanded-result": [
                _canned_hit(
                    orcid="0000-0001-2345-6789", given="Yann", family="LeCun", institution="NYU"
                )
            ]
        }
    )
    client = _client(tmp_path, {"q=Yann%20LeCun": payload})
    out = lookup_author("Yann LeCun", client)
    assert out.orcid_id == "0000-0001-2345-6789"
    assert out.matched_name == "Yann LeCun"
    assert out.institution == "NYU"
    assert out.confidence >= 0.9


def test_no_hits_returns_null_match(tmp_path: Path):
    client = _client(tmp_path, routes={})
    out = lookup_author("Noone Here", client)
    assert out.orcid_id is None
    assert out.confidence == 0.0


def test_multiple_hits_picks_best(tmp_path: Path):
    payload = json.dumps(
        {
            "expanded-result": [
                _canned_hit(orcid="0000-0001-0000-0001", given="Random", family="Person"),
                _canned_hit(
                    orcid="0000-0001-0000-0002", given="Yoshua", family="Bengio", institution="MILA"
                ),
                _canned_hit(orcid="0000-0001-0000-0003", given="Other", family="Author"),
            ]
        }
    )
    client = _client(tmp_path, {"q=Yoshua%20Bengio": payload})
    out = lookup_author("Yoshua Bengio", client)
    assert out.orcid_id == "0000-0001-0000-0002"
    assert out.institution == "MILA"


def test_bogus_orcid_format_rejected(tmp_path: Path):
    """Hit has a non-ORCID-shaped id -> we still match on name but orcid_id is None."""
    payload = json.dumps(
        {"expanded-result": [_canned_hit(orcid="NOT-AN-ORCID", given="Ada", family="Lovelace")]}
    )
    client = _client(tmp_path, {"q=Ada%20Lovelace": payload})
    out = lookup_author("Ada Lovelace", client)
    assert out.orcid_id is None
    assert out.matched_name == "Ada Lovelace"


def test_low_similarity_rejects_match(tmp_path: Path):
    """Query 'Jane Smith' vs hit 'Qbc Def' should NOT match."""
    payload = json.dumps(
        {"expanded-result": [_canned_hit(orcid="0000-0001-0000-0001", given="Qbc", family="Def")]}
    )
    client = _client(tmp_path, {"q=Jane%20Smith": payload})
    out = lookup_author("Jane Smith", client)
    assert out.orcid_id is None
    assert out.confidence == 0.0


def test_5_known_authors_all_resolve(tmp_path: Path):
    """Exit gate: ORCID 5/5 on fixtures."""
    authors = [
        ("Geoffrey Hinton", "0000-0002-1111-0001"),
        ("Yann LeCun", "0000-0002-1111-0002"),
        ("Yoshua Bengio", "0000-0002-1111-0003"),
        ("Ian Goodfellow", "0000-0002-1111-0004"),
        ("Fei-Fei Li", "0000-0002-1111-0005"),
    ]
    routes: dict[str, str] = {}
    for name, orcid in authors:
        given, family = name.rsplit(" ", 1)
        # ORCID URL-encoding may vary; we use substring matching on the
        # first name fragment which is unique per author.
        routes[given.replace(" ", "%20")] = json.dumps(
            {
                "expanded-result": [
                    _canned_hit(
                        orcid=orcid,
                        given=given,
                        family=family,
                        institution=f"Inst-{family}",
                    )
                ]
            }
        )
    client = _client(tmp_path, routes)

    out = lookup_authors([name for name, _ in authors], client)
    assert len(out) == 5
    for name, expected_orcid in authors:
        m = out[name]
        assert m.orcid_id == expected_orcid, f"{name} resolved to {m.orcid_id}"
        assert m.matched_name is not None
        assert m.confidence >= 0.5


def test_blank_name_no_query(tmp_path: Path):
    client = _client(tmp_path, routes={})
    out = lookup_author("   ", client)
    assert out.orcid_id is None
    assert out.confidence == 0.0
