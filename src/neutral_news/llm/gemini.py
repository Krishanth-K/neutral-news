"""
Gemini API client.

Thin wrapper around google-genai for making structured LLM calls.
Install: pip install google-genai

Used by:
  - extract/quotes.py  (quote extraction)
  - explain/           (Phase 6 explanation layer)
"""

import json

import google.genai as genai
from google.genai import types as genai_types

from neutral_news.config import GEMINI_API_KEY
from neutral_news.extract.constants import ROLE_LABELS

_client = None


def _get_client() -> genai.Client:
    """Lazy-init the Gemini client (created once, reused across calls)."""
    global _client
    if _client is None:
        _client = genai.Client(api_key=GEMINI_API_KEY)
    return _client


def extract_quotes(article_text: str) -> list[dict]:
    """Call Gemini Flash to extract quotes from a news article.

    Returns a list of dicts: [{"quote_text": ..., "speaker": ..., "role": ...}]

    Roles are exactly one of:
         other
    Returns an empty list if the article has no quotes or parsing fails.
    """
    prompt = f"""Extract all direct and indirect quotes from the news article below.
For each quote, identify the speaker's name and their role.

Role must be exactly one of: {ROLE_LABELS}, other

Return ONLY a JSON array. No explanation, no markdown, no code fences.
Example: [{{"quote_text": "We will act soon", "speaker": "Amit Shah", "role": "government"}}]

Article:
{article_text}"""

    client = _get_client()
    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt,
    )

    raw = response.text.strip()

    # Strip markdown code fences if the model adds them anyway
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()

    try:
        quotes = json.loads(raw)
        if not isinstance(quotes, list):
            return []
        return quotes
    except json.JSONDecodeError:
        return []


def generate_explanation(prompt: str) -> str:
    """Call Gemini Flash to generate a neutral, factual narrative from analysis evidence.

    Used by the Phase 6 explainability layer. The prompt is pre-built by
    explain/prompt.py and contains only structured, pre-computed facts —
    the model is instructed to narrate, not analyse.

    Args:
        prompt: The full structured prompt from explain/prompt.py.

    Returns:
        The generated explanation text (stripped). Returns an empty string
        if the API call fails or returns nothing.

    Raises:
        Exception: Propagates API errors so the caller can handle retries/logging.
    """
    client = _get_client()

    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt,
        config=genai_types.GenerateContentConfig(
            temperature=0.3,
            max_output_tokens=500,
        ),
    )

    return (response.text or "").strip()
