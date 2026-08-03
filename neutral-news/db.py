import os
import psycopg

DATABASE_URL = os.getenv(
    "DATABASE_URL", "postgresql://postgres:postgres@localhost:5433/neutral_news"
)

SCHEMA_SQL = """
-- Enable required extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS vector;

-- Scrape status enum
DO $$ 
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'scrape_status_enum') THEN
        CREATE TYPE scrape_status_enum AS ENUM ('pending', 'processing', 'completed', 'failed');
    END IF;
END $$;

-- 1. Articles Table (Staged RSS ingest + scraped full text)
CREATE TABLE IF NOT EXISTS articles (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_name VARCHAR(100) NOT NULL,
    article_url TEXT UNIQUE NOT NULL,
    headline TEXT NOT NULL,
    published_at TIMESTAMPTZ,
    
    -- Scraped content
    full_text TEXT,
    authors TEXT[],
    scraped_at TIMESTAMPTZ,
    
    -- Queue & status management
    scrape_status scrape_status_enum NOT NULL DEFAULT 'pending',
    scrape_attempts INT NOT NULL DEFAULT 0,
    scrape_error TEXT,
    
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_articles_scrape_status ON articles(scrape_status);
CREATE INDEX IF NOT EXISTS idx_articles_source_pub ON articles(source_name, published_at DESC);

-- 2. Embeddings Table
CREATE TABLE IF NOT EXISTS article_embeddings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    article_id UUID NOT NULL REFERENCES articles(id) ON DELETE CASCADE,
    embedding vector(384),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_embeddings_article_id ON article_embeddings(article_id);

-- 3. Extracted Quotes Table
CREATE TABLE IF NOT EXISTS quotes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    article_id UUID NOT NULL REFERENCES articles(id) ON DELETE CASCADE,
    quote_text TEXT NOT NULL,
    speaker VARCHAR(255),
    role VARCHAR(100),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_quotes_article_id ON quotes(article_id);

-- 4. Events Table
CREATE TABLE IF NOT EXISTS events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 5. Event Articles Mapping Table
CREATE TABLE IF NOT EXISTS event_articles (
    event_id UUID NOT NULL REFERENCES events(id) ON DELETE CASCADE,
    article_id UUID NOT NULL REFERENCES articles(id) ON DELETE CASCADE,
    PRIMARY KEY (event_id, article_id)
);

-- 6. Event Explanations Table
CREATE TABLE IF NOT EXISTS event_explanations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_id UUID NOT NULL REFERENCES events(id) ON DELETE CASCADE,
    explanation_text TEXT NOT NULL,
    evidence JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
"""


def init_db(db_url: str = DATABASE_URL):
    """Initializes PostgreSQL extensions, tables, and indexes, creating the database if needed."""
    # Parse target database name from URL if possible
    # Connect to default postgres DB first to create neutral_news DB if it doesn't exist
    from psycopg.conninfo import conninfo_to_dict, make_conninfo

    try:
        conn_params = conninfo_to_dict(db_url)
        target_db = conn_params.get("dbname", "neutral_news")

        # Connect to maintenance database 'postgres'
        conn_params["dbname"] = "postgres"
        admin_url = make_conninfo(**conn_params)

        with psycopg.connect(admin_url, autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1 FROM pg_database WHERE datname = %s;", (target_db,))
                if not cur.fetchone():
                    cur.execute(f'CREATE DATABASE "{target_db}";')
                    print(f"Created database '{target_db}'.")
    except Exception as e:
        print(f"[WARN] Database creation check skipped/failed: {e}")

    with psycopg.connect(db_url, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(SCHEMA_SQL)
            print("PostgreSQL database initialized successfully with all tables and extensions.")


def insert_article(article: dict, conn=None, db_url: str = DATABASE_URL):
    """
    Inserts a single RSS article record into the articles table.
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


def view_articles(limit: int = 10, db_url: str = DATABASE_URL):
    """Fetches and prints recent article records from the database."""
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


def get_pending_articles(limit: int = 50, conn=None, db_url: str = DATABASE_URL):
    """Fetches up to `limit` pending articles from the database."""
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


def update_article_text(article_id, full_text=None, error=None, status='completed', conn=None, db_url: str = DATABASE_URL):
    """Updates an article with scraped text or error, and updates its status."""
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
    if conn:
        with conn.cursor() as cur:
            cur.execute(query, params)
    else:
        with psycopg.connect(db_url) as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)
                conn.commit()


if __name__ == "__main__":
    init_db()
