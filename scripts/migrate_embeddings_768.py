"""
Migration: resize embedding column from vector(384) → vector(768).

Drops all existing embeddings (incompatible dimensions) and recreates the
column for nomic-ai/nomic-embed-text-v1.5 (768-dim, 8192-token context).

Run once:
    PYTHONPATH=src python3 scripts/migrate_embeddings_768.py
Then re-embed:
    make embed
"""

import psycopg

from neutral_news.config import DATABASE_URL


def migrate(db_url: str = DATABASE_URL) -> None:
    print("[MIGRATE] Connecting to database...")
    with psycopg.connect(db_url, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM article_embeddings;")
            (count,) = cur.fetchone()
            print(f"[MIGRATE] Dropping {count} existing embeddings (vector(384))...")

            cur.execute("TRUNCATE TABLE article_embeddings;")
            cur.execute("ALTER TABLE article_embeddings DROP COLUMN embedding;")
            cur.execute(
                "ALTER TABLE article_embeddings ADD COLUMN embedding vector(768);"
            )
            print("[MIGRATE] Column recreated as vector(768).")

            # Recreate the IVFFlat index for the new dimension if it existed
            cur.execute(
                """
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM pg_indexes
                        WHERE tablename = 'article_embeddings'
                          AND indexname = 'idx_embeddings_embedding'
                    ) THEN
                        -- Index will be created after embeddings are populated
                        NULL;
                    END IF;
                END $$;
                """
            )

    print("[MIGRATE] Done. Run `make embed` to re-generate embeddings.")


if __name__ == "__main__":
    migrate()
