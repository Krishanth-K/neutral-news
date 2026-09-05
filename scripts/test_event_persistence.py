"""
Test script for event and event_articles persistence and querying.
"""

import psycopg
from neutral_news.config import DATABASE_URL
from neutral_news.db.articles import (
    save_event_cluster,
    save_event_clusters,
    get_event_by_article_id,
    get_articles_for_event,
)
from neutral_news.embed.group_events import group_and_persist_events


def test_event_crud():
    print("=" * 80)
    print("TEST 1: Direct Event Creation and Querying")
    print("=" * 80)

    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id, headline FROM articles WHERE headline IS NOT NULL LIMIT 3;")
            sample_articles = cur.fetchall()

        if len(sample_articles) < 3:
            print("[WARN] Need at least 3 articles in DB to run test.")
            return

        medoid_id = str(sample_articles[0][0])
        medoid_headline = sample_articles[0][1]
        cluster_article_ids = [str(r[0]) for r in sample_articles]

        print(f"Medoid article ID: {medoid_id}")
        print(f"Medoid headline:   {medoid_headline}")
        print(f"Cluster articles:  {cluster_article_ids}")

        # 1. Save single cluster
        print("\n1. Saving test cluster to DB...")
        event_id = save_event_cluster(
            medoid_id=medoid_id,
            article_ids=cluster_article_ids,
            conn=conn,
        )
        conn.commit()
        print(f"✓ Event created with ID: {event_id}")

        # 2. Query event by article ID
        print("\n2. Querying event by article ID (finding event from member article)...")
        target_article = cluster_article_ids[1]
        event_info = get_event_by_article_id(target_article, conn=conn)
        print(f"✓ Found event for article {target_article}:")
        print(f"   Event ID:    {event_info['id']}")
        print(f"   Event Title: {event_info['title']}")
        assert event_info["id"] == event_id, f"Expected {event_id}, got {event_info['id']}"
        assert event_info["title"] == medoid_headline, f"Expected {medoid_headline}, got {event_info['title']}"

        # 3. Query all articles belonging to the event
        print("\n3. Querying all articles for the event...")
        articles_in_event = get_articles_for_event(event_id, conn=conn)
        print(f"✓ Found {len(articles_in_event)} articles linked to event {event_id}:")
        for a in articles_in_event:
            print(f"   - [{a['source_name']}] {a['headline']} (ID: {a['id']})")
        assert len(articles_in_event) == len(cluster_article_ids)

        # Clean up test event
        with conn.cursor() as cur:
            cur.execute("DELETE FROM events WHERE id = %s;", (event_id,))
        conn.commit()
        print("\n✓ Cleaned up test event record.")


def test_clustering_and_persistence():
    print("\n" + "=" * 80)
    print("TEST 2: End-to-End HAC Clustering & Event Persistence")
    print("=" * 80)

    with psycopg.connect(DATABASE_URL) as conn:
        event_ids = group_and_persist_events(conn, threshold=0.40)
        print(f"\n✓ Generated and persisted {len(event_ids)} events.")

        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM events;")
            events_count = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM event_articles;")
            ea_count = cur.fetchone()[0]

            # Find multi-article events
            cur.execute("""
                SELECT ea.event_id, e.title, COUNT(ea.article_id) AS article_count
                FROM event_articles ea
                JOIN events e ON e.id = ea.event_id
                GROUP BY ea.event_id, e.title
                HAVING COUNT(ea.article_id) > 1
                ORDER BY article_count DESC
                LIMIT 5;
            """)
            multi_events = cur.fetchall()

        print(f"\nDatabase verification:")
        print(f"  • Total events in `events` table:                 {events_count}")
        print(f"  • Total mappings in `event_articles` table:       {ea_count}")
        print(f"\nTop Multi-Article Events:")
        for idx, (eid, title, count) in enumerate(multi_events, 1):
            print(f"  {idx}. [{count} articles] {title} (Event ID: {eid})")
            articles = get_articles_for_event(str(eid), conn=conn)
            for art in articles:
                print(f"     - [{art['source_name']}] {art['headline']}")


if __name__ == "__main__":
    test_event_crud()
    test_clustering_and_persistence()
