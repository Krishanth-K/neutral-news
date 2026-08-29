import numpy as np
from scipy.cluster.hierarchy import fcluster, linkage
from scipy.spatial.distance import squareform


def cluster_articles_hac(
    distances: np.ndarray,
    article_ids: list[str],
    distance_threshold: float = 0.40,
    linkage_method: str = "complete",  # 'complete' prevents chaining
) -> dict[int, dict]:
    """Clusters articles using Hierarchical Agglomerative Clustering (HAC).

    Args:
        distances: (N, N) symmetric pairwise distance matrix with zero diagonal.
        article_ids: List of article UUIDs corresponding to matrix rows/cols.
        distance_threshold: Distance cutoff (t) for merging clusters.
        linkage_method: 'complete' (recommended) or 'average'.

    Returns:
        dict mapping cluster_id -> {
            "article_ids": list[str],
            "medoid_id": str,
            "size": int
        }
    """
    n = len(article_ids)
    if n == 0:
        return {}
    if n == 1:
        return {1: {"article_ids": article_ids, "medoid_id": article_ids[0], "size": 1}}

    # 1. Convert square (N, N) distance matrix to 1D condensed vector
    # (Scipy linkage requires condensed format for precomputed distances)
    condensed_dist = squareform(distances, checks=False)

    # 2. Perform hierarchical agglomerative clustering
    # Creates the linkage matrix (dendrogram tree)
    Z = linkage(condensed_dist, method=linkage_method)

    # 3. Cut the dendrogram at the distance threshold
    # Labels will be 1-indexed integers (e.g. 1, 2, 3...)
    labels = fcluster(Z, t=distance_threshold, criterion="distance")

    # 4. Group member indices by cluster label
    cluster_members: dict[int, list[int]] = {}
    for idx, cluster_label in enumerate(labels):
        cluster_members.setdefault(int(cluster_label), []).append(idx)

    # 5. Build structured result with medoid computation
    result = {}
    for cluster_id, member_indices in cluster_members.items():
        member_article_ids = [article_ids[i] for i in member_indices]

        # Compute Medoid: the article closest to all other articles in the cluster
        if len(member_indices) == 1:
            medoid_idx = member_indices[0]
        else:
            sub_matrix = distances[np.ix_(member_indices, member_indices)]
            # Sum distances from each article to all other members in the cluster
            avg_distances = sub_matrix.sum(axis=1) / (len(member_indices) - 1)
            medoid_idx = member_indices[int(np.argmin(avg_distances))]

        result[cluster_id] = {
            "article_ids": member_article_ids,
            "medoid_id": article_ids[medoid_idx],
            "size": len(member_article_ids),
        }

    return result
