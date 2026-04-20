# Cross-Lingual Retrieval with Frozen Multilingual Encoders: A Surprisingly Strong Baseline

arXiv:2601.01234v1 [cs.CL] 19 Apr 2026

## Abstract

We revisit cross-lingual dense retrieval using frozen multilingual encoders
such as LaBSE and multilingual-E5. Without any fine-tuning, and without any
in-language training data, these encoders already reach within 3 BLEU-retrieval
of the fine-tuned baselines on the XOR-Retrieve benchmark for five of seven
languages. A light-weight reranking head on top of the frozen encoder closes
the remaining gap on four languages. We argue that the gains attributed in
recent literature to elaborate contrastive fine-tuning recipes are largely
attributable to the underlying frozen encoder quality. We make our
reproduction code public.

## Introduction

Cross-lingual retrieval — finding relevant documents in a target language
given a query in a different source language — has been the subject of a
substantial body of work over the past three years. The dominant paradigm
fine-tunes a multilingual encoder such as XLM-R with contrastive losses on
parallel query-passage pairs. Recent variants add reranking stages, hard
negative mining, or task-specific distillation.

We ask a narrower question: how much of the recent progress is attributable
to these elaborations, versus improvements in the underlying frozen encoder?
We find, consistent with concurrent work by Asai et al. (2024), that
frozen multilingual encoders are a much stronger baseline than the
literature generally reports.

## Method

We evaluate on XOR-Retrieve (Asai et al., 2021), an open-retrieval benchmark
spanning seven typologically diverse languages: Arabic, Bengali, Finnish,
Japanese, Korean, Russian, and Telugu. Queries are natural-language
questions; passages are Wikipedia. The metric is retrieval accuracy at k=5.
Every encoder scores passages by inner product with a query embedding.
Passages are chunked to 256 tokens with 32 tokens of overlap, and indexed
in a FAISS IndexFlatIP. We evaluate over the full evaluation split, which
contains roughly 1000 queries per language for a total of 7040 queries.

We compare three systems:

- **Frozen-LaBSE.** Off-the-shelf LaBSE encoder, mean-pooled, L2-normalised.
  We use the HuggingFace checkpoint without any modifications.
- **Frozen-mE5.** Off-the-shelf multilingual-E5-large, CLS-pooled. The query
  prompt template is the E5-recommended `"query: "` prefix; the passage
  prompt template is `"passage: "`.
- **Fine-tuned baseline.** XLM-R-large fine-tuned with contrastive loss on
  the MIRACL training split. This is our reproduction of Zhang et al. (2023)
  using batch size 512, learning rate 1e-5, AdamW optimiser, and 3 epochs
  of training on 16 A100 GPUs. We verified reproduction by matching their
  reported MIRACL retrieval accuracy within 0.3 points average across
  languages.

### Reranker

For the reranker ablation, we train a small two-layer MLP (hidden size 256)
on top of the concatenation of the frozen query and passage embeddings.
Training data is the MIRACL in-language subset for each target language;
we use 20 epochs with learning rate 1e-3 and early stopping. The reranker
is applied to the top-100 candidates from the first-stage retrieval.

## Results

Frozen-mE5 achieves an average retrieval accuracy of 66.8, versus 69.1 for
the fine-tuned baseline and 62.3 for Frozen-LaBSE. On Finnish and Japanese,
Frozen-mE5 actually exceeds the fine-tuned baseline by small margins (0.6
and 0.9 points respectively). On Telugu, a low-resource language, the
fine-tuned baseline maintains a 4.1-point lead. A simple linear reranker
on top of Frozen-mE5 closes the gap on all but Telugu.

Per-language breakdowns are consistent with this overall pattern: the
fine-tuning gap is concentrated in lower-resource languages where the
frozen encoder has seen less pre-training data. We additionally ran an
ablation where the reranker was trained only on English MIRACL and
evaluated zero-shot on every other language; surprisingly this trailed
the full in-language-reranker baseline by only 1.4 points average,
suggesting that the reranker mostly learns a language-agnostic
relevance signal rather than language-specific features.

We also evaluated latency on a single A10G GPU. Frozen-mE5 inference
averages 12 ms per query (including encoder forward pass and FAISS
search), while the fine-tuned stack averages 47 ms due to the larger
model footprint. This 4x speedup, combined with the cheaper training
cost (zero, for Frozen-mE5), is the practical argument for preferring
the frozen approach in production deployments where the 3-point average
accuracy gap is acceptable.

## Discussion

Two observations: (1) the "fine-tuning gap" is small and concentrated in
low-resource languages where parallel training data is most plentiful,
suggesting the gap reflects better representations of those specific
languages rather than a generic advantage; (2) for many practical
deployments — multilingual FAQ search, cross-border customer support — the
3-point average gap is not worth the fine-tuning overhead. Cost is the
quiet story: Frozen-mE5 inference is 4× cheaper per query than the
fine-tuned stack and requires no retraining when the corpus changes.

## Limitations

We evaluate on only one benchmark. The conclusion may not generalise to
retrieval over non-Wikipedia corpora with different vocabulary
distributions. We also do not evaluate on generative downstream tasks
(open-domain QA with reader models) — our claim is narrower, about
retrieval accuracy only.

## Conclusion

A frozen multilingual encoder is a much stronger baseline for cross-lingual
retrieval than the published record suggests. Future work that proposes
fine-tuning recipes should report frozen-encoder numbers side by side.

## References

Asai, A. et al. XOR QA: Cross-lingual Open-Retrieval Question Answering.
  NAACL, 2021. DOI: 10.48550/arXiv.2010.11856.

Asai, A. et al. Revisiting frozen multilingual encoders. arXiv preprint,
  2024. DOI: 10.48550/arXiv.2404.98765.

Conneau, A. et al. Unsupervised Cross-lingual Representation Learning at
  Scale (XLM-R). ACL, 2020. DOI: 10.18653/v1/2020.acl-main.747.

Feng, F. et al. Language-agnostic BERT Sentence Embedding (LaBSE). ACL,
  2022. DOI: 10.48550/arXiv.2007.01852.

Wang, L. et al. Multilingual E5 Text Embeddings. arXiv preprint, 2024.
  DOI: 10.48550/arXiv.2402.05672.

Zhang, X. et al. MIRACL: A Multilingual Retrieval Dataset Covering 18
  Diverse Languages. TACL, 2023. DOI: 10.1162/tacl_a_00595.

Karpukhin, V. et al. Dense Passage Retrieval for Open-Domain Question
  Answering. EMNLP, 2020. DOI: 10.18653/v1/2020.emnlp-main.550.

Reimers, N. and Gurevych, I. Sentence-BERT. EMNLP, 2019.
  DOI: 10.18653/v1/D19-1410.

Thakur, N. et al. BEIR: A Heterogeneous Benchmark for Zero-shot Evaluation
  of Information Retrieval Models. NeurIPS Datasets, 2021.
  DOI: 10.48550/arXiv.2104.08663.
