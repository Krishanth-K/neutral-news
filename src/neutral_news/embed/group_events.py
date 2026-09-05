"""
Event clustering and database persistence.

Clusters embedded articles using Hierarchical Agglomerative Clustering (HAC)
and persists event clusters into `events` and `event_articles` tables.
"""

from __future__ import annotations

import argparse
import logging
import sys
import psycopg

from neutral_news.config import DATABASE_URL
from neutral_news.db.articles import save_event_clusters
from neutral_news.embed.cluster import cluster_articles_hac
from neutral_news.embed.distance import build_distance_matrix

log = logging.getLogger(__name__)


def clear_existing_events(conn) -> None:
    """Clear existing events and their article associations."""
    with conn.cursor() as cur:
        cur.execute("DELETE FROM events;")
    log.info("Cleared existing events and event_articles records.")


def group_and_persist_events(
    conn,
    threshold: float = 0.40,
    linkage: str = "complete",
    clear_existing: bool = True,
) -> list[str]:
    """Computes distance matrix, clusters articles using HAC, and persists events to PostgreSQL.

    Args:
        conn: psycopg connection
        threshold: HAC distance threshold cutoff (default: 0.40)
        linkage: HAC linkage method (default: 'complete')
        clear_existing: Whether to clear previous events before inserting new ones

    Returns:
        List of generated event IDs (UUID strings)
    """
    print(f"[GROUP] Computing pairwise distance matrix for embedded articles...")
    distances, article_ids = build_distance_matrix(conn)

    if len(article_ids) == 0:
        print("[GROUP] No embedded articles found to cluster.")
        return []

    print(f"[GROUP] Running HAC clustering on {len(article_ids)} articles (threshold={threshold}, linkage={linkage})...")
    clusters = cluster_articles_hac(
        distances=distances,
        article_ids=article_ids,
        distance_threshold=threshold,
        linkage_method=linkage,
    )

    multi_count = sum(1 for c in clusters.values() if c["size"] > 1)
    print(f"[GROUP] Identified {len(clusters)} events total ({multi_count} multi-article events).")

    if clear_existing:
        print("[GROUP] Clearing previous events and event_articles...")
        clear_existing_events(conn)

    print(f"[GROUP] Persisting {len(clusters)} events to database...")
    event_ids = save_event_clusters(clusters, conn=conn)
    conn.commit()

    print(f"[GROUP] Successfully persisted {len(event_ids)} events with linked event_articles.")
    return event_ids


def main():
    parser = argparse.ArgumentParser(description="Group articles into events and persist to database.")
    parser.add_argument("--threshold", type=float, default=0.40, help="HAC distance threshold cutoff (default: 0.40)")
    parser.add_argument("--linkage", type=str, default="complete", choices=["complete", "average", "single"], help="HAC linkage method")
    parser.add_argument("--no-clear", action="store_true", help="Do not clear existing events before persisting")
    args = parser.parse_args()

    with psycopg.connect(DATABASE_URL) as conn:
        group_and_persist_events(
            conn,
            threshold=args.threshold,
            linkage=args.linkage,
            clear_existing=not args.no_clear,
        )


if __name__ == "__main__":
    main()
