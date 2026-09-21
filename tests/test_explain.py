"""
Unit tests for the Phase 6 LLM Explainability Layer.

Tests cover:
- prompt.build_prompt() — pure string logic, no LLM call needed
- explain_event.explain_event() — with a mocked Gemini call
- explain_event.explain_all_events() — with a mocked pipeline
"""

import json
import unittest
from unittest.mock import MagicMock, patch


class TestBuildPrompt(unittest.TestCase):
    """Tests for explain/prompt.py — pure string logic, no external dependencies."""

    def setUp(self):
        from neutral_news.explain.prompt import build_prompt
        self.build_prompt = build_prompt

    def _make_quote_distribution(self, sources, counts_per_source=None):
        """Helper to construct a minimal quote_distribution dict."""
        by_source = {}
        for src in sources:
            counts = counts_per_source.get(src, {}) if counts_per_source else {}
            total = sum(counts.values())
            by_source[src] = {
                "total_quotes": total,
                "counts": counts,
                "proportions": {k: v / total if total else 0.0 for k, v in counts.items()},
                "dominant_role": max(counts, key=counts.get) if counts else None,
                "omitted_roles": [r for r in ["government", "opposition", "expert"] if counts.get(r, 0) == 0],
                "quotes": [],
            }
        return {"sources_analyzed": sources, "total_quotes": sum(d["total_quotes"] for d in by_source.values()), "by_source": by_source}

    def _make_missing_context(self, sources, entity_sets=None):
        """Helper to construct a minimal missing_context dict."""
        entity_sets = entity_sets or {src: set() for src in sources}
        universal = set()
        for ents in entity_sets.values():
            universal.update(ents)
        missing_by_source = {}
        for src in sources:
            present = sorted(entity_sets.get(src, set()))
            missing = sorted(universal - entity_sets.get(src, set()))
            missing_by_source[src] = {
                "present_count": len(present),
                "missing_count": len(missing),
                "missing_entities": missing,
                "present_entities": present,
            }
        return {"sources_analyzed": sources, "universal_entity_count": len(universal), "missing_by_source": missing_by_source}

    def test_prompt_contains_event_title(self):
        qd = self._make_quote_distribution(["The Hindu", "ToI"])
        mc = self._make_missing_context(["The Hindu", "ToI"])
        prompt = self.build_prompt("Budget 2025 Coverage", qd, mc)
        self.assertIn("Budget 2025 Coverage", prompt)

    def test_prompt_contains_source_names(self):
        qd = self._make_quote_distribution(["The Hindu", "ToI"])
        mc = self._make_missing_context(["The Hindu", "ToI"])
        prompt = self.build_prompt("Test Event", qd, mc)
        self.assertIn("The Hindu", prompt)
        self.assertIn("ToI", prompt)

    def test_prompt_contains_instructions(self):
        qd = self._make_quote_distribution(["Source A"])
        mc = self._make_missing_context(["Source A"])
        prompt = self.build_prompt("Test", qd, mc)
        self.assertIn("neutral", prompt.lower())
        self.assertIn("bias", prompt.lower())  # The rule "do NOT use the word bias"

    def test_prompt_with_quotes_shows_counts(self):
        qd = self._make_quote_distribution(
            ["The Hindu", "ToI"],
            {"The Hindu": {"government": 3, "opposition": 1}, "ToI": {"expert": 5}}
        )
        mc = self._make_missing_context(["The Hindu", "ToI"])
        prompt = self.build_prompt("Test Event", qd, mc)
        self.assertIn("The Hindu", prompt)
        self.assertIn("3", prompt)  # government count

    def test_prompt_missing_context_filters_single_source_entities(self):
        """Entities mentioned by only 1 source should NOT appear in the missing context section."""
        qd = self._make_quote_distribution(["Source A", "Source B"])
        # Only Source A mentions "UniqueEntity" — should be filtered
        mc = self._make_missing_context(
            ["Source A", "Source B"],
            {"Source A": {"UniqueEntity", "SharedEntity"}, "Source B": {"SharedEntity"}}
        )
        prompt = self.build_prompt("Test", qd, mc)
        # "UniqueEntity" is only in Source A, so it won't appear as notable missing
        # "SharedEntity" is in both — neither is missing from both — no missing context note
        self.assertNotIn("UniqueEntity", prompt.split("MISSING CONTEXT")[1] if "MISSING CONTEXT" in prompt else prompt)

    def test_prompt_empty_quote_distribution(self):
        """Prompt should gracefully handle events with no quotes."""
        qd = {"sources_analyzed": [], "total_quotes": 0, "by_source": {}}
        mc = {"sources_analyzed": [], "universal_entity_count": 0, "missing_by_source": {}}
        prompt = self.build_prompt("Empty Event", qd, mc)
        self.assertIn("Empty Event", prompt)
        self.assertIn("No quote data", prompt)

    def test_prompt_returns_string(self):
        qd = self._make_quote_distribution(["A", "B"])
        mc = self._make_missing_context(["A", "B"])
        result = self.build_prompt("Event", qd, mc)
        self.assertIsInstance(result, str)
        self.assertGreater(len(result), 100)


class TestExplainEvent(unittest.TestCase):
    """Tests for explain_event.explain_event() with mocked LLM and DB calls."""

    def _make_conn(self, explanation_text=None, event_title="Test Event"):
        """Create a mock psycopg connection."""
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value.__enter__.return_value = cursor

        # Mock title fetch
        cursor.fetchone.side_effect = [
            (event_title,),  # _get_event_title
            None,            # get_event_explanation (no existing)
        ]
        return conn, cursor

    @patch("neutral_news.explain.explain_event.get_event_explanation", return_value=None)
    @patch("neutral_news.explain.explain_event.get_event_analysis")
    @patch("neutral_news.explain.explain_event.generate_explanation", return_value="Mocked explanation text.")
    @patch("neutral_news.explain.explain_event.upsert_event_explanation")
    def test_explain_event_generates_and_persists(
        self, mock_upsert, mock_generate, mock_analysis, mock_get_expl
    ):
        """explain_event() should call the LLM and upsert the result."""
        from neutral_news.explain.explain_event import explain_event

        # Provide enough analysis data for 2+ sources
        mock_analysis.return_value = {
            "quote_distribution": {
                "sources_analyzed": ["The Hindu", "ToI"],
                "total_quotes": 5,
                "by_source": {
                    "The Hindu": {"total_quotes": 3, "counts": {"government": 3}, "proportions": {"government": 1.0}, "dominant_role": "government", "omitted_roles": [], "quotes": []},
                    "ToI": {"total_quotes": 2, "counts": {"expert": 2}, "proportions": {"expert": 1.0}, "dominant_role": "expert", "omitted_roles": [], "quotes": []},
                }
            },
            "missing_context": {
                "sources_analyzed": ["The Hindu", "ToI"],
                "universal_entity_count": 2,
                "missing_by_source": {
                    "The Hindu": {"present_count": 1, "missing_count": 1, "missing_entities": ["Entity B"], "present_entities": ["Entity A"]},
                    "ToI": {"present_count": 1, "missing_count": 1, "missing_entities": ["Entity A"], "present_entities": ["Entity B"]},
                }
            }
        }

        conn = MagicMock()
        conn.cursor.return_value.__enter__.return_value.fetchone.return_value = ("Test Event",)

        result = explain_event("test-uuid", conn=conn)

        self.assertEqual(result, "Mocked explanation text.")
        mock_generate.assert_called_once()
        mock_upsert.assert_called_once()

    @patch("neutral_news.explain.explain_event.get_event_explanation", return_value="Existing explanation.")
    def test_explain_event_skips_if_exists(self, mock_get_expl):
        """explain_event() should return existing explanation and skip LLM call."""
        from neutral_news.explain.explain_event import explain_event

        conn = MagicMock()
        result = explain_event("test-uuid", conn=conn, force=False)

        self.assertEqual(result, "Existing explanation.")

    @patch("neutral_news.explain.explain_event.get_event_explanation", return_value="Existing explanation.")
    @patch("neutral_news.explain.explain_event.get_event_analysis")
    @patch("neutral_news.explain.explain_event.generate_explanation", return_value="New explanation.")
    @patch("neutral_news.explain.explain_event.upsert_event_explanation")
    def test_explain_event_force_regenerates(self, mock_upsert, mock_generate, mock_analysis, mock_get_expl):
        """explain_event(force=True) should regenerate even when explanation exists."""
        from neutral_news.explain.explain_event import explain_event

        mock_analysis.return_value = {
            "quote_distribution": {
                "sources_analyzed": ["A", "B"],
                "total_quotes": 2,
                "by_source": {
                    "A": {"total_quotes": 1, "counts": {}, "proportions": {}, "dominant_role": None, "omitted_roles": [], "quotes": []},
                    "B": {"total_quotes": 1, "counts": {}, "proportions": {}, "dominant_role": None, "omitted_roles": [], "quotes": []},
                }
            },
            "missing_context": {"sources_analyzed": ["A", "B"], "universal_entity_count": 0, "missing_by_source": {}}
        }

        conn = MagicMock()
        conn.cursor.return_value.__enter__.return_value.fetchone.return_value = ("Test Event",)

        result = explain_event("test-uuid", conn=conn, force=True)

        self.assertEqual(result, "New explanation.")
        mock_generate.assert_called_once()

    @patch("neutral_news.explain.explain_event.get_event_explanation", return_value=None)
    @patch("neutral_news.explain.explain_event.get_event_analysis")
    def test_explain_event_skips_single_source(self, mock_analysis, mock_get_expl):
        """explain_event() should skip events with fewer than 2 sources."""
        from neutral_news.explain.explain_event import explain_event

        mock_analysis.return_value = {
            "quote_distribution": {
                "sources_analyzed": ["The Hindu"],  # only 1 source
                "total_quotes": 1,
                "by_source": {"The Hindu": {"total_quotes": 1, "counts": {}, "proportions": {}, "dominant_role": None, "omitted_roles": [], "quotes": []}}
            },
            "missing_context": {"sources_analyzed": ["The Hindu"], "universal_entity_count": 0, "missing_by_source": {}}
        }

        conn = MagicMock()
        conn.cursor.return_value.__enter__.return_value.fetchone.return_value = ("Test Event",)

        result = explain_event("test-uuid", conn=conn)
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
