"""Decomposition pipeline tests.

We use a `ScriptedProvider` that returns canned JSON per prompt so the
decompose logic is exercised without real LLM calls. The repo-wide stub
returns non-JSON text, which is the right behavior for the "malformed
response handled gracefully" test.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from evalit_4me.contracts import (
    ClaimType,
    Paper,
    PaperMetadata,
    Reference,
    Section,
    Severity,
)
from evalit_4me.ingest.parser import parse_markdown
from evalit_4me.llm.protocol import EmbedRequest, EmbedResponse, LLMRequest, LLMResponse
from evalit_4me.llm.stub import StubProvider
from evalit_4me.stages.claims.decompose import (
    DecomposeConfig,
    _locate_span,
    build_claims,
    decompose_claims,
    parse_decompose_response,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@dataclass
class ScriptedProvider:
    """Returns canned completion text keyed on the first N chars of the prompt."""

    name: str = "scripted"
    script: dict[str, str] = field(default_factory=dict)
    default: str = "[]"

    def complete(self, request: LLMRequest) -> LLMResponse:
        text = self.default
        for cue, canned in self.script.items():
            if cue in request.prompt:
                text = canned
                break
        return LLMResponse(
            text=text,
            model=request.model,
            provider=self.name,
            prompt_tokens=max(1, len(request.prompt) // 4),
            completion_tokens=max(1, len(text) // 4),
        )

    def embed(self, request: EmbedRequest) -> EmbedResponse:
        return EmbedResponse(
            vectors=[[0.0] * 4 for _ in request.texts],
            model=request.model,
            provider=self.name,
        )


def _paper_with_sections() -> Paper:
    return Paper(
        id="p",
        metadata=PaperMetadata(title="T"),
        sections=[
            Section(
                id="intro",
                title="Introduction",
                text="Deep learning has achieved state-of-the-art on many tasks. "
                "Prior work established this in 2017.",
                order=0,
            ),
            Section(
                id="results",
                title="Results",
                text="Our model reaches F1=0.93 on the held-out split.",
                order=1,
            ),
            Section(
                id="refs",
                title="References",
                text="[1] ...",
                order=2,
            ),
        ],
        references=[
            Reference(id="ref-1", raw="Vaswani et al. 2017"),
            Reference(id="ref-2", raw="Smith 2020"),
        ],
    )


# ---------------------------------------------------------------------------
# parse_decompose_response
# ---------------------------------------------------------------------------


def test_parse_plain_json_array():
    raw = '[{"text": "A is true.", "ref_ids": ["ref-1"]}]'
    out = parse_decompose_response(raw, limit=10)
    assert len(out) == 1
    assert out[0].text == "A is true."
    assert out[0].ref_ids == ["ref-1"]


def test_parse_fenced_json():
    raw = '```json\n[{"text": "A.", "ref_ids": []}]\n```'
    out = parse_decompose_response(raw, limit=10)
    assert [c.text for c in out] == ["A."]


def test_parse_embedded_array_with_prose():
    raw = 'Here you go: [{"text": "A.", "ref_ids": []}] done.'
    out = parse_decompose_response(raw, limit=10)
    assert [c.text for c in out] == ["A."]


def test_parse_malformed_returns_empty():
    assert parse_decompose_response("not even close", limit=10) == []
    assert parse_decompose_response("", limit=10) == []


def test_parse_respects_limit():
    raw = '[{"text":"a"},{"text":"b"},{"text":"c"}]'
    out = parse_decompose_response(raw, limit=2)
    assert len(out) == 2


def test_parse_skips_non_dict_items():
    raw = '["nope", {"text": "ok"}, 42]'
    out = parse_decompose_response(raw, limit=10)
    assert [c.text for c in out] == ["ok"]


def test_parse_drops_entries_missing_text():
    raw = '[{"ref_ids":["r1"]}, {"text":""}, {"text":"keep"}]'
    out = parse_decompose_response(raw, limit=10)
    assert [c.text for c in out] == ["keep"]


# ---------------------------------------------------------------------------
# decompose_claims — end-to-end with ScriptedProvider
# ---------------------------------------------------------------------------


def test_decompose_happy_path():
    paper = _paper_with_sections()
    provider = ScriptedProvider(
        script={
            "Section title: Introduction": (
                '[{"text":"Deep learning has achieved state-of-the-art on many tasks.",'
                '"ref_ids":["ref-1"]}]'
            ),
            "Section title: Results": (
                '[{"text":"Our model reaches F1=0.93 on the held-out split.","ref_ids":[]}]'
            ),
        }
    )
    claims = decompose_claims(paper, provider)
    assert len(claims) == 2
    # Intro claim: citation-referenced; SOTA marker => CRITICAL.
    intro = claims[0]
    assert intro.claim_type == ClaimType.CITATION
    assert intro.referenced_citation_ids == ["ref-1"]
    assert intro.severity == Severity.CRITICAL
    # Results claim: statistical (F1=0.93).
    res = claims[1]
    assert res.claim_type == ClaimType.STATISTICAL
    assert res.severity == Severity.HIGH


def test_decompose_skips_references_section():
    paper = _paper_with_sections()
    provider = ScriptedProvider(default="[]")
    decompose_claims(paper, provider)
    # Assert: the LLM was not called with the references section.
    # (We can't easily check call list without more plumbing; instead,
    # verify that a bogus claim put on the References section doesn't
    # leak into output.)
    provider_with_bogus = ScriptedProvider(
        script={"Section title: References": '[{"text":"SHOULD NOT APPEAR","ref_ids":[]}]'}
    )
    claims = decompose_claims(paper, provider_with_bogus)
    assert all("SHOULD NOT APPEAR" not in c.text for c in claims)


def test_decompose_filters_hallucinated_ref_ids():
    paper = _paper_with_sections()
    provider = ScriptedProvider(
        script={
            "Section title: Introduction": ('[{"text":"Claim A.","ref_ids":["ref-1","ref-99"]}]'),
        }
    )
    claims = decompose_claims(paper, provider)
    assert claims[0].referenced_citation_ids == ["ref-1"]


def test_decompose_with_stub_returns_empty_but_no_error():
    """The repo stub returns non-JSON deterministic text; decompose must
    tolerate it rather than crash the pipeline."""
    paper = _paper_with_sections()
    claims = decompose_claims(paper, StubProvider())
    assert claims == []


def test_build_claims_is_alias_for_decompose():
    paper = _paper_with_sections()
    provider = ScriptedProvider(default="[]")
    assert build_claims(paper, provider) == decompose_claims(paper, provider)


def test_decompose_config_passes_temperature_and_seed():
    """Recorded requests must use temperature=0 and seed=0 for determinism."""
    recorded: list[LLMRequest] = []

    class Recorder(ScriptedProvider):
        def complete(self, request: LLMRequest) -> LLMResponse:
            recorded.append(request)
            return super().complete(request)

    paper = _paper_with_sections()
    decompose_claims(paper, Recorder(default="[]"), config=DecomposeConfig(seed=42))
    assert all(r.temperature == 0.0 for r in recorded)
    assert all(r.seed == 42 for r in recorded)


# ---------------------------------------------------------------------------
# _locate_span behaviour
# ---------------------------------------------------------------------------


def test_locate_span_exact_match():
    section = Section(
        id="s",
        title="S",
        text="The model achieves state of the art results on translation tasks.",
        order=0,
    )
    span = _locate_span(section=section, claim_text="state of the art results")
    assert span.char_start == section.text.lower().find("state of the art results")
    assert span.char_end - span.char_start == len("state of the art results")


def test_locate_span_case_insensitive():
    section = Section(id="s", title="S", text="Deep Learning is great.", order=0)
    span = _locate_span(section=section, claim_text="DEEP LEARNING")
    assert span.char_start == 0
    assert span.char_end == len("deep learning")


def test_locate_span_fallback_to_whole_section_when_not_found():
    section = Section(id="s", title="S", text="Short section body text.", order=0)
    span = _locate_span(section=section, claim_text="something completely different phrase")
    assert span.char_start == 0
    assert span.char_end == len(section.text)


# ---------------------------------------------------------------------------
# Integration — decompose + all 5 fixture papers (no crash)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "fixture_name",
    [
        "paper_01_numbered_refs",
        "paper_02_doi_heavy",
        "paper_03_bulleted_refs",
        "paper_04_no_refs_section",
        "paper_05_mixed_refs",
    ],
)
def test_decompose_runs_on_all_fixtures_with_stub(fixture_name):
    """Full pipeline: parse -> decompose (stub). Must never raise."""
    import pathlib

    md = (
        pathlib.Path(__file__).parents[2] / "fixtures" / "markdown" / f"{fixture_name}.md"
    ).read_text(encoding="utf-8")
    paper = parse_markdown(md, source_name=fixture_name)
    claims = decompose_claims(paper, StubProvider())
    # Stub gives [] — the invariant is "no exception, returns a list".
    assert isinstance(claims, list)
    assert all(c.severity in Severity for c in claims)
