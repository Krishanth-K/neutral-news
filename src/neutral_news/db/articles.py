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

def insert_entity(
    article_id: str,
    entity_text: str,
    entity_label: str,
    conn=None,
    db_url: str = DATABASE_URL,
) -> None:
    """Insert a single extracted entity into the entities table."""
    query = """
        INSERT INTO entities (article_id, text, label)
        VALUES (%s, %s, %s);
    """
    params = (
        article_id,
        entity_text,
        entity_label,
    )

    if conn:
        with conn.cursor() as cur:
            cur.execute(query, params)
    else:
        with psycopg.connect(db_url) as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)


def insert_quote(
    article_id: str,
    quote_text: str,
    speaker: str | None,
    role: str | None,
    conn=None,
    db_url: str = DATABASE_URL,
) -> None:
    """Insert a single extracted quote into the quotes table."""
    query = """
        INSERT INTO quotes (article_id, quote_text, speaker, role)
        VALUES (%s, %s, %s, %s);
    """
    params = (article_id, quote_text, speaker, role)

    if conn:
        with conn.cursor() as cur:
            cur.execute(query, params)
    else:
        with psycopg.connect(db_url) as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)


def insert_event(
    medoid_id: str,
    title: str | None = None,
    conn=None,
    db_url: str = DATABASE_URL,
) -> str:
    """Create a new event record in the events table and return its ID.

    If title is not provided, uses the headline of the medoid article.
    """
    def _execute(connection) -> str:
        with connection.cursor() as cur:
            if title:
                cur.execute(
                    """
                    INSERT INTO events (title)
                    VALUES (%s)
                    RETURNING id;
                    """,
                    (title,),
                )
            else:
                cur.execute(
                    """
                    INSERT INTO events (title)
                    SELECT headline FROM articles WHERE id = %s
                    RETURNING id;
                    """,
                    (medoid_id,),
                )
            row = cur.fetchone()
            if not row:
                raise ValueError(f"Could not create event for medoid article ID: {medoid_id}")
            return str(row[0])

    if conn:
        return _execute(conn)
    with psycopg.connect(db_url) as connection:
        event_id = _execute(connection)
        connection.commit()
        return event_id


def link_event_articles(
    event_id: str,
    article_ids: list[str],
    conn=None,
    db_url: str = DATABASE_URL,
) -> None:
    """Insert mappings between an event and its member articles."""
    if not article_ids:
        return

    query = """
        INSERT INTO event_articles (event_id, article_id)
        VALUES (%s, %s)
        ON CONFLICT (event_id, article_id) DO NOTHING;
    """
    records = [(event_id, art_id) for art_id in article_ids]

    def _execute(connection):
        with connection.cursor() as cur:
            cur.executemany(query, records)

    if conn:
        _execute(conn)
    else:
        with psycopg.connect(db_url) as connection:
            _execute(connection)
            connection.commit()


def save_event_cluster(
    medoid_id: str,
    article_ids: list[str],
    title: str | None = None,
    conn=None,
    db_url: str = DATABASE_URL,
) -> str:
    """Create an event and map all member articles to it in a single transaction."""
    def _execute(connection) -> str:
        with connection.cursor() as cur:
            if title:
                cur.execute(
                    "INSERT INTO events (title) VALUES (%s) RETURNING id;",
                    (title,),
                )
            else:
                cur.execute(
                    "INSERT INTO events (title) SELECT headline FROM articles WHERE id = %s RETURNING id;",
                    (medoid_id,),
                )
            row = cur.fetchone()
            if not row:
                raise ValueError(f"Medoid article {medoid_id} not found.")
            event_id = str(row[0])

            records = [(event_id, art_id) for art_id in article_ids]
            cur.executemany(
                """
                INSERT INTO event_articles (event_id, article_id)
                VALUES (%s, %s)
                ON CONFLICT (event_id, article_id) DO NOTHING;
                """,
                records,
            )
            return event_id

    if conn:
        return _execute(conn)
    with psycopg.connect(db_url) as connection:
        with connection.transaction():
            return _execute(connection)


def save_event_clusters(
    clusters: dict[int, dict],
    conn=None,
    db_url: str = DATABASE_URL,
) -> list[str]:
    """Persist all clusters from HAC output to events and event_articles tables.

    clusters: {cluster_id: {"medoid_id": str, "article_ids": list[str], ...}}
    Returns list of created event IDs.
    """
    event_ids = []

    def _execute(connection) -> list[str]:
        created = []
        for cluster_data in clusters.values():
            medoid_id = cluster_data["medoid_id"]
            article_ids = cluster_data["article_ids"]
            event_id = save_event_cluster(medoid_id=medoid_id, article_ids=article_ids, conn=connection)
            created.append(event_id)
        return created

    if conn:
        return _execute(conn)
    with psycopg.connect(db_url) as connection:
        with connection.transaction():
            return _execute(connection)


def get_event_by_article_id(
    article_id: str,
    conn=None,
    db_url: str = DATABASE_URL,
) -> dict | None:
    """Fetch the event associated with a given article ID."""
    query = """
        SELECT e.id, e.title, e.created_at, e.updated_at
        FROM events e
        JOIN event_articles ea ON ea.event_id = e.id
        WHERE ea.article_id = %s;
    """
    def _execute(connection):
        with connection.cursor() as cur:
            cur.execute(query, (article_id,))
            row = cur.fetchone()
            if not row:
                return None
            return {
                "id": str(row[0]),
                "title": row[1],
                "created_at": row[2],
                "updated_at": row[3],
            }

    if conn:
        return _execute(conn)
    with psycopg.connect(db_url) as connection:
        return _execute(connection)


def get_articles_for_event(
    event_id: str,
    conn=None,
    db_url: str = DATABASE_URL,
) -> list[dict]:
    """Fetch all articles associated with an event."""
    query = """
        SELECT a.id, a.source_name, a.headline, a.article_url, a.published_at, a.full_text
        FROM articles a
        JOIN event_articles ea ON ea.article_id = a.id
        WHERE ea.event_id = %s
        ORDER BY a.published_at ASC NULLS LAST;
    """
    def _execute(connection):
        with connection.cursor() as cur:
            cur.execute(query, (event_id,))
            rows = cur.fetchall()
            return [
                {
                    "id": str(r[0]),
                    "source_name": r[1],
                    "headline": r[2],
                    "article_url": r[3],
                    "published_at": r[4],
                    "full_text": r[5],
                }
                for r in rows
            ]

    if conn:
        return _execute(conn)
    with psycopg.connect(db_url) as connection:
        return _execute(connection)


def get_articles_needing_quote_extraction(
    conn, limit: int = 50
) -> list[tuple[str, str]]:
    """Return completed articles pending quote extraction."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT a.id, a.full_text
            FROM articles a
            WHERE a.scrape_status = 'completed'
              AND a.full_text IS NOT NULL
              AND a.quote_extraction_status IS NULL
            LIMIT %s;
            """,
            (limit,),
        )
        return cur.fetchall()




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

    def _execute(connection, cur):
        try:
            with connection.transaction():
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
            _execute(conn, cur)
    else:
        with psycopg.connect(db_url) as connection:
            with connection.cursor() as cur:
                _execute(connection, cur)
            connection.commit()


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

