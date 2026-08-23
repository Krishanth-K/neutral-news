"""
Article CRUD operations.

All database reads and writes for the articles and article_embeddings tables.
"""

import logging

import psycopg
from psycopg.errors import UniqueViolation

from neutral_news.config import DATABASE_URL

log = logging.getLogger(__name__)


def insert_article(article: dict, conn=None, db_url: str = DATABASE_URL) -> None:
    """Insert a single RSS article record into the articles table.

    Ignores duplicates based on article_url.
    """
    published_at = article.get("published_at") if article.get("published_at") else None

    query = """
        INSERT INTO articles (source_name, article_url, headline, published_at)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (article_url) DO NOTHING;
    """
    params = (
        article["source_name"],
        article["article_url"],
        article["headline"],
        published_at,
    )

    if conn:
        with conn.cursor() as cur:
            cur.execute(query, params)
    else:
        with psycopg.connect(db_url) as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)


def get_pending_articles(limit: int = 50, conn=None, db_url: str = DATABASE_URL) -> list:
    """Fetch up to `limit` pending articles from the database."""
    query = """
        SELECT id, article_url
        FROM articles
        WHERE scrape_status = 'pending'
        LIMIT %s;
    """
    if conn:
        with conn.cursor() as cur:
            cur.execute(query, (limit,))
            return cur.fetchall()
    else:
        with psycopg.connect(db_url) as conn:
            with conn.cursor() as cur:
                cur.execute(query, (limit,))
                return cur.fetchall()


def update_article_text(
    article_id,
    full_text=None,
    error=None,
    status: str = "completed",
    conn=None,
    db_url: str = DATABASE_URL,
) -> None:
    """Update an article with scraped text or an error message, and advance its status.

    If the scraped full_text is a duplicate of an already-stored article, the
    update is silently skipped and the article is marked as failed so the
    pipeline does not re-process it endlessly.
    """
    query = """
        UPDATE articles
        SET full_text = %s,
            scrape_error = %s,
            scrape_status = %s,
            scraped_at = NOW(),
            scrape_attempts = scrape_attempts + 1,
            updated_at = NOW()
        WHERE id = %s;
    """
    params = (full_text, error, status, article_id)

    def _execute(cur):
        try:
            cur.execute(query, params)
        except UniqueViolation:
            log.warning(
                "Duplicate full_text detected for article %s — marking as failed.",
                article_id,
            )
            cur.execute(
                """
                UPDATE articles
                SET scrape_status = 'failed',
                    scrape_error = 'duplicate_full_text',
                    scrape_attempts = scrape_attempts + 1,
                    updated_at = NOW()
                WHERE id = %s;
                """,
                (article_id,),
            )

    if conn:
        with conn.cursor() as cur:
            _execute(cur)
    else:
        with psycopg.connect(db_url) as conn:
            with conn.cursor() as cur:
                _execute(cur)
            conn.commit()


def view_articles(limit: int = 10, db_url: str = DATABASE_URL) -> None:
    """Fetch and print recent article records from the database."""
    query = """
        SELECT source_name, headline, published_at, created_at, scrape_status
        FROM articles
        ORDER BY created_at DESC
        LIMIT %s;
    """
    with psycopg.connect(db_url) as conn:
        with conn.cursor() as cur:
            cur.execute(query, (limit,))
            rows = cur.fetchall()

    print(f"\n--- Recent {len(rows)} Articles in Database ---")
    for i, (source, headline, pub_at, created, status) in enumerate(rows, 1):
        print(f"{i}. [{source}] [{status}] {headline}")
        print(f"   Published: {pub_at} | Staged: {created}\n")

