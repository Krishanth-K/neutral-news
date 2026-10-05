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

from neutral_news.config import GEMINI_API_KEY_POOL
from neutral_news.extract.constants import ROLE_LABELS

from google.genai import errors

class KeyPool:
    def __init__(self, keys: list[str]):
        self._keys = keys
        self._index = 0
        self._consecutive_failures = 0
        self._client = self._make_client()

    def _make_client(self) -> genai.Client:
        return genai.Client(api_key=self._keys[self._index])

    def get_client(self) -> genai.Client:
        return self._client

    def rotate(self):
        self._consecutive_failures += 1

        if self._consecutive_failures >= len(self._keys):
            raise RuntimeError("All Gemini API keys are exhausted.")

        self._index = (self._index + 1) % len(self._keys)
        self._client = self._make_client()  # always creates fresh

    def reset_failures(self):
        self._consecutive_failures = 0


_pool = KeyPool(GEMINI_API_KEY_POOL)  # one module-level instance, not bare globals


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

    try:
        client = _pool.get_client()
        response = client.models.generate_content(
            model="gemini-3.8-flash",
            contents=prompt,
        )
        raw = response.text.strip()
        _pool.reset_failures()

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

    except errors.APIError as e:
        print(f"API returned error code {e.code}")

        if e.code == 429:
            print("rotating api key")

            _pool.rotate()
            return extract_quotes(article_text)  # retry with next key
        raise  # re-raise non-429 errors (403, 500, etc.)

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

    try:
        client = _pool.get_client()

        response = client.models.generate_content(
            model="gemini-3.8-flash",
            contents=prompt,
            config=genai_types.GenerateContentConfig(
                temperature=0.3,
                max_output_tokens=500,
            ),
        )

        _pool.reset_failures()
        return (response.text or "").strip()

    except errors.APIError as e:
        print(f"API returned error code {e.code}")

        if e.code == 429:
            print("rotating api key")

            _pool.rotate()
            return generate_explanation(prompt)  # retry with next key
        raise  # re-raise non-429 errors (403, 500, etc.)
