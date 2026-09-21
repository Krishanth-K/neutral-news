"""
Event clustering and database persistence.

Supports two modes:

  Incremental (default):
    Assign newly-embedded articles to existing events or create new events for
    them. Does NOT clear existing events — analysis, explanations, and event IDs
    are preserved across pipeline runs.

  Full (--full flag):
    Clear all events and recluster the entire article corpus from scratch.
    Use when tuning the distance threshold or recovering from a corrupt state.
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
from neutral_news.embed.incremental import incremental_group_and_persist

log = logging.getLogger(__name__)


def clear_existing_events(conn) -> None:
    """Clear existing events and their article associations (cascades to analysis & explanations)."""
    with conn.cursor() as cur:
        cur.execute("DELETE FROM events;")
    log.info("Cleared existing events and event_articles records.")


def group_and_persist_events(
    conn,
    threshold: float = 0.40,
    linkage: str = "complete",
    incremental: bool = True,
) -> list[str] | dict[str, int]:
    """Cluster articles into events and persist to PostgreSQL.

    Args:
        conn: psycopg connection
        threshold: HAC distance threshold cutoff (default: 0.40)
        linkage: HAC linkage method (default: 'complete')
        incremental: If True (default), only process newly-embedded articles
                     and assign or create events without clearing existing ones.
                     If False, clear all events and recluster the full corpus.

    Returns:
        Incremental mode: summary dict {"assigned": N, "created": N, "skipped": N}
        Full mode: list of generated event IDs
    """
    if incremental:
        return _group_incremental(conn, threshold, linkage)
    else:
        return _group_full(conn, threshold, linkage)


def _group_incremental(conn, threshold: float, linkage: str) -> dict[str, int]:
    """Incremental mode: assign-or-create for unassigned articles only."""
    print(f"[GROUP] Running in INCREMENTAL mode (threshold={threshold}, linkage={linkage})...")
    result = incremental_group_and_persist(conn, threshold=threshold, linkage=linkage)
    conn.commit()
    print(
        f"[GROUP] Incremental done — "
        f"assigned={result['assigned']}, created={result['created']}, skipped={result['skipped']}"
    )
    return result


def _group_full(conn, threshold: float, linkage: str) -> list[str]:
    """Full mode: clear everything and recluster the entire corpus."""
    print(f"[GROUP] Running in FULL mode (threshold={threshold}, linkage={linkage})...")
    print("[GROUP] Computing pairwise distance matrix for ALL embedded articles...")
    distances, article_ids = build_distance_matrix(conn)

    if len(article_ids) == 0:
        print("[GROUP] No embedded articles found to cluster.")
        return []

    print(f"[GROUP] Running HAC on {len(article_ids)} articles...")
    clusters = cluster_articles_hac(
        distances=distances,
        article_ids=article_ids,
        distance_threshold=threshold,
        linkage_method=linkage,
    )

    multi_count = sum(1 for c in clusters.values() if c["size"] > 1)
    print(f"[GROUP] Identified {len(clusters)} events total ({multi_count} multi-article events).")

    print("[GROUP] Clearing previous events and event_articles...")
    clear_existing_events(conn)

    print(f"[GROUP] Persisting {len(clusters)} events to database...")
    event_ids = save_event_clusters(clusters, conn=conn)
    conn.commit()

    print(f"[GROUP] Successfully persisted {len(event_ids)} events with linked event_articles.")
    return event_ids


def main():
    parser = argparse.ArgumentParser(
        description="Group articles into events and persist to database.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Modes:
  Default (incremental): only processes newly-embedded articles.
                         Existing events, analyses, and explanations are preserved.
  --full:                clears all events and reclusters the entire corpus from scratch.
                         Use when tuning the threshold or recovering from a bad state.
        """,
    )
    parser.add_argument(
        "--threshold", type=float, default=0.40,
        help="HAC distance threshold cutoff (default: 0.40)"
    )
    parser.add_argument(
        "--linkage", type=str, default="complete",
        choices=["complete", "average", "single"],
        help="HAC linkage method (default: complete)"
    )
    parser.add_argument(
        "--full", action="store_true",
        help="Full recluster mode: clear all events and rebuild from scratch"
    )
    args = parser.parse_args()

    try:
        with psycopg.connect(DATABASE_URL) as conn:
            group_and_persist_events(
                conn,
                threshold=args.threshold,
                linkage=args.linkage,
                incremental=not args.full,
            )
    except psycopg.OperationalError as exc:
        print(f"[FATAL] Database connection failed: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
