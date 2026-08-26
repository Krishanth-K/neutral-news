
from datetime import datetime

import numpy as np
import torch
import torch.nn.functional as F


def calculate_time_dist(publish_time_a: datetime, publish_time_b: datetime) -> float:
    """Returns the absolute difference in hours between two publication timestamps."""
    return abs((publish_time_a - publish_time_b).total_seconds() / 3600)


# TODO: Include entity distance
def calculate_entity_dist(entity_a, entity_b) -> float:
    """Returns a distance score based on shared named entities.

    TODO: Not yet implemented — requires entity extraction upstream.
    Returns 0.0 (maximum similarity) as a neutral placeholder.
    """
    return 0.0


def build_distance_matrix(
    conn,
) -> tuple[np.ndarray, list[str]]:
    """Computes the full pairwise distance matrix for all embedded articles.

    Suitable for use with HAC (e.g. scipy.cluster.hierarchy.linkage).

    Distance is a weighted sum:
        0.55 — cosine distance between embeddings (semantic similarity)
        0.25 — time distance (absolute difference in hours)
        0.20 — entity distance (shared named entities, TODO)

    Returns:
        distances   : np.ndarray of shape (n, n), symmetric, zero diagonal
        article_ids : list[str] of length n — row/column labels for the matrix
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT a.id, a.published_at, e.embedding
            FROM articles a
            JOIN article_embeddings e ON e.article_id = a.id
            ORDER BY a.id;
            """
        )
        rows = cur.fetchall()

    if not rows:
        return np.empty((0, 0)), []

    n = len(rows)
    article_ids = [str(row[0]) for row in rows]
    publish_times = [row[1] for row in rows]

    # --- Embedding distance (vectorised) ---
    # Stack all embeddings into (n, dim) and compute the full cosine similarity
    # matrix in one matrix multiply: sim[i,j] = normed[i] · normed[j]
    embeddings = torch.tensor(
        [row[2] for row in rows], dtype=torch.float32
    )  # (n, dim)
    normed = F.normalize(embeddings, p=2, dim=1)
    cosine_sim = (normed @ normed.T).numpy()  # (n, n), values in [-1, 1]
    embedding_dist = 1.0 - cosine_sim           # cosine distance in [0, 2]

    # --- Time distance (pairwise) ---
    time_dist = np.zeros((n, n), dtype=np.float32)
    for i in range(n):
        for j in range(i + 1, n):
            d = calculate_time_dist(publish_times[i], publish_times[j])
            time_dist[i, j] = d
            time_dist[j, i] = d

    # --- Entity distance (pairwise, TODO) ---
    # Returns 0.0 for all pairs until entity extraction is implemented.
    entity_dist = np.zeros((n, n), dtype=np.float32)

    distances = 0.55 * embedding_dist + 0.25 * time_dist + 0.2 * entity_dist
    np.fill_diagonal(distances, 0.0)

    return distances, article_ids
