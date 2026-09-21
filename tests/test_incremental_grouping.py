"""
Unit tests for incremental event grouping (embed/incremental.py).

All DB calls are mocked — no live database required.
Tests cover the core assign-or-create logic:
  - Unassigned articles within threshold → assigned to existing event
  - Unassigned articles outside threshold → new event created
  - Multiple new articles clustering together before matching existing events
  - Medoid recomputation after assignment
  - Empty unassigned list → early return
  - No existing events → always creates
"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, call, patch

import numpy as np


# ---------------------------------------------------------------------------
# Helper builders
# ---------------------------------------------------------------------------


def _make_conn():
    """Return a mock psycopg connection with cursor context manager support."""
    conn = MagicMock()
    cursor = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cursor
    return conn, cursor


# ---------------------------------------------------------------------------
# Tests for compute_new_to_event_distances
# ---------------------------------------------------------------------------


class TestComputeNewToEventDistances(unittest.TestCase):
    """Unit tests for the per-article nearest-event lookup."""

    @patch("neutral_news.embed.incremental.compute_distance_between_two_articles")
    def test_assigns_when_within_threshold(self, mock_dist):
        """Article whose closest event medoid distance ≤ threshold gets assigned."""
        from neutral_news.embed.incremental import compute_new_to_event_distances

        mock_dist.return_value = {"total_distance": 0.25}
        conn, _ = _make_conn()

        result = compute_new_to_event_distances(
            new_article_ids=["article-1"],
            event_medoid_pairs=[("event-A", "medoid-A")],
            conn=conn,
            threshold=0.40,
        )

        self.assertEqual(result["article-1"], ("event-A", 0.25))

    @patch("neutral_news.embed.incremental.compute_distance_between_two_articles")
    def test_returns_none_when_above_threshold(self, mock_dist):
        """Article whose closest event is beyond threshold gets None (will create new event)."""
        from neutral_news.embed.incremental import compute_new_to_event_distances

        mock_dist.return_value = {"total_distance": 0.75}
        conn, _ = _make_conn()

        result = compute_new_to_event_distances(
            new_article_ids=["article-1"],
            event_medoid_pairs=[("event-A", "medoid-A")],
            conn=conn,
            threshold=0.40,
        )

        self.assertIsNone(result["article-1"])

    @patch("neutral_news.embed.incremental.compute_distance_between_two_articles")
    def test_picks_closest_of_multiple_events(self, mock_dist):
        """When multiple events exist, the nearest one below threshold is chosen."""
        from neutral_news.embed.incremental import compute_new_to_event_distances

        # event-A is farther, event-B is closer
        mock_dist.side_effect = [
            {"total_distance": 0.38},  # article-1 ↔ medoid-A
            {"total_distance": 0.15},  # article-1 ↔ medoid-B
        ]
        conn, _ = _make_conn()

        result = compute_new_to_event_distances(
            new_article_ids=["article-1"],
            event_medoid_pairs=[("event-A", "medoid-A"), ("event-B", "medoid-B")],
            conn=conn,
            threshold=0.40,
        )

        self.assertEqual(result["article-1"], ("event-B", 0.15))

    @patch("neutral_news.embed.incremental.compute_distance_between_two_articles")
    def test_handles_distance_calc_failure_gracefully(self, mock_dist):
        """If distance calculation raises, that event pair is skipped."""
        from neutral_news.embed.incremental import compute_new_to_event_distances

        mock_dist.side_effect = [
            Exception("embedding not found"),   # event-A fails
            {"total_distance": 0.20},           # event-B succeeds
        ]
        conn, _ = _make_conn()

        result = compute_new_to_event_distances(
            new_article_ids=["article-1"],
            event_medoid_pairs=[("event-A", "medoid-A"), ("event-B", "medoid-B")],
            conn=conn,
            threshold=0.40,
        )

        self.assertEqual(result["article-1"], ("event-B", 0.20))

    def test_no_existing_events_returns_none(self):
        """With no existing events, every article gets None (new event will be created)."""
        from neutral_news.embed.incremental import compute_new_to_event_distances

        conn, _ = _make_conn()

        result = compute_new_to_event_distances(
            new_article_ids=["article-1", "article-2"],
            event_medoid_pairs=[],
            conn=conn,
            threshold=0.40,
        )

        self.assertIsNone(result["article-1"])
        self.assertIsNone(result["article-2"])


# ---------------------------------------------------------------------------
# Tests for micro_cluster_new_articles
# ---------------------------------------------------------------------------


class TestMicroClusterNewArticles(unittest.TestCase):

    def test_single_article_returns_trivial_cluster(self):
        """One new article → one cluster with itself as medoid."""
        from neutral_news.embed.incremental import micro_cluster_new_articles

        conn, _ = _make_conn()
        result = micro_cluster_new_articles(["only-article"], conn, threshold=0.40)

        self.assertEqual(len(result), 1)
        cluster = list(result.values())[0]
        self.assertEqual(cluster["medoid_id"], "only-article")
        self.assertEqual(cluster["size"], 1)

    def test_empty_input_returns_empty(self):
        """No new articles → empty cluster dict."""
        from neutral_news.embed.incremental import micro_cluster_new_articles

        conn, _ = _make_conn()
        result = micro_cluster_new_articles([], conn, threshold=0.40)
        self.assertEqual(result, {})

    @patch("neutral_news.embed.incremental.build_distance_matrix_for_articles")
    @patch("neutral_news.embed.incremental.cluster_articles_hac")
    def test_delegates_to_hac_for_multiple_articles(self, mock_hac, mock_matrix):
        """Multiple articles → delegates to build_distance_matrix_for_articles + cluster_articles_hac."""
        from neutral_news.embed.incremental import micro_cluster_new_articles

        mock_matrix.return_value = (np.zeros((2, 2)), ["a-1", "a-2"])
        mock_hac.return_value = {
            1: {"article_ids": ["a-1", "a-2"], "medoid_id": "a-1", "size": 2}
        }
        conn, _ = _make_conn()

        result = micro_cluster_new_articles(["a-1", "a-2"], conn, threshold=0.40)

        mock_matrix.assert_called_once()
        mock_hac.assert_called_once()
        self.assertIn(1, result)
        self.assertEqual(result[1]["size"], 2)


# ---------------------------------------------------------------------------
# Tests for incremental_group_and_persist (full flow)
# ---------------------------------------------------------------------------


class TestIncrementalGroupAndPersist(unittest.TestCase):

    @patch("neutral_news.embed.incremental.get_unassigned_embedded_articles", return_value=[])
    def test_early_return_when_nothing_to_process(self, mock_unassigned):
        """If no unassigned articles exist, returns zeros without touching DB."""
        from neutral_news.embed.incremental import incremental_group_and_persist

        conn, _ = _make_conn()
        result = incremental_group_and_persist(conn)

        self.assertEqual(result, {"assigned": 0, "created": 0, "skipped": 0})

    @patch("neutral_news.embed.incremental.update_event_medoid")
    @patch("neutral_news.embed.incremental.recompute_event_medoid", return_value="article-1")
    @patch("neutral_news.embed.incremental.link_event_articles")
    @patch("neutral_news.embed.incremental.save_event_cluster")
    @patch("neutral_news.embed.incremental.compute_new_to_event_distances")
    @patch("neutral_news.embed.incremental.micro_cluster_new_articles")
    @patch("neutral_news.embed.incremental.get_event_medoid_ids")
    @patch("neutral_news.embed.incremental.get_unassigned_embedded_articles")
    def test_new_article_assigned_to_existing_event(
        self, mock_unassigned, mock_medoids, mock_micro,
        mock_dist, mock_save, mock_link, mock_recompute, mock_update
    ):
        """New article within threshold of an existing event → link_event_articles called, no new event."""
        from neutral_news.embed.incremental import incremental_group_and_persist

        mock_unassigned.return_value = ["article-1"]
        mock_medoids.return_value = [("event-X", "medoid-X")]
        mock_micro.return_value = {
            1: {"article_ids": ["article-1"], "medoid_id": "article-1", "size": 1}
        }
        mock_dist.return_value = {"article-1": ("event-X", 0.20)}

        conn, _ = _make_conn()
        result = incremental_group_and_persist(conn, threshold=0.40)

        mock_link.assert_called_once_with("event-X", ["article-1"], conn=conn)
        mock_save.assert_not_called()
        self.assertEqual(result["assigned"], 1)
        self.assertEqual(result["created"], 0)

    @patch("neutral_news.embed.incremental.update_event_medoid")
    @patch("neutral_news.embed.incremental.recompute_event_medoid")
    @patch("neutral_news.embed.incremental.link_event_articles")
    @patch("neutral_news.embed.incremental.save_event_cluster", return_value="new-event-id")
    @patch("neutral_news.embed.incremental.compute_new_to_event_distances")
    @patch("neutral_news.embed.incremental.micro_cluster_new_articles")
    @patch("neutral_news.embed.incremental.get_event_medoid_ids")
    @patch("neutral_news.embed.incremental.get_unassigned_embedded_articles")
    def test_new_article_creates_new_event_when_no_match(
        self, mock_unassigned, mock_medoids, mock_micro,
        mock_dist, mock_save, mock_link, mock_recompute, mock_update
    ):
        """New article outside threshold of all events → save_event_cluster called."""
        from neutral_news.embed.incremental import incremental_group_and_persist

        mock_unassigned.return_value = ["article-1"]
        mock_medoids.return_value = [("event-X", "medoid-X")]
        mock_micro.return_value = {
            1: {"article_ids": ["article-1"], "medoid_id": "article-1", "size": 1}
        }
        mock_dist.return_value = {"article-1": None}  # no match

        conn, _ = _make_conn()
        result = incremental_group_and_persist(conn, threshold=0.40)

        mock_save.assert_called_once_with(
            medoid_id="article-1",
            article_ids=["article-1"],
            conn=conn,
        )
        mock_link.assert_not_called()
        self.assertEqual(result["created"], 1)
        self.assertEqual(result["assigned"], 0)

    @patch("neutral_news.embed.incremental.update_event_medoid")
    @patch("neutral_news.embed.incremental.recompute_event_medoid")
    @patch("neutral_news.embed.incremental.link_event_articles")
    @patch("neutral_news.embed.incremental.save_event_cluster", return_value="brand-new-event")
    @patch("neutral_news.embed.incremental.micro_cluster_new_articles")
    @patch("neutral_news.embed.incremental.get_event_medoid_ids", return_value=[])
    @patch("neutral_news.embed.incremental.get_unassigned_embedded_articles")
    def test_creates_event_when_no_existing_events(
        self, mock_unassigned, mock_medoids, mock_micro,
        mock_save, mock_link, mock_recompute, mock_update
    ):
        """When there are no existing events at all, new events are always created."""
        from neutral_news.embed.incremental import incremental_group_and_persist

        mock_unassigned.return_value = ["article-1"]
        mock_micro.return_value = {
            1: {"article_ids": ["article-1"], "medoid_id": "article-1", "size": 1}
        }

        conn, _ = _make_conn()
        result = incremental_group_and_persist(conn, threshold=0.40)

        mock_save.assert_called_once()
        mock_link.assert_not_called()
        self.assertEqual(result["created"], 1)

    @patch("neutral_news.embed.incremental.update_event_medoid")
    @patch("neutral_news.embed.incremental.recompute_event_medoid", return_value="article-1")
    @patch("neutral_news.embed.incremental.link_event_articles")
    @patch("neutral_news.embed.incremental.save_event_cluster")
    @patch("neutral_news.embed.incremental.compute_new_to_event_distances")
    @patch("neutral_news.embed.incremental.micro_cluster_new_articles")
    @patch("neutral_news.embed.incremental.get_event_medoid_ids")
    @patch("neutral_news.embed.incremental.get_unassigned_embedded_articles")
    def test_medoid_recomputed_after_assignment(
        self, mock_unassigned, mock_medoids, mock_micro,
        mock_dist, mock_save, mock_link, mock_recompute, mock_update
    ):
        """After assigning an article to an existing event, recompute_event_medoid is called."""
        from neutral_news.embed.incremental import incremental_group_and_persist

        mock_unassigned.return_value = ["article-new"]
        mock_medoids.return_value = [("event-X", "medoid-X")]
        mock_micro.return_value = {
            1: {"article_ids": ["article-new"], "medoid_id": "article-new", "size": 1}
        }
        mock_dist.return_value = {"article-new": ("event-X", 0.10)}

        conn, _ = _make_conn()
        incremental_group_and_persist(conn, threshold=0.40)

        mock_recompute.assert_called_once_with("event-X", conn)
        mock_update.assert_called_once_with("event-X", "article-1", conn=conn)


# ---------------------------------------------------------------------------
# Tests for group_and_persist_events dispatch
# ---------------------------------------------------------------------------


class TestGroupAndPersistEventsDispatch(unittest.TestCase):

    @patch("neutral_news.embed.group_events.incremental_group_and_persist")
    def test_incremental_true_calls_incremental(self, mock_incremental):
        """incremental=True dispatches to incremental_group_and_persist."""
        from neutral_news.embed.group_events import group_and_persist_events

        mock_incremental.return_value = {"assigned": 0, "created": 0, "skipped": 0}
        conn = MagicMock()

        group_and_persist_events(conn, incremental=True)
        mock_incremental.assert_called_once()

    @patch("neutral_news.embed.group_events.save_event_clusters", return_value=[])
    @patch("neutral_news.embed.group_events.cluster_articles_hac", return_value={})
    @patch("neutral_news.embed.group_events.build_distance_matrix", return_value=(np.empty((0, 0)), []))
    def test_full_false_calls_full_recluster(self, mock_matrix, mock_hac, mock_save):
        """incremental=False triggers full recluster path (build_distance_matrix called)."""
        from neutral_news.embed.group_events import group_and_persist_events

        conn = MagicMock()
        group_and_persist_events(conn, incremental=False)

        mock_matrix.assert_called_once_with(conn)


if __name__ == "__main__":
    unittest.main()
