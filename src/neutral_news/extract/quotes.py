"""
LLM-based quote extraction from article full text.

For each completed article, calls Gemini Flash to extract structured quotes
(quote_text, speaker, role) and stores them in the quotes table.

Mirrors the structure of extract/entities.py — same batching, status tracking,
and error handling patterns.
"""

from __future__ import annotations

from neutral_news.db.articles import (
    get_articles_needing_quote_extraction,
    insert_quote,
)
from neutral_news.extract.constants import ROLE_LABELS
from neutral_news.llm.gemini import extract_quotes

VALID_ROLES = set(ROLE_LABELS) | {"other"}


def extract_quotes_from_text(text: str) -> list[dict]:
    """Extract quotes from raw article text via the LLM.

    Returns a list of dicts: [{"quote_text": ..., "speaker": ..., "role": ...}]
    Any quote whose role is not a known label is coerced to "other".
    Returns an empty list if the article has no quotes or the LLM call fails.
    """
    if not text or not text.strip():
        return []

    raw_quotes = extract_quotes(text)

    validated = []
    for q in raw_quotes:
        if not isinstance(q, dict):
            continue
        quote_text = q.get("quote_text", "").strip()
        if not quote_text:
            continue
        speaker = q.get("speaker", "").strip() or None
        role = q.get("role", "").strip().lower()
        if role not in VALID_ROLES:
            role = "other"
        validated.append({"quote_text": quote_text, "speaker": speaker, "role": role})

    return validated


def _set_status(article_id: str, status: str, conn) -> None:
    """Update quote_extraction_status for an article."""
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE articles
            SET quote_extraction_status = %s,
                updated_at = NOW()
            WHERE id = %s;
            """,
            (status, article_id),
        )


def extract_article_quotes(article_id: str, text: str, conn) -> list[dict]:
    """Extract quotes for a single article, save to DB, and mark completed.

    Returns the list of validated quotes (may be empty for quote-free articles).
    Sets status to 'failed' on any exception so the row is not retried.
    """
    quotes = extract_quotes_from_text(text)

    for q in quotes:
        insert_quote(
            article_id=article_id,
            quote_text=q["quote_text"],
            speaker=q["speaker"],
            role=q["role"],
            conn=conn,
        )

    _set_status(article_id, "completed", conn)
    return quotes


def extract_quotes_pipeline(
    conn, limit: int | None = None, batch_size: int = 25
) -> None:
    """Extract and store quotes for completed articles in batches.

    Batch size defaults to 25 (smaller than entity extraction's 50) because
    each article requires an LLM call — rate limits matter here.
    """
    total = 0
    while True:
        fetch_limit = (
            min(batch_size, limit - total) if limit is not None else batch_size
        )
        if fetch_limit <= 0:
            break

        rows = get_articles_needing_quote_extraction(conn, limit=fetch_limit)
        if not rows:
            break

        print(f"[QUOTES] Processing batch of {len(rows)} articles...")
        for article_id, text in rows:
            try:
                extracted = extract_article_quotes(article_id, text, conn)
                print(
                    f"  ✓ Extracted {len(extracted)} quotes for article {article_id}"
                )
            except Exception as e:
                print(f"  ✗ Failed for article {article_id}: {e}")
                conn.rollback()
                try:
                    _set_status(article_id, "failed", conn)
                    conn.commit()
                except Exception:
                    pass
            total += 1

        conn.commit()
        if limit is not None and total >= limit:
            break

    print(f"[QUOTES] Done. Processed {total} articles.")
