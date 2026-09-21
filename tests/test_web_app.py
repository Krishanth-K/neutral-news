"""Unit tests for Media Lens web API and services."""

from __future__ import annotations

import unittest
from fastapi.testclient import TestClient

from neutral_news.web.app import app
from neutral_news.web.services import (
    get_database_stats,
    get_events_feed,
    get_sources_list,
    get_raw_table_sample,
)


class TestWebAPI(unittest.TestCase):
    """Test suite for FastAPI endpoints."""

    def setUp(self):
        self.client = TestClient(app)

    def test_serve_index_html(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Media Lens", response.text)
        self.assertIn("Evidence Explorer", response.text)

    def test_api_events_feed(self):
        response = self.client.get("/api/events?page=1&page_size=5")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("events", data)
        self.assertIn("pagination", data)
        self.assertGreater(len(data["events"]), 0)

    def test_api_sources_list(self):
        response = self.client.get("/api/sources")
        self.assertEqual(response.status_code, 200)
        sources = response.json()
        self.assertIsInstance(sources, list)

    def test_api_debug_stats(self):
        response = self.client.get("/api/debug/stats")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("counts", data)
        self.assertIn("articles", data["counts"])
        self.assertIn("events", data["counts"])

    def test_api_debug_targets(self):
        response = self.client.get("/api/debug/targets")
        self.assertEqual(response.status_code, 200)
        targets = response.json()
        target_names = {t["target"] for t in targets}
        self.assertIn("run", target_names)
        self.assertIn("embed", target_names)
        self.assertIn("clear-embed", target_names)
        self.assertIn("group", target_names)
        self.assertIn("analyse", target_names)
        self.assertIn("db-up", target_names)

    def test_api_debug_articles_table(self):
        response = self.client.get("/api/debug/articles?limit=10")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("articles", data)
        self.assertIn("total", data)

    def test_api_debug_table_inspection(self):
        response = self.client.get("/api/debug/tables/articles?limit=5")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["table_name"], "articles")
        self.assertIn("columns", data)
        self.assertIn("rows", data)


if __name__ == "__main__":
    unittest.main()
