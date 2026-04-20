# Notes on Graph Convolutions

## Abstract

I worked on graph neural networks this semester and this document summarises
what I tried. The main thing is that deeper models were not always better.

## Intro

Graph convolutional networks (GCNs) are popular for node classification. They
apply a convolution-like operation over a graph's adjacency structure. I
implemented a two-layer GCN in PyTorch and tried it on Cora and Citeseer.

## Experiments

On Cora I got 81 percent accuracy with two layers. With three layers I got
79 percent. With four layers it dropped to 74 percent. This is the
over-smoothing problem.

On Citeseer the numbers were similar, two layers worked best.

## Discussion

Deeper is not always better. Over-smoothing is real. I would try DropEdge
next if I had more time.

## References

Kipf, T., and Welling, M. Semi-Supervised Classification with Graph
Convolutional Networks. ICLR, 2017.

Rong, Y. et al. DropEdge: Towards Deep Graph Convolutional Networks on Node
Classification. ICLR, 2020.
