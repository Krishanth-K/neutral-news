"""
Article embedding generation and storage.

Uses sentence-transformers (nomic-ai/nomic-embed-text-v1.5, 768-dim, 8192-token context)
to generate embeddings and stores them in the article_embeddings table via pgvector.
"""

from __future__ import annotations

import argparse
import psycopg
from pgvector.psycopg import register_vector
from sentence_transformers import SentenceTransformer

from neutral_news.config import DATABASE_URL

# Matches the vector(768) column in article_embeddings
_MODEL_NAME = "nomic-ai/nomic-embed-text-v1.5"
_EMBEDDING_DIM = 768
_model: SentenceTransformer | None = None


def _get_model() -> SentenceTransformer:
    """Lazy-load the embedding model (downloaded once, cached in memory)."""
    global _model
    if _model is None:
        print(f"[EMBED] Loading model '{_MODEL_NAME}'...")
        _model = SentenceTransformer(_MODEL_NAME, trust_remote_code=True)
    return _model


def _set_status(article_id: str, status: str, conn) -> None:
    """Update embedding_status for an article."""
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE articles
            SET embedding_status = %s,
                updated_at = NOW()
            WHERE id = %s;
            """,
            (status, article_id),
        )


def get_articles_needing_embeddings(
    conn, limit: int = 50
) -> list[tuple[str, str]]:
    """Return completed articles that do not yet have an embedding.

    Returns:
        List of (article_id, full_text) tuples.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT a.id, a.full_text
            FROM articles a
            LEFT JOIN article_embeddings e ON e.article_id = a.id
            WHERE a.scrape_status = 'completed'
              AND a.full_text IS NOT NULL
              AND e.id IS NULL
            LIMIT %s;
            """,
            (limit,),
        )
        return cur.fetchall()


def embed_article(article_id: str, text: str, conn) -> None:
    """Generate and store an embedding for a single article.

    Skips silently if an embedding already exists (ON CONFLICT DO NOTHING).
    """
    model = _get_model()
    vector = model.encode("search_document: " + text).tolist()

    with conn.cursor() as cur:
        register_vector(conn)
        cur.execute(
            """
            INSERT INTO article_embeddings (article_id, embedding)
            VALUES (%s, %s)
            ON CONFLICT DO NOTHING;
            """,
            (article_id, vector),
        )
    _set_status(article_id, "completed", conn)


def clear_embeddings(conn=None, db_url: str = DATABASE_URL) -> int:
    """Clear all embeddings from article_embeddings table and reset embedding_status on articles.

    Returns:
        Number of cleared embeddings.
    """
    def _execute(connection) -> int:
        with connection.cursor() as cur:
            # Ensure column exists if migration hasn't run yet
            cur.execute("ALTER TABLE articles ADD COLUMN IF NOT EXISTS embedding_status TEXT;")
            cur.execute("SELECT COUNT(*) FROM article_embeddings;")
            count = cur.fetchone()[0]
            cur.execute("DELETE FROM article_embeddings;")
            cur.execute(
                """
                UPDATE articles
                SET embedding_status = NULL,
                    updated_at = NOW();
                """
            )
            print(f"[EMBED] Cleared {count} records from article_embeddings and reset embedding status on all articles.")
            return count

    if conn:
        return _execute(conn)
    with psycopg.connect(db_url) as connection:
        count = _execute(connection)
        connection.commit()
        return count


def embed_pending_articles(
    conn, limit: int | None = None, batch_size: int = 50
) -> None:
    """Embed completed articles that are missing embeddings, in batches."""
    total = 0
    while True:
        fetch_limit = (
            min(batch_size, limit - total) if limit is not None else batch_size
        )
        if fetch_limit <= 0:
            break

        rows = get_articles_needing_embeddings(conn, limit=fetch_limit)
        if not rows:
            break

        print(f"[EMBED] Embedding batch of {len(rows)} articles...")
        for article_id, text in rows:
            try:
                embed_article(article_id, text, conn)
                print(f"  ✓ Embedded article {article_id}")
            except Exception as e:
                print(f"  ✗ Failed to embed article {article_id}: {e}")
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

    print(f"[EMBED] Done. Embedded {total} articles.")


def main():
    parser = argparse.ArgumentParser(description="Generate embeddings or clear embedding table.")
    parser.add_argument("--clear", action="store_true", help="Clear embedding table and reset embedding status on all articles")
    parser.add_argument("--limit", type=int, default=None, help="Limit number of articles to embed")
    args = parser.parse_args()

    with psycopg.connect(DATABASE_URL) as conn:
        if args.clear:
            clear_embeddings(conn)
            conn.commit()
        else:
            embed_pending_articles(conn, limit=args.limit)


if __name__ == "__main__":
    main()

