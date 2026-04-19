# Scaling Laws for Language Models

## Abstract

We study how model performance scales with compute, dataset size, and
parameters. Power laws describe the loss well across seven orders of magnitude.

## Introduction

Empirical scaling laws provide a map for allocating compute. Prior work has
observed that test loss falls as a power law in model size.

## Methods

We train transformer decoders ranging from 768 to 1.5B parameters on a
large English corpus.

![Figure 1: Loss versus compute across model scales.](./figures/scaling.png)

## Results

![Figure 2: Dataset-size scaling curves.](./figures/data_scaling.png)

We find that loss scales as a power law in both parameters and tokens.

## References

- Kaplan, J., McCandlish, S., Henighan, T., Brown, T. B., Chess, B., Child, R., Gray, S., Radford, A., Wu, J., and Amodei, D. (2020). Scaling laws for neural language models. arXiv:2001.08361.
- Hoffmann, J., Borgeaud, S., Mensch, A., Buchatskaya, E., et al. (2022). Training compute-optimal large language models. arXiv:2203.15556.
- Brown, T., Mann, B., Ryder, N., Subbiah, M., et al. (2020). Language models are few-shot learners. In Advances in Neural Information Processing Systems, 33, 1877-1901.
- Radford, A., Wu, J., Child, R., Luan, D., Amodei, D., and Sutskever, I. (2019). Language models are unsupervised multitask learners. OpenAI Technical Report.
