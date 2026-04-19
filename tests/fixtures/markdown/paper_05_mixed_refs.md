# Variational Autoencoders: A Tutorial

## Abstract

This tutorial introduces variational autoencoders (VAEs) from a Bayesian
perspective, deriving the evidence lower bound and discussing practical
implementation considerations.

## 1. Introduction

Generative models learn the distribution of observed data. VAEs combine
neural networks with variational inference to enable amortized inference
in latent variable models.

## 2. The Evidence Lower Bound

![Figure 1: Graphical model of a VAE.](./figures/vae_graph.png)

We derive the ELBO objective and show how it balances reconstruction
against a KL regularization term.

| Term | Role |
|------|------|
| Reconstruction | Data fidelity |
| KL divergence | Regularization |

Table 1: ELBO decomposition.

## 3. Practical Training

Standard practice initializes with a small KL warmup and uses Adam.

![Figure 2: Training curves on MNIST.](./figures/vae_curves.png)

## Bibliography

1. Kingma, D. P., and Welling, M. (2014). Auto-encoding variational Bayes. In ICLR. arXiv:1312.6114.

2. Rezende, D. J., Mohamed, S., and Wierstra, D. (2014). Stochastic backpropagation and approximate inference in deep generative models. In ICML.

3. Doersch, C. (2016). Tutorial on variational autoencoders. arXiv:1606.05908.

4. Higgins, I., Matthey, L., Pal, A., Burgess, C., Glorot, X., Botvinick, M., Mohamed, S., and Lerchner, A. (2017). beta-VAE: Learning basic visual concepts with a constrained variational framework. In ICLR.

5. Tomczak, J., and Welling, M. (2018). VAE with a VampPrior. In AISTATS. arXiv:1705.07120.
