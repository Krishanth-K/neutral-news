"""
Comprehensive automated test suite for neutral-news.

Covers:
1. Database Schema & Table structure
2. Articles & Analysis CRUD operations (including event_analysis upsert and cascade)
3. Quote distribution analysis logic
4. Missing context (entity set difference) analysis logic
5. Event clustering & medoid calculations
"""

from __future__ import annotations

import unittest
import psycopg
import numpy as np

from neutral_news.config import DATABASE_URL
from neutral_news.db.articles import (
    insert_article,
    insert_entity,
    insert_quote,
    save_event_cluster,
    get_event_by_article_id,
    get_articles_for_event,
    get_all_events,
    retrieve_quotes_for_event,
    retrieve_entities_by_article_id,
    retrieve_event_articles_id_by_source,
    upsert_event_analysis,
    get_event_analysis,
    clear_embeddings,
)
from neutral_news.analyse.analysis import (
    analyse_quote_distribution,
    analyse_missing_context,
    analyse_event,
)
from neutral_news.embed.cluster import cluster_articles_hac


class TestDatabaseAndSchema(unittest.TestCase):
    """Test database schema integrity and table structures."""

    def test_schema_tables_exist(self):
        with psycopg.connect(DATABASE_URL) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT table_name 
                    FROM information_schema.tables 
                    WHERE table_schema = 'public';
                    """
                )
                tables = {row[0] for row in cur.fetchall()}

        expected_tables = {
            "articles",
            "article_embeddings",
            "quotes",
            "entities",
            "events",
            "event_articles",
            "event_explanations",
            "event_analysis",
        }
        for table in expected_tables:
            self.assertIn(table, tables, f"Expected table '{table}' not found in database schema")


class TestArticlesAndAnalysisCRUD(unittest.TestCase):
    """Test database helper and CRUD functions."""

    def setUp(self):
        self.conn = psycopg.connect(DATABASE_URL)
        # Create test articles
        self.test_articles = [
            {
                "source_name": "Test Outlet A",
                "article_url": "https://test.example.com/article-1",
                "headline": "Test Headline 1 - Major Economic Policy Announcement",
                "published_at": "2026-09-01T10:00:00Z",
            },
            {
                "source_name": "Test Outlet B",
                "article_url": "https://test.example.com/article-2",
                "headline": "Test Headline 2 - Policy Reforms Unveiled by Government",
                "published_at": "2026-09-01T11:00:00Z",
            },
        ]
        for art in self.test_articles:
            insert_article(art, conn=self.conn)
        self.conn.commit()

        # Retrieve created article IDs
        with self.conn.cursor() as cur:
            cur.execute(
                "SELECT id, source_name, article_url FROM articles WHERE article_url IN (%s, %s);",
                (self.test_articles[0]["article_url"], self.test_articles[1]["article_url"]),
            )
            rows = cur.fetchall()
            self.article_ids = {row[2]: str(row[0]) for row in rows}

        self.art_id_1 = self.article_ids[self.test_articles[0]["article_url"]]
        self.art_id_2 = self.article_ids[self.test_articles[1]["article_url"]]

    def tearDown(self):
        # Clean up test records
        with self.conn.cursor() as cur:
            cur.execute(
                "DELETE FROM articles WHERE article_url IN (%s, %s);",
                (self.test_articles[0]["article_url"], self.test_articles[1]["article_url"]),
            )
        self.conn.commit()
        self.conn.close()

    def test_quotes_and_entities_crud(self):
        # Insert test quotes
        insert_quote(self.art_id_1, "The economy will grow by 8%", "Finance Minister", "government", conn=self.conn)
        insert_quote(self.art_id_1, "Growth targets are unrealistic", "Opposition Leader", "opposition", conn=self.conn)
        insert_quote(self.art_id_2, "Inflation remains under control", "RBI Governor", "expert", conn=self.conn)
        self.conn.commit()

        # Insert test entities
        insert_entity(self.art_id_1, "Finance Ministry", "ORG", conn=self.conn)
        insert_entity(self.art_id_1, "New Delhi", "GPE", conn=self.conn)
        insert_entity(self.art_id_1, "GST", "LAW", conn=self.conn)

        insert_entity(self.art_id_2, "RBI", "ORG", conn=self.conn)
        insert_entity(self.art_id_2, "New Delhi", "GPE", conn=self.conn)
        self.conn.commit()

        # Create event cluster linking both articles
        event_id = save_event_cluster(
            medoid_id=self.art_id_1,
            article_ids=[self.art_id_1, self.art_id_2],
            title="Economic Policy Announcement Cluster",
            conn=self.conn,
        )
        self.conn.commit()

        try:
            # Verify event querying
            event_by_art = get_event_by_article_id(self.art_id_2, conn=self.conn)
            self.assertIsNotNone(event_by_art)
            self.assertEqual(event_by_art["id"], event_id)

            articles_in_event = get_articles_for_event(event_id, conn=self.conn)
            self.assertEqual(len(articles_in_event), 2)

            # Test quote retrieval for event
            quotes = retrieve_quotes_for_event(event_id, conn=self.conn)
            self.assertEqual(len(quotes), 3)

            # Test entity retrieval
            entities = retrieve_entities_by_article_id([self.art_id_1, self.art_id_2], conn=self.conn)
            entity_texts = {e["text"] for e in entities}
            self.assertIn("Finance Ministry", entity_texts)
            self.assertIn("RBI", entity_texts)
            self.assertIn("New Delhi", entity_texts)

            # Test Quote Distribution Analysis
            quote_analysis = analyse_quote_distribution(event_id, conn=self.conn)
            self.assertEqual(quote_analysis["total_quotes"], 3)
            self.assertIn("Test Outlet A", quote_analysis["by_source"])
            self.assertIn("Test Outlet B", quote_analysis["by_source"])
            
            outlet_a_quotes = quote_analysis["by_source"]["Test Outlet A"]
            self.assertEqual(outlet_a_quotes["counts"]["government"], 1)
            self.assertEqual(outlet_a_quotes["counts"]["opposition"], 1)
            self.assertEqual(outlet_a_quotes["counts"]["expert"], 0)

            outlet_b_quotes = quote_analysis["by_source"]["Test Outlet B"]
            self.assertEqual(outlet_b_quotes["counts"]["expert"], 1)
            self.assertEqual(outlet_b_quotes["dominant_role"], "expert")

            # Test Missing Context Analysis
            missing_analysis = analyse_missing_context(event_id, conn=self.conn)
            self.assertEqual(missing_analysis["universal_entity_count"], 4) # Finance Ministry, New Delhi, GST, RBI
            
            outlet_a_missing = missing_analysis["missing_by_source"]["Test Outlet A"]
            self.assertIn("RBI", outlet_a_missing["missing_entities"])
            self.assertIn("GST", outlet_a_missing["present_entities"])

            outlet_b_missing = missing_analysis["missing_by_source"]["Test Outlet B"]
            self.assertIn("Finance Ministry", outlet_b_missing["missing_entities"])
            self.assertIn("GST", outlet_b_missing["missing_entities"])

            # Test Combined Analysis & Upsert
            combined_analysis = analyse_event(event_id, conn=self.conn)
            upsert_event_analysis(
                event_id=event_id,
                quote_distribution=combined_analysis["quote_distribution"],
                missing_context=combined_analysis["missing_context"],
                conn=self.conn,
            )
            self.conn.commit()

            # Retrieve persisted event analysis
            saved_analysis = get_event_analysis(event_id, conn=self.conn)
            self.assertIsNotNone(saved_analysis)
            self.assertEqual(saved_analysis["event_id"], event_id)
            self.assertEqual(saved_analysis["quote_distribution"]["total_quotes"], 3)
            self.assertEqual(saved_analysis["missing_context"]["universal_entity_count"], 4)

        finally:
            # Clean up event
            with self.conn.cursor() as cur:
                cur.execute("DELETE FROM events WHERE id = %s;", (event_id,))
            self.conn.commit()

            # Verify CASCADE deleted event_analysis
            self.assertIsNone(get_event_analysis(event_id, conn=self.conn))

    def test_clear_embeddings_and_status_reset(self):
        # Insert sample embedding records
        with self.conn.cursor() as cur:
            dummy_vec = "[" + ",".join(["0.0"] * 768) + "]"
            cur.execute(
                "INSERT INTO article_embeddings (article_id, embedding) VALUES (%s, %s::vector);",
                (self.art_id_1, dummy_vec),
            )
            cur.execute(
                "UPDATE articles SET embedding_status = 'completed' WHERE id = %s;",
                (self.art_id_1,),
            )
        self.conn.commit()

        # Verify embedding exists and status is set
        with self.conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM article_embeddings WHERE article_id = %s;", (self.art_id_1,))
            self.assertEqual(cur.fetchone()[0], 1)
            cur.execute("SELECT embedding_status FROM articles WHERE id = %s;", (self.art_id_1,))
            self.assertEqual(cur.fetchone()[0], "completed")

        # Execute clear_embeddings
        cleared_count = clear_embeddings(conn=self.conn)
        self.conn.commit()
        self.assertGreaterEqual(cleared_count, 1)

        # Verify embeddings table is empty and articles status is reset to NULL
        with self.conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM article_embeddings;")
            self.assertEqual(cur.fetchone()[0], 0)
            cur.execute("SELECT embedding_status FROM articles WHERE id IN (%s, %s);", (self.art_id_1, self.art_id_2))
            statuses = [r[0] for r in cur.fetchall()]
            for s in statuses:
                self.assertIsNone(s)



class TestClusteringLogic(unittest.TestCase):
    """Test HAC clustering and medoid computation logic."""

    def test_hac_clustering_basic(self):
        # 3 articles: Art 0 and 1 are very close (dist=0.1), Art 2 is far (dist=0.8)
        dist_matrix = np.array([
            [0.0, 0.1, 0.8],
            [0.1, 0.0, 0.8],
            [0.8, 0.8, 0.0],
        ])
        art_ids = ["art-0", "art-1", "art-2"]

        clusters = cluster_articles_hac(
            distances=dist_matrix,
            article_ids=art_ids,
            distance_threshold=0.30,
            linkage_method="complete",
        )

        self.assertEqual(len(clusters), 2)
        sizes = sorted([c["size"] for c in clusters.values()])
        self.assertEqual(sizes, [1, 2])


if __name__ == "__main__":
    unittest.main()
