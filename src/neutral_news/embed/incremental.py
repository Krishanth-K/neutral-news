"""
Incremental event grouping for Media Lens.

Implements the "assign-or-create" strategy:

  1. Find articles that have embeddings but are not yet in any event (unassigned).
  2. Micro-cluster the unassigned articles among themselves using HAC
     (handles multiple new articles about the same story arriving together).
  3. For each resulting micro-cluster, compute distance to every existing
     event's medoid article.
  4. If distance to the nearest existing event ≤ threshold → assign to that event.
  5. Otherwise → create a new event for the micro-cluster.
  6. Recompute medoid for any event that received new members.

Complexity: O(new² + new × events) per run — fast and bounded compared to
the full O(N²) recluster.

Note: articles with no embedding are silently skipped (they'll be embedded on
the next pipeline run and processed in the following incremental pass).
"""

from __future__ import annotations

import logging

import numpy as np

from neutral_news.db.articles import (
    get_event_medoid_ids,
    get_unassigned_embedded_articles,
    link_event_articles,
    save_event_cluster,
    update_event_medoid,
)
from neutral_news.embed.cluster import cluster_articles_hac
from neutral_news.embed.distance import (
    build_distance_matrix_for_articles,
    compute_distance_between_two_articles,
)

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Distance helpers
# ---------------------------------------------------------------------------


def compute_new_to_event_distances(
    new_article_ids: list[str],
    event_medoid_pairs: list[tuple[str, str]],
    conn,
    threshold: float = 0.40,
) -> dict[str, tuple[str, float] | None]:
    """Compute distance from each new article to every existing event's medoid.

    Args:
        new_article_ids: Article IDs to assign.
        event_medoid_pairs: [(event_id, medoid_article_id), ...]
        conn: Active psycopg connection.
        threshold: Only events within this distance are considered candidates.

    Returns:
        Mapping of article_id → (event_id, distance) for the closest event
        within threshold, or None if no existing event is close enough.
    """
    result: dict[str, tuple[str, float] | None] = {}

    for new_id in new_article_ids:
        best_event_id = None
        best_dist = float("inf")

        for event_id, medoid_id in event_medoid_pairs:
            if new_id == medoid_id:
                # Article is somehow already a medoid — should not happen but guard it
                best_event_id = event_id
                best_dist = 0.0
                break
            try:
                info = compute_distance_between_two_articles(new_id, medoid_id, conn)
                d = info["total_distance"]
            except Exception as exc:
                log.debug("Distance calc failed (%s ↔ %s): %s", new_id, medoid_id, exc)
                continue

            if d < best_dist:
                best_dist = d
                best_event_id = event_id

        if best_event_id is not None and best_dist <= threshold:
            result[new_id] = (best_event_id, best_dist)
        else:
            result[new_id] = None

    return result


def recompute_event_medoid(event_id: str, conn) -> str | None:
    """Recompute the medoid article for an event after new members join.

    Fetches all member article IDs for the event, builds a small intra-event
    distance matrix, and picks the article with the smallest mean distance
    to all other members.

    Returns the medoid article ID, or None if the event has no members.
    """
    with conn.cursor() as cur:
        cur.execute(
            "SELECT article_id FROM event_articles WHERE event_id = %s;",
            (event_id,),
        )
        member_ids = [str(row[0]) for row in cur.fetchall()]

    if not member_ids:
        return None
    if len(member_ids) == 1:
        return member_ids[0]

    # Build pairwise distance matrix for this event's members only
    distances, ordered_ids = build_distance_matrix_for_articles(member_ids, conn)
    if len(ordered_ids) == 0:
        return member_ids[0]

    # Medoid = article with minimum mean distance to all others
    mean_dists = distances.sum(axis=1) / max(len(ordered_ids) - 1, 1)
    medoid_idx = int(np.argmin(mean_dists))
    return ordered_ids[medoid_idx]


# ---------------------------------------------------------------------------
# Micro-clustering: cluster new articles among themselves
# ---------------------------------------------------------------------------


def micro_cluster_new_articles(
    new_article_ids: list[str],
    conn,
    threshold: float = 0.40,
    linkage: str = "complete",
) -> dict[int, dict]:
    """Run HAC on the new (unassigned) articles only.

    Returns the same cluster dict format as cluster_articles_hac():
        {cluster_id: {"article_ids": [...], "medoid_id": str, "size": int}}

    If there is only one new article, returns a single trivial cluster.
    """
    if len(new_article_ids) == 0:
        return {}
    if len(new_article_ids) == 1:
        return {1: {"article_ids": new_article_ids, "medoid_id": new_article_ids[0], "size": 1}}

    distances, ordered_ids = build_distance_matrix_for_articles(new_article_ids, conn)
    if len(ordered_ids) == 0:
        return {}

    return cluster_articles_hac(
        distances=distances,
        article_ids=ordered_ids,
        distance_threshold=threshold,
        linkage_method=linkage,
    )


# ---------------------------------------------------------------------------
# Main incremental entry point
# ---------------------------------------------------------------------------


def incremental_group_and_persist(
    conn,
    threshold: float = 0.40,
    linkage: str = "complete",
) -> dict[str, int]:
    """Assign new articles to existing events or create new events for them.

    Returns a summary dict: {"assigned": N, "created": N, "skipped": N}
    """
    # 1. Find articles not yet in any event
    unassigned = get_unassigned_embedded_articles(conn)
    if not unassigned:
        log.info("[INCREMENTAL] No unassigned articles to process.")
        return {"assigned": 0, "created": 0, "skipped": 0}

    print(f"[INCREMENTAL] {len(unassigned)} unassigned article(s) to process.")

    # 2. Get existing event medoids
    existing_medoids = get_event_medoid_ids(conn)
    print(f"[INCREMENTAL] {len(existing_medoids)} existing event(s) with medoids.")

    # 3. Micro-cluster the new articles among themselves
    micro_clusters = micro_cluster_new_articles(unassigned, conn, threshold, linkage)
    print(f"[INCREMENTAL] Micro-clustered into {len(micro_clusters)} group(s).")

    assigned = 0
    created = 0
    skipped = 0
    # Track which existing events received new members (need medoid refresh)
    events_needing_medoid_update: set[str] = set()

    for cluster_data in micro_clusters.values():
        cluster_article_ids: list[str] = cluster_data["article_ids"]
        cluster_medoid: str = cluster_data["medoid_id"]

        if not existing_medoids:
            # No existing events at all → always create
            event_id = save_event_cluster(
                medoid_id=cluster_medoid,
                article_ids=cluster_article_ids,
                conn=conn,
            )
            print(f"  + Created new event {event_id[:8]}… ({len(cluster_article_ids)} article(s))")
            # Add to medoid list for subsequent clusters in this same run
            existing_medoids.append((event_id, cluster_medoid))
            created += 1
            continue

        # 4. Find the closest existing event to this cluster's medoid article
        assignment = compute_new_to_event_distances(
            [cluster_medoid], existing_medoids, conn, threshold
        )
        closest = assignment.get(cluster_medoid)

        if closest is not None:
            # 5a. Assign all cluster members to the closest existing event
            target_event_id, dist = closest
            link_event_articles(target_event_id, cluster_article_ids, conn=conn)
            events_needing_medoid_update.add(target_event_id)
            print(
                f"  → Assigned {len(cluster_article_ids)} article(s) to event "
                f"{target_event_id[:8]}… (dist={dist:.3f})"
            )
            assigned += len(cluster_article_ids)
        else:
            # 5b. No close enough existing event → create a new one
            event_id = save_event_cluster(
                medoid_id=cluster_medoid,
                article_ids=cluster_article_ids,
                conn=conn,
            )
            print(
                f"  + Created new event {event_id[:8]}… "
                f"({len(cluster_article_ids)} article(s), no close match)"
            )
            # Add to medoid list for subsequent clusters in this same run
            existing_medoids.append((event_id, cluster_medoid))
            created += 1

    # 6. Recompute medoids for events that received new members
    for event_id in events_needing_medoid_update:
        new_medoid = recompute_event_medoid(event_id, conn)
        if new_medoid:
            update_event_medoid(event_id, new_medoid, conn=conn)
            log.debug("Updated medoid for event %s → %s", event_id[:8], new_medoid[:8])

    print(
        f"[INCREMENTAL] Done — assigned={assigned}, created={created}, skipped={skipped}"
    )
    return {"assigned": assigned, "created": created, "skipped": skipped}
