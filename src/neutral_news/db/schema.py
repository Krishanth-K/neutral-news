"""
Database schema definition and initialisation.

Manages PostgreSQL extensions, enums, tables, and indexes for neutral_news.
Run directly (`python -m neutral_news.db.schema`) to initialise the database.
"""

import psycopg
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from neutral_news.config import DATABASE_URL

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
    
    -- entity extraction
    entity_extraction_status TEXT,
    
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_articles_scrape_status ON articles(scrape_status);
CREATE INDEX IF NOT EXISTS idx_articles_source_pub ON articles(source_name, published_at DESC);
CREATE UNIQUE INDEX IF NOT EXISTS idx_articles_full_text_hash ON articles(md5(full_text)) WHERE full_text IS NOT NULL;

-- 2. Embeddings Table
CREATE TABLE IF NOT EXISTS article_embeddings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    article_id UUID NOT NULL REFERENCES articles(id) ON DELETE CASCADE,
    embedding vector(768),
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

-- 4. Extracted Entities Table
CREATE TABLE IF NOT EXISTS entities (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    article_id UUID NOT NULL REFERENCES articles(id) ON DELETE CASCADE,
    text TEXT NOT NULL,
    label VARCHAR(255),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_entities_article_id ON entities(article_id);

-- 5. Events Table
CREATE TABLE IF NOT EXISTS events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 6. Event Articles Mapping Table
CREATE TABLE IF NOT EXISTS event_articles (
    event_id UUID NOT NULL REFERENCES events(id) ON DELETE CASCADE,
    article_id UUID NOT NULL REFERENCES articles(id) ON DELETE CASCADE,
    PRIMARY KEY (event_id, article_id)
);

-- 7. Event Explanations Table
CREATE TABLE IF NOT EXISTS event_explanations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_id UUID NOT NULL REFERENCES events(id) ON DELETE CASCADE,
    explanation_text TEXT NOT NULL,
    evidence JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
"""


def init_db(db_url: str = DATABASE_URL) -> None:
    """Initialise PostgreSQL extensions, tables, and indexes.

    Connects to the maintenance database first to create the target database
    if it does not already exist, then applies the full schema.
    """
    try:
        conn_params = conninfo_to_dict(db_url)
        target_db = conn_params.get("dbname", "neutral_news")

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
            print("PostgreSQL database initialised successfully with all tables and extensions.")


if __name__ == "__main__":
    init_db()
