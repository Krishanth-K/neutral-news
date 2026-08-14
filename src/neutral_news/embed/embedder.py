"""
Article embedding generation and storage.

Uses sentence-transformers (all-MiniLM-L6-v2, 384-dim) to generate embeddings
and stores them in the article_embeddings table via pgvector.
"""

from __future__ import annotations

import psycopg
from sentence_transformers import SentenceTransformer

from neutral_news.config import DATABASE_URL

# Matches the vector(384) column in article_embeddings
_MODEL_NAME = "all-MiniLM-L6-v2"
# _MODEL_NAME = "nomic-ai/nomic-embed-text-v1.5"
_model: SentenceTransformer | None = None


def _get_model() -> SentenceTransformer:
    """Lazy-load the embedding model (downloaded once, cached in memory)."""
    global _model
    if _model is None:
        print(f"[EMBED] Loading model '{_MODEL_NAME}'...")
        _model = SentenceTransformer(_MODEL_NAME)
    return _model


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
    vector = model.encode(text).tolist()

    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO article_embeddings (article_id, embedding)
            VALUES (%s, %s)
            ON CONFLICT DO NOTHING;
            """,
            (article_id, vector),
        )


def embed_pending_articles(conn, batch_size: int = 50) -> None:
    """Embed all completed articles that are missing embeddings, in batches."""
    total = 0
    while True:
        rows = get_articles_needing_embeddings(conn, limit=batch_size)
        if not rows:
            break

        print(f"[EMBED] Embedding batch of {len(rows)} articles...")
        for article_id, text in rows:
            try:
                embed_article(article_id, text, conn)
                print(f"  ✓ Embedded article {article_id}")
            except Exception as e:
                print(f"  ✗ Failed to embed article {article_id}: {e}")
            total += 1

        conn.commit()

    print(f"[EMBED] Done. Embedded {total} articles.")
