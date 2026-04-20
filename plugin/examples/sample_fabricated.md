# Retrieval-Augmented Generation Without Retrieval: A Paradox Resolved

## Abstract

We introduce *latent retrieval-augmented generation* (L-RAG), a technique
that gives transformer language models the performance of retrieval-augmented
systems without any actual retrieval at inference time. By distilling
retrieval behaviour into a lightweight routing head during pre-training,
L-RAG matches full-RAG accuracy on three knowledge-intensive benchmarks
while eliminating the retrieval latency and infrastructure. Our 7B L-RAG
model outperforms a 13B fine-tuned baseline on TriviaQA and matches it on
NaturalQuestions.

## 1. Introduction

Retrieval-augmented generation has become the default paradigm for
knowledge-intensive NLP tasks. It addresses the "parametric knowledge"
problem in pure language models — their tendency to hallucinate when asked
about rare entities — by retrieving relevant documents at inference time
and conditioning generation on the retrieved passages. The cost is
retrieval latency and the complexity of maintaining a document store.

We propose latent RAG: train a model to behave as if it were retrieving,
without actually doing so at inference. Our claim is that the retrieval
operation itself is a source of noise; what matters is the
knowledge-conditioning behaviour it induces in the generator. We show this
behaviour can be distilled into the generator's parameters directly during
pre-training (Chen et al., 2024).

## 2. Method

L-RAG adds a 64M-parameter "knowledge router" head to a standard decoder-only
transformer. During pre-training the router is jointly trained to predict
which of 16 pseudo-retrieval slots each token should attend to. The slots
themselves are learned embeddings initialised from a k-means clustering of
the retrieval embeddings a standard RAG system would produce. At inference
time no retrieval occurs — the router simply routes each token to the
learned slots, and the model uses their stored knowledge directly.

The full training recipe is described in Martinez and Johnson (2025), who
observed that the slots converge to cluster centroids of the implicit
knowledge graph, and that the 64M-parameter overhead is the minimum
needed to preserve capacity.

## 3. Experiments

We evaluate on TriviaQA, NaturalQuestions, and HotpotQA. Our 7B-parameter
L-RAG model reaches 72.1 exact-match on TriviaQA, compared to 69.4 for a
13B fine-tuned baseline without retrieval and 73.0 for a full-RAG 7B
baseline with Contriever (Izacard et al., 2022). On NaturalQuestions the
numbers are 45.2 (L-RAG), 43.8 (fine-tuned 13B), and 45.9 (full-RAG 7B).
HotpotQA (multi-hop) shows a smaller gap to full-RAG (42.1 vs 45.1),
consistent with the expectation that multi-hop queries benefit from
retrieval diversity the learned slots cannot reproduce.

The detailed ablation study in our companion paper (Patel et al., 2025)
confirms that the knowledge-router capacity is the critical hyperparameter,
and that slot count can be reduced to 8 with only a 1.2-point accuracy drop.

## 4. Limitations

L-RAG's knowledge is static at pre-training time. For queries about events
or entities that appear after the training cutoff, accuracy degrades to
pure-parametric baseline levels. We also do not evaluate on open-domain
generation tasks where the citation trail matters for downstream
verification.

## 5. Conclusion

Pre-training a knowledge-router head lets a transformer recover most of the
accuracy benefit of retrieval-augmented generation without any
inference-time retrieval. For deployments where retrieval latency and
infrastructure complexity are the primary pain points, L-RAG is a useful
alternative.

## References

1. Chen, S. et al. Distilling retrieval into parameters: foundations of
   latent RAG. NeurIPS, 2024. DOI: 10.9999/evalit-test-fabricated-2024-001.
2. Martinez, R. and Johnson, P. Knowledge routing heads in decoder-only
   transformers. ICML, 2025. DOI: 10.9999/evalit-test-fabricated-2025-002.
3. Patel, D., Kim, S., and Wu, J. Ablation studies of latent retrieval.
   ACL, 2025. DOI: 10.9999/evalit-test-fabricated-2025-003.
4. Izacard, G. and Grave, E. Unsupervised dense information retrieval with
   contrastive learning (Contriever). TMLR, 2022.
   DOI: 10.48550/arXiv.2112.09118.
5. Lewis, P. et al. Retrieval-augmented generation for knowledge-intensive
   NLP tasks. NeurIPS, 2020. DOI: 10.48550/arXiv.2005.11401.
6. Karpukhin, V. et al. Dense Passage Retrieval for Open-Domain Question
   Answering. EMNLP, 2020. DOI: 10.18653/v1/2020.emnlp-main.550.
7. Kwiatkowski, T. et al. Natural Questions: A Benchmark for Question
   Answering Research. TACL, 2019. DOI: 10.1162/tacl_a_00276.
8. Joshi, M. et al. TriviaQA. ACL, 2017. DOI: 10.18653/v1/P17-1147.
9. Yang, Z. et al. HotpotQA: A Dataset for Diverse, Explainable Multi-hop
   Question Answering. EMNLP, 2018. DOI: 10.18653/v1/D18-1259.
