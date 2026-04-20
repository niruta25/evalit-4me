# Sample papers

Synthetic papers covering the cases the plugin is expected to handle.
Each is small (~2 pages equivalent) so reviewers can smoke-test the whole
pipeline in seconds.

| File | Format | Exercises | Expected signal |
|---|---|---|---|
| `sample_neurips.md` | markdown | NeurIPS config detection, happy path | compliance PASS, rubric filled |
| `sample_ieee.md` | markdown | IEEE config detection (Roman numerals, numeric refs) | compliance PASS, IEEE rubric |
| `sample_arxiv.md` | markdown | arXiv detection (preprint, arXiv ID in body) | compliance PASS, lenient thresholds |
| `sample_failing.md` | markdown | Compliance FAIL — missing sections, too few refs | triage = FAIL, warning banner |
| `sample_fabricated.md` | markdown | Citation-verify — 3 fabricated DOIs (`10.9999/evalit-test-...`) | hallucination_count ≥ 3 |
| `sample.pdf` | PDF | pdfplumber single-column parse | sections detected, composite computes |
| `sample_twocol.pdf` | PDF | pdfplumber two-column parse (IEEE style) | sections detected in column order |
| `sample.docx` | DOCX | mammoth `.docx` dispatcher | sections detected |

## Smoke tests

Fastest-path:

```
you:    review this paper at plugin/examples/sample_neurips.md
claude: [detects neurips, runs pipeline in seconds, composite ≈ ACCEPT]
```

FAIL path:

```
you:    review this paper at plugin/examples/sample_failing.md
claude: [compliance triage = FAIL, warning banner, no crash]
```

Citation verification:

```
you:    review this paper at plugin/examples/sample_fabricated.md
claude: [stage 2b flags the three 10.9999/* DOIs as hallucinated]
```

Two-column PDF:

```
you:    review this paper at plugin/examples/sample_twocol.pdf under ieee
claude: [pdfplumber extracts both columns, sections detected]
```

## Regenerating

The PDFs are generated from the markdown via reportlab; the `.docx` is
generated from `sample_neurips.md` via pandoc. See
`scripts/regenerate_samples.sh` if you want to re-run them.

## Licensing

These samples are synthetic and authored for the plugin test harness.
They contain no content from copyrighted papers. The `10.9999/*` DOIs in
`sample_fabricated.md` are deliberately invalid — they won't resolve on
CrossRef, Semantic Scholar, or OpenAlex, which is the point.
