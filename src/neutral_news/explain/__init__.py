"""LLM Explainability layer for Media Lens (Phase 6).

Takes pre-computed analysis evidence (quote distributions, missing context)
and generates a human-readable, neutral narrative via Gemini Flash.

The LLM narrates facts — it does NOT analyse or score bias.
"""

from neutral_news.explain.explain_event import explain_event

__all__ = ["explain_event"]
