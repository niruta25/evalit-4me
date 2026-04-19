# Attention Is All You Need

## Abstract

We propose the Transformer, a network architecture based solely on attention
mechanisms, dispensing with recurrence and convolutions entirely. Experiments
on machine translation show these models to be superior in quality.

## Introduction

Recurrent neural networks have long dominated sequence modeling. The dominant
sequence transduction models are based on complex recurrent or convolutional
neural networks that include an encoder and a decoder.

## Related Work

Self-attention has been used successfully in a variety of tasks including
reading comprehension, abstractive summarization, and learning task-independent
sentence representations.

## Model Architecture

![Figure 1: The Transformer - model architecture.](./figures/fig1.png)

Most competitive neural sequence transduction models have an encoder-decoder
structure. Here, the encoder maps an input sequence of symbol representations.

| Model | BLEU | Params |
|-------|------|--------|
| RNN   | 25.1 | 200M   |
| Transformer | 28.4 | 65M |

Table 1: BLEU scores on the WMT 2014 English-to-German translation task.

## Training

We trained our models on the standard WMT 2014 English-German dataset.

## Results

![Figure 2: Attention visualization for layer 5.](./figures/fig2.png)

The Transformer achieves 28.4 BLEU on English-to-German translation, improving
over the best previously reported results.

## Conclusion

We presented the Transformer, the first sequence transduction model based
entirely on attention.

## References

[1] Bahdanau, D., Cho, K., and Bengio, Y. (2014). Neural machine translation by jointly learning to align and translate. arXiv:1409.0473.

[2] Vaswani, A., Shazeer, N., Parmar, N., and Uszkoreit, J. (2017). Attention is all you need. In Advances in Neural Information Processing Systems, 30.

[3] LeCun, Y., Bengio, Y., and Hinton, G. (2015). Deep learning. Nature, 521(7553), 436-444. doi:10.1038/nature14539

[4] He, K., Zhang, X., Ren, S., and Sun, J. (2016). Deep residual learning for image recognition. In Proceedings of CVPR, pages 770-778.

[5] Kingma, D. P., and Ba, J. (2015). Adam: A method for stochastic optimization. arXiv:1412.6980.
