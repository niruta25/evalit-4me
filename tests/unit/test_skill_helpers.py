"""Tests for `evalit_4me.skill_helpers` and the MCP server surface.

Exercises: config detection heuristic, multi-config runner (stub LLM +
no network), comparison builder, composite reweighting, MCP server
construction.
"""

from __future__ import annotations

import json
from pathlib import Path

from evalit_4me.skill_helpers import (
    SHIPPED_CONFIGS,
    compare_records,
    detect_best_config,
    prepare_output_dir,
    recompute_composite,
    recompute_to_json,
    run_multi_config,
    slugify,
    write_comparison,
)

FIXTURES_DIR = Path(__file__).parents[1] / "fixtures" / "markdown"


# ---------------------------------------------------------------------------
# detect_best_config
# ---------------------------------------------------------------------------


def test_detect_ieee_on_roman_numeral_headers():
    md = (
        "# Paper Title\n\n"
        "I. INTRODUCTION\n\n"
        "body\n\n"
        "II. RELATED WORK\n\n"
        "body\n\n"
        "III. METHOD\n\n"
        "body\n"
    )
    guess = detect_best_config(md)
    assert guess.recommended == "ieee"
    assert guess.confidence > 0.5


def test_detect_arxiv_on_arxiv_id():
    md = "# Paper\n\nRefers to arXiv:2305.17493v3 in body.\n"
    guess = detect_best_config(md)
    assert guess.recommended == "arxiv"


def test_detect_neurips_on_broader_impact_cue():
    md = "# Paper\n\n## Broader Impact\n\nDiscussion here.\n" * 20  # pad length
    guess = detect_best_config(md)
    assert guess.recommended == "neurips"


def test_detect_ieee_on_short_papers():
    md = "# A\n\nShort body.\n" * 10  # very few words
    guess = detect_best_config(md)
    assert guess.recommended == "ieee"


def test_detect_arxiv_on_long_papers():
    # > 15000 words without any other signal
    md = "# Paper\n\n" + ("word " * 16000)
    guess = detect_best_config(md)
    assert guess.recommended == "arxiv"


def test_detect_defaults_to_neurips_when_no_signal():
    # Aim for 3000 < word_count < 15000 and no Roman/arxiv/neurips cues.
    md = "# Paper\n\n" + ("medium length content about a neural network model " * 800)
    guess = detect_best_config(md)
    assert guess.recommended == "neurips"


def test_detect_returns_all_shipped_configs():
    """Every branch should route to one of SHIPPED_CONFIGS."""
    for md in [
        "I. INTRO\n\nII. METHOD\n\nIII. RESULTS\n",
        "arXiv:1234.5678\n",
        "Broader Impact section.\n" * 20,
        "short\n",
        "word " * 16000,
        "generic content\n" * 200,
    ]:
        assert detect_best_config(md).recommended in SHIPPED_CONFIGS


# ---------------------------------------------------------------------------
# slugify + output dir
# ---------------------------------------------------------------------------


def test_slugify_basic():
    assert slugify("Attention Is All You Need") == "attention-is-all-you-need"
    assert slugify("Hello, World!") == "hello-world"
    assert slugify("") == "untitled"


def test_prepare_output_dir_creates_dated_folder(tmp_path: Path):
    out = prepare_output_dir("my-paper", home=tmp_path)
    assert out.exists()
    assert out.parent == tmp_path / "evalit-reports"
    # Folder name starts with today's date.
    from datetime import datetime

    assert out.name.startswith(datetime.now().strftime("%Y-%m-%d"))
    assert out.name.endswith("-my-paper")


# ---------------------------------------------------------------------------
# run_multi_config (no LLM, no network — fast smoke)
# ---------------------------------------------------------------------------


def test_run_multi_config_single(tmp_path: Path):
    fixture = FIXTURES_DIR / "paper_01_numbered_refs.md"
    _out_dir, results = run_multi_config(
        fixture,
        ["neurips"],
        provider=None,
        http_client=None,
        home=tmp_path,
    )
    assert len(results) == 1
    r = results[0]
    assert r.config_name == "neurips"
    assert r.record_path.exists()
    assert r.html_path.exists()
    assert r.review_md_path.exists()
    assert 0.0 <= r.composite <= 1.0


def test_run_multi_config_parallel(tmp_path: Path):
    fixture = FIXTURES_DIR / "paper_01_numbered_refs.md"
    _out_dir, results = run_multi_config(
        fixture,
        list(SHIPPED_CONFIGS),
        provider=None,
        http_client=None,
        home=tmp_path,
        parallel=True,
    )
    assert len(results) == 3
    # Order preserved.
    assert [r.config_name for r in results] == list(SHIPPED_CONFIGS)
    # All artifacts present.
    for r in results:
        assert r.record_path.exists()
        assert r.html_path.exists()
        assert r.review_md_path.exists()


def test_write_comparison_creates_markdown(tmp_path: Path):
    fixture = FIXTURES_DIR / "paper_01_numbered_refs.md"
    _, results = run_multi_config(
        fixture,
        ["neurips", "ieee"],
        provider=None,
        http_client=None,
        home=tmp_path,
    )
    comp = write_comparison(results[0].record_path.parent, results)
    assert comp.exists()
    content = comp.read_text(encoding="utf-8")
    assert "| Metric |" in content
    assert "neurips" in content
    assert "ieee" in content


# ---------------------------------------------------------------------------
# compare_records
# ---------------------------------------------------------------------------


def test_compare_records_renders_all_rows(tmp_path: Path):
    fixture = FIXTURES_DIR / "paper_01_numbered_refs.md"
    _, results = run_multi_config(
        fixture, ["neurips", "arxiv"], provider=None, http_client=None, home=tmp_path
    )
    md = compare_records([r.record_path for r in results])
    for label in (
        "Compliance triage",
        "Total claims",
        "Hallucinations",
        "Rubric bias-adjusted",
        "Composite (recomputed)",
        "Recommendation",
    ):
        assert label in md


def test_compare_records_empty_input():
    assert "No records" in compare_records([])


# ---------------------------------------------------------------------------
# recompute_composite
# ---------------------------------------------------------------------------


def test_recompute_changes_composite(tmp_path: Path):
    fixture = FIXTURES_DIR / "paper_01_numbered_refs.md"
    _, results = run_multi_config(
        fixture, ["neurips"], provider=None, http_client=None, home=tmp_path
    )
    record_path = results[0].record_path
    heavy_rubric = recompute_composite(
        record_path,
        {"compliance": 0.05, "verification": 0.05, "depth": 0.10, "rubric": 0.80},
    )
    heavy_compliance = recompute_composite(
        record_path,
        {"compliance": 0.80, "verification": 0.05, "depth": 0.10, "rubric": 0.05},
    )
    # Sanity: flipping weights flips the composite direction.
    assert heavy_rubric.new_composite != heavy_compliance.new_composite


def test_recompute_partial_weights_merge_with_defaults(tmp_path: Path):
    fixture = FIXTURES_DIR / "paper_01_numbered_refs.md"
    _, results = run_multi_config(
        fixture, ["neurips"], provider=None, http_client=None, home=tmp_path
    )
    record_path = results[0].record_path
    # Only rubric specified — other keys should default.
    result = recompute_composite(record_path, {"rubric": 0.8})
    assert result.weights["rubric"] == 0.8
    # Other keys keep defaults.
    assert result.weights["compliance"] == 0.15


def test_recompute_to_json_is_valid_json(tmp_path: Path):
    fixture = FIXTURES_DIR / "paper_01_numbered_refs.md"
    _, results = run_multi_config(
        fixture, ["neurips"], provider=None, http_client=None, home=tmp_path
    )
    r = recompute_composite(results[0].record_path, {"rubric": 0.7})
    payload = json.loads(recompute_to_json(r))
    for key in (
        "original_composite",
        "new_composite",
        "delta",
        "recommendation_before",
        "recommendation_after",
        "breakdown",
        "weights",
    ):
        assert key in payload


def test_recompute_recommendation_moves_with_weights(tmp_path: Path):
    """Piling 95% weight on a high component should raise the composite
    and can change the recommendation tier."""
    fixture = FIXTURES_DIR / "paper_01_numbered_refs.md"
    _, results = run_multi_config(
        fixture, ["neurips"], provider=None, http_client=None, home=tmp_path
    )
    # Rubric score is typically moderate for fixtures.
    r_heavy = recompute_composite(
        results[0].record_path,
        {"compliance": 0.02, "verification": 0.02, "depth": 0.01, "rubric": 0.95},
    )
    r_light = recompute_composite(
        results[0].record_path,
        {"compliance": 0.95, "verification": 0.01, "depth": 0.02, "rubric": 0.02},
    )
    # Direction: heavier rubric weight produces a different composite than
    # heavier compliance weight on the same record.
    assert r_heavy.new_composite != r_light.new_composite


# ---------------------------------------------------------------------------
# MCP server construction (stdio smoke)
# ---------------------------------------------------------------------------


def test_mcp_server_builds():
    from evalit_4me.mcp_server import build_server

    server = build_server()
    assert server.name == "evalit-4me"


def test_mcp_server_exposes_four_tools():
    """Check the server registered all four tool handlers without relying
    on pytest-asyncio. FastMCP stores them internally on the tool manager."""
    import asyncio

    from evalit_4me.mcp_server import build_server

    server = build_server()
    tools = asyncio.run(server.list_tools())
    names = {t.name for t in tools}
    assert names == {"detect_config", "review_paper", "compare", "reweight"}
