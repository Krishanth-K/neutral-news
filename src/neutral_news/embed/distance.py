from datetime import datetime

import numpy as np
import torch
import torch.nn.functional as F


def calculate_time_dist(publish_time_a: datetime, publish_time_b: datetime) -> float:
    """Returns the absolute difference in hours between two publication timestamps."""
    return abs((publish_time_a - publish_time_b).total_seconds() / 3600)

def _get_entities_with_article_id(article_id: str, conn):
    with conn.cursor() as cur:
        query = """
            SELECT e.text, e.label
            FROM entities e
            WHERE e.article_id = %s
        """
        params = (article_id,)
        cur.execute(query, params)

        return cur.fetchall()


def calculate_entity_dist(entity_set_a: set, entity_set_b: set) -> float:
    """Returns distance based on shared named entities (0.0 = identical, 1.0 = disjoint)."""
    if not entity_set_a or not entity_set_b:
        return 1.0

    union_len = len(entity_set_a | entity_set_b)
    if union_len == 0:
        return 1.0

    intersection_len = len(entity_set_a & entity_set_b)
    return 1.0 - (intersection_len / union_len)


def _parse_embedding(raw) -> np.ndarray:
    """Parse raw embedding from database (Vector, numpy array, list, or string)."""
    if hasattr(raw, "to_numpy"):
        return raw.to_numpy()
    if isinstance(raw, np.ndarray):
        return raw
    if isinstance(raw, (list, tuple)):
        return np.array(raw, dtype=np.float32)
    if isinstance(raw, str):
        return np.fromstring(raw.strip("[]"), sep=",", dtype=np.float32)
    return np.array(raw, dtype=np.float32)


def compute_distance_between_two_articles(
    article_id_a: str,
    article_id_b: str,
    conn,
    weight_embedding: float = 0.55,
    weight_time: float = 0.25,
    weight_entity: float = 0.20,
) -> dict:
    """Computes individual distance components and the 2x2 distance matrix for two articles.

    Args:
        article_id_a: UUID string for first article
        article_id_b: UUID string for second article
        conn: psycopg database connection
        weight_embedding: weight for embedding distance (default 0.55)
        weight_time: weight for publication time distance in hours (default 0.25)
        weight_entity: weight for entity Jaccard distance (default 0.20)

    Returns:
        dict with metadata, distance metrics, shared entities, and the 2x2 matrix.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT a.id, a.source_name, a.headline, a.published_at, e.embedding
            FROM articles a
            JOIN article_embeddings e ON e.article_id = a.id
            WHERE a.id IN (%s, %s);
            """,
            (article_id_a, article_id_b),
        )
        rows = {str(r[0]): r for r in cur.fetchall()}

    if article_id_a not in rows or article_id_b not in rows:
        raise ValueError(f"One or both articles ({article_id_a}, {article_id_b}) not found with embeddings.")

    row_a = rows[article_id_a]
    row_b = rows[article_id_b]

    # --- 1. Embedding distance ---
    emb_a = torch.tensor(_parse_embedding(row_a[4]), dtype=torch.float32).unsqueeze(0)
    emb_b = torch.tensor(_parse_embedding(row_b[4]), dtype=torch.float32).unsqueeze(0)
    norm_a = F.normalize(emb_a, p=2, dim=1)
    norm_b = F.normalize(emb_b, p=2, dim=1)

    cos_sim = float((norm_a @ norm_b.T).item()) if article_id_a != article_id_b else 1.0
    embedding_dist = max(0.0, 1.0 - cos_sim)

    # --- 2. Time distance ---
    if row_a[3] and row_b[3] and article_id_a != article_id_b:
        time_dist = calculate_time_dist(row_a[3], row_b[3])
    else:
        time_dist = 0.0

    # --- 3. Entity distance ---
    entities_a = set(_get_entities_with_article_id(article_id_a, conn))
    entities_b = set(_get_entities_with_article_id(article_id_b, conn))
    if article_id_a == article_id_b:
        entity_dist = 0.0
    else:
        entity_dist = calculate_entity_dist(entities_a, entities_b)

    # --- Combined weighted distance ---
    if article_id_a == article_id_b:
        total_dist = 0.0
    else:
        total_dist = (
            weight_embedding * embedding_dist
            + weight_time * time_dist
            + weight_entity * entity_dist
        )

    matrix = np.array(
        [[0.0, total_dist], [total_dist, 0.0]],
        dtype=np.float32,
    )

    return {
        "article_a": {
            "id": str(row_a[0]),
            "source": row_a[1],
            "headline": row_a[2],
            "published_at": row_a[3],
        },
        "article_b": {
            "id": str(row_b[0]),
            "source": row_b[1],
            "headline": row_b[2],
            "published_at": row_b[3],
        },
        "cosine_similarity": cos_sim,
        "embedding_distance": embedding_dist,
        "time_distance_hours": time_dist,
        "entities_a": entities_a,
        "entities_b": entities_b,
        "shared_entities": entities_a & entities_b,
        "entity_distance": entity_dist,
        "weights": {
            "embedding": weight_embedding,
            "time": weight_time,
            "entity": weight_entity,
        },
        "total_distance": total_dist,
        "matrix": matrix,
    }


def build_distance_matrix(
    conn,
) -> tuple[np.ndarray, list[str]]:
    """Computes the full pairwise distance matrix for all embedded articles.

    Suitable for use with HAC (e.g. scipy.cluster.hierarchy.linkage).

    Distance is a weighted sum:
        0.55 — cosine distance between embeddings (semantic similarity)
        0.25 — time distance (absolute difference in hours)
        0.20 — entity distance (shared named entities)

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
    raw_embs = [_parse_embedding(row[2]) for row in rows]
    embeddings = torch.tensor(np.array(raw_embs), dtype=torch.float32)  # (n, dim)
    normed = F.normalize(embeddings, p=2, dim=1)
    cosine_sim = (normed @ normed.T).numpy()  # (n, n), values in [-1, 1]
    embedding_dist = 1.0 - cosine_sim           # cosine distance in [0, 2]

    # --- Time distance (pairwise) ---
    time_dist = np.zeros((n, n), dtype=np.float32)
    for i in range(n):
        for j in range(i + 1, n):
            if publish_times[i] and publish_times[j]:
                d = calculate_time_dist(publish_times[i], publish_times[j])
            else:
                d = 0.0
            time_dist[i, j] = d
            time_dist[j, i] = d

    # --- Entity distance (pairwise) ---
    entity_dist = np.zeros((n, n), dtype=np.float32)
    for i in range(n):
        for j in range(i + 1, n):
            id_a, id_b = article_ids[i], article_ids[j]

            entity_a = set(_get_entities_with_article_id(id_a, conn))
            entity_b = set(_get_entities_with_article_id(id_b, conn))

            d = calculate_entity_dist(entity_a, entity_b)
            entity_dist[i, j] = d
            entity_dist[j, i] = d

    distances = 0.55 * embedding_dist + 0.25 * time_dist + 0.2 * entity_dist
    np.fill_diagonal(distances, 0.0)

    return distances, article_ids
