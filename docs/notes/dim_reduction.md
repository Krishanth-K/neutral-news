# Dimensionality Reduction

PCA -> preserves variance
LDA -> preserves class boundaries
UMAP -> preserves the relative distance between two data points


PCA only works when the two principal components account for most of the variation in the data
For complex datasets -> PCA might not work very well

## UMAP

UMAP tries to project higher-dim space into lower-dim.
For ex: a 2d graph into a 1d graph.

It does this by calculating the distance of each point to every other point -> to understand the similarity between data points -> identify clusters.

Then these points are placed on the 1d graph based on this distance. So similar points stay together

IMPORTANT: the main parameter is `num of neighbors`

