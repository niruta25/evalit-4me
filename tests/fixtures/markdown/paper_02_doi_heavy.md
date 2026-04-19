# Graph Neural Networks for Molecular Property Prediction

## Abstract

Graph neural networks have emerged as a powerful framework for learning
over structured data. We apply GNNs to molecular property prediction and
achieve state-of-the-art on several benchmarks.

## Introduction

Predicting molecular properties from structure is a long-standing problem
in computational chemistry. Traditional approaches rely on hand-engineered
descriptors; graph-based approaches learn representations directly from the
molecular graph.

## Method

We use a message-passing neural network (MPNN) with edge features for
bond types and global readout.

![Figure 1: Architecture overview.](./figures/arch.png)

## Experiments

| Dataset | MAE | Prior SOTA |
|---------|-----|------------|
| QM9     | 0.012 | 0.021 |
| ESOL    | 0.33  | 0.58  |
| FreeSolv | 0.69 | 1.15  |

Table 1: Mean absolute error on three benchmarks.

## Discussion

Our results suggest that message-passing architectures generalize better
than fixed descriptors for small-molecule regression tasks.

## Conclusion

We demonstrated GNNs can match or exceed domain-specific baselines on QM9,
ESOL, and FreeSolv.

## References

Gilmer, J., Schoenholz, S. S., Riley, P. F., Vinyals, O., and Dahl, G. E. (2017). Neural message passing for quantum chemistry. In International Conference on Machine Learning, pages 1263-1272. arXiv:1704.01212.

Kipf, T. N., and Welling, M. (2017). Semi-supervised classification with graph convolutional networks. In ICLR. arXiv:1609.02907.

Wu, Z., Ramsundar, B., Feinberg, E. N., Gomes, J., Geniesse, C., Pappu, A. S., Leswing, K., and Pande, V. (2018). MoleculeNet: a benchmark for molecular machine learning. Chemical Science, 9(2), 513-530. doi:10.1039/c7sc02664a

Schütt, K. T., Arbabzadah, F., Chmiela, S., Müller, K. R., and Tkatchenko, A. (2017). Quantum-chemical insights from deep tensor neural networks. Nature Communications, 8, 13890. doi:10.1038/ncomms13890

Battaglia, P. W., Hamrick, J. B., Bapst, V., Sanchez-Gonzalez, A., et al. (2018). Relational inductive biases, deep learning, and graph networks. arXiv:1806.01261.

Xu, K., Hu, W., Leskovec, J., and Jegelka, S. (2019). How powerful are graph neural networks? In ICLR. arXiv:1810.00826.
