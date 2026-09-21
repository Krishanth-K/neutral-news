"""Database query services for the Neutral News / Media Lens web application."""

from __future__ import annotations

import json
from collections import defaultdict
from typing import Any, Dict, List, Optional
import psycopg

from neutral_news.analyse.analysis import analyse_event
from neutral_news.config import DATABASE_URL
from neutral_news.db.articles import (
    get_all_events,
    get_articles_for_event,
    get_event_analysis,
    retrieve_entities_by_article_id,
    retrieve_quotes_for_event,
)


def get_events_feed(
    search: Optional[str] = None,
    source: Optional[str] = None,
    multi_source_only: bool = False,
    page: int = 1,
    page_size: int = 20,
) -> dict[str, Any]:
    """Fetch paginated events for the main news feed with metadata and source badges."""
    offset = max(0, (page - 1) * page_size)

    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            # Query events with aggregated source names and article counts
            base_query = """
                SELECT 
                    e.id,
                    e.title,
                    e.created_at,
                    COUNT(DISTINCT a.id) as article_count,
                    ARRAY_AGG(DISTINCT a.source_name) FILTER (WHERE a.source_name IS NOT NULL) as sources,
                    MIN(a.published_at) as earliest_pub,
                    MAX(a.published_at) as latest_pub,
                    COUNT(DISTINCT q.id) as quote_count,
                    COUNT(DISTINCT ent.id) as entity_count
                FROM events e
                JOIN event_articles ea ON ea.event_id = e.id
                JOIN articles a ON ea.article_id = a.id
                LEFT JOIN quotes q ON q.article_id = a.id
                LEFT JOIN entities ent ON ent.article_id = a.id
            """

            conditions = []
            params: list[Any] = []

            if search and search.strip():
                conditions.append("(e.title ILIKE %s OR a.headline ILIKE %s)")
                term = f"%{search.strip()}%"
                params.extend([term, term])

            if source and source.strip() and source.lower() != "all":
                conditions.append("a.source_name = %s")
                params.append(source.strip())

            if conditions:
                base_query += " WHERE " + " AND ".join(conditions)

            base_query += """
                GROUP BY e.id, e.title, e.created_at
            """

            if multi_source_only:
                base_query += " HAVING COUNT(DISTINCT a.source_name) > 1"

            # Total count query using CTE
            count_query = f"WITH event_list AS ({base_query}) SELECT COUNT(*) FROM event_list;"
            cur.execute(count_query, params)
            total_items = cur.fetchone()[0]

            # Fetch paginated items, sorting by multi-source first then latest publication/creation
            data_query = f"""
                WITH event_list AS ({base_query})
                SELECT 
                    id,
                    title,
                    created_at,
                    article_count,
                    sources,
                    earliest_pub,
                    latest_pub,
                    quote_count,
                    entity_count,
                    CARDINALITY(sources) as source_count
                FROM event_list
                ORDER BY source_count DESC, COALESCE(latest_pub, created_at) DESC
                LIMIT %s OFFSET %s;
            """
            cur.execute(data_query, params + [page_size, offset])
            rows = cur.fetchall()

            events = []
            for r in rows:
                events.append({
                    "id": str(r[0]),
                    "title": r[1],
                    "created_at": r[2].isoformat() if r[2] else None,
                    "article_count": r[3],
                    "sources": sorted(list(r[4] or [])),
                    "source_count": len(r[4] or []),
                    "earliest_pub": r[5].isoformat() if r[5] else None,
                    "latest_pub": r[6].isoformat() if r[6] else None,
                    "quote_count": r[7],
                    "entity_count": r[8],
                })

            total_pages = (total_items + page_size - 1) // page_size if total_items > 0 else 1

            return {
                "events": events,
                "pagination": {
                    "page": page,
                    "page_size": page_size,
                    "total_items": total_items,
                    "total_pages": total_pages,
                    "has_next": page < total_pages,
                    "has_prev": page > 1,
                },
            }


def get_event_detail_with_analysis(event_id: str) -> Optional[dict[str, Any]]:
    """Fetch complete event information, articles, quotes, entities, analysis, and related news."""
    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            # 1. Fetch Event metadata
            cur.execute(
                """
                SELECT id, title, created_at, updated_at
                FROM events
                WHERE id = %s;
                """,
                (event_id,),
            )
            event_row = cur.fetchone()
            if not event_row:
                return None

            event = {
                "id": str(event_row[0]),
                "title": event_row[1],
                "created_at": event_row[2].isoformat() if event_row[2] else None,
                "updated_at": event_row[3].isoformat() if event_row[3] else None,
            }

            # 2. Fetch all Articles for this event
            cur.execute(
                """
                SELECT 
                    a.id,
                    a.source_name,
                    a.headline,
                    a.article_url,
                    a.published_at,
                    a.authors,
                    a.full_text,
                    a.scrape_status,
                    a.scraped_at
                FROM event_articles ea
                JOIN articles a ON ea.article_id = a.id
                WHERE ea.event_id = %s
                ORDER BY a.source_name ASC, a.published_at ASC NULLS LAST;
                """,
                (event_id,),
            )
            article_rows = cur.fetchall()
            articles = []
            article_ids = []
            for ar in article_rows:
                aid = str(ar[0])
                article_ids.append(aid)
                # Compute snippet preview
                full_text = ar[6] or ""
                snippet = full_text[:350] + "..." if len(full_text) > 350 else full_text
                articles.append({
                    "id": aid,
                    "source_name": ar[1],
                    "headline": ar[2],
                    "article_url": ar[3],
                    "published_at": ar[4].isoformat() if ar[4] else None,
                    "authors": ar[5] or [],
                    "snippet": snippet,
                    "full_text_length": len(full_text),
                    "scrape_status": ar[7],
                    "scraped_at": ar[8].isoformat() if ar[8] else None,
                })

            # 3. Fetch Quotes for this event
            cur.execute(
                """
                SELECT 
                    q.id,
                    q.article_id,
                    a.source_name,
                    q.quote_text,
                    q.speaker,
                    q.role,
                    q.created_at
                FROM quotes q
                JOIN articles a ON q.article_id = a.id
                WHERE q.article_id = ANY(%s)
                ORDER BY a.source_name, q.created_at ASC;
                """,
                (article_ids,),
            )
            quote_rows = cur.fetchall()
            quotes = []
            for qr in quote_rows:
                quotes.append({
                    "id": str(qr[0]),
                    "article_id": str(qr[1]),
                    "source_name": qr[2],
                    "quote_text": qr[3],
                    "speaker": qr[4] or "Unidentified speaker",
                    "role": qr[5] or "other",
                    "created_at": qr[6].isoformat() if qr[6] else None,
                })

            # 4. Fetch Entities for this event
            cur.execute(
                """
                SELECT 
                    e.id,
                    e.article_id,
                    a.source_name,
                    e.text,
                    e.label
                FROM entities e
                JOIN articles a ON e.article_id = a.id
                WHERE e.article_id = ANY(%s)
                ORDER BY e.text ASC;
                """,
                (article_ids,),
            )
            entity_rows = cur.fetchall()
            entities = []
            for er in entity_rows:
                entities.append({
                    "id": str(er[0]),
                    "article_id": str(er[1]),
                    "source_name": er[2],
                    "text": er[3],
                    "label": er[4],
                })

            # 5. Compute Analysis (use live analysis for latest accurate metrics)
            analysis = analyse_event(event_id, conn=conn)

            # 6. Fetch Related Events (events sharing similar timeline or entities)
            cur.execute(
                """
                SELECT 
                    e2.id,
                    e2.title,
                    COUNT(ea2.article_id) as article_count,
                    ARRAY_AGG(DISTINCT a2.source_name) as sources,
                    MAX(a2.published_at) as latest_pub,
                    e2.created_at
                FROM events e2
                JOIN event_articles ea2 ON ea2.event_id = e2.id
                JOIN articles a2 ON ea2.article_id = a2.id
                WHERE e2.id != %s
                GROUP BY e2.id, e2.title, e2.created_at
                ORDER BY COUNT(ea2.article_id) DESC, e2.created_at DESC
                LIMIT 4;
                """,
                (event_id,),
            )
            related_rows = cur.fetchall()
            related_events = []
            for rr in related_rows:
                related_events.append({
                    "id": str(rr[0]),
                    "title": rr[1],
                    "article_count": rr[2],
                    "sources": sorted(list(rr[3] or [])),
                    "latest_pub": rr[4].isoformat() if rr[4] else None,
                })

            return {
                "event": event,
                "articles": articles,
                "quotes": quotes,
                "entities": entities,
                "analysis": analysis,
                "related_events": related_events,
            }


def get_sources_list() -> list[dict[str, Any]]:
    """Return available news sources and their article counts."""
    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT source_name, COUNT(*) as count, MAX(published_at) as latest_published
                FROM articles
                GROUP BY source_name
                ORDER BY count DESC;
                """
            )
            rows = cur.fetchall()
            return [
                {
                    "name": r[0],
                    "count": r[1],
                    "latest_published": r[2].isoformat() if r[2] else None,
                }
                for r in rows
            ]


def get_database_stats() -> dict[str, Any]:
    """Retrieve comprehensive database statistics for the debug panel."""
    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            # Table counts
            counts = {}
            for tbl in [
                "articles",
                "article_embeddings",
                "quotes",
                "entities",
                "events",
                "event_articles",
                "event_analysis",
            ]:
                cur.execute(f"SELECT COUNT(*) FROM {tbl};")
                counts[tbl] = cur.fetchone()[0]

            # Scrape status breakdown
            cur.execute(
                "SELECT scrape_status, COUNT(*) FROM articles GROUP BY scrape_status ORDER BY scrape_status;"
            )
            scrape_statuses = {str(r[0]): r[1] for r in cur.fetchall()}

            # Entity extraction breakdown
            cur.execute(
                """
                SELECT COALESCE(entity_extraction_status, 'pending'), COUNT(*) 
                FROM articles 
                GROUP BY entity_extraction_status;
                """
            )
            entity_statuses = {str(r[0]): r[1] for r in cur.fetchall()}

            # Quote extraction breakdown
            cur.execute(
                """
                SELECT COALESCE(quote_extraction_status, 'pending'), COUNT(*) 
                FROM articles 
                GROUP BY quote_extraction_status;
                """
            )
            quote_statuses = {str(r[0]): r[1] for r in cur.fetchall()}

            # Embedding status breakdown
            cur.execute(
                """
                SELECT COALESCE(embedding_status, 'pending'), COUNT(*) 
                FROM articles 
                GROUP BY embedding_status;
                """
            )
            embedding_statuses = {str(r[0]): r[1] for r in cur.fetchall()}

            # Multi-source events count
            cur.execute(
                """
                SELECT COUNT(*) FROM (
                    SELECT ea.event_id 
                    FROM event_articles ea
                    JOIN articles a ON ea.article_id = a.id
                    GROUP BY ea.event_id 
                    HAVING COUNT(DISTINCT a.source_name) > 1
                ) sub;
                """
            )
            multi_source_events_count = cur.fetchone()[0]

            # Database disk size
            cur.execute("SELECT pg_size_pretty(pg_database_size(current_database()));")
            db_size = cur.fetchone()[0]

            return {
                "counts": counts,
                "scrape_statuses": scrape_statuses,
                "entity_statuses": entity_statuses,
                "quote_statuses": quote_statuses,
                "embedding_statuses": embedding_statuses,
                "multi_source_events_count": multi_source_events_count,
                "db_size": db_size,
            }


def get_debug_articles_table(
    limit: int = 50,
    offset: int = 0,
    search: Optional[str] = None,
    source: Optional[str] = None,
    status: Optional[str] = None,
) -> dict[str, Any]:
    """Retrieve raw articles table rows for inspection and debugging."""
    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            conditions = []
            params: list[Any] = []

            if search and search.strip():
                conditions.append("(headline ILIKE %s OR article_url ILIKE %s)")
                term = f"%{search.strip()}%"
                params.extend([term, term])

            if source and source.strip() and source.lower() != "all":
                conditions.append("source_name = %s")
                params.append(source.strip())

            if status and status.strip() and status.lower() != "all":
                conditions.append("scrape_status = %s")
                params.append(status.strip())

            where_clause = " WHERE " + " AND ".join(conditions) if conditions else ""

            count_query = f"SELECT COUNT(*) FROM articles{where_clause};"
            cur.execute(count_query, params)
            total = cur.fetchone()[0]

            data_query = f"""
                SELECT 
                    id,
                    source_name,
                    headline,
                    article_url,
                    scrape_status,
                    entity_extraction_status,
                    quote_extraction_status,
                    published_at,
                    created_at,
                    scrape_attempts,
                    scrape_error,
                    embedding_status
                FROM articles
                {where_clause}
                ORDER BY created_at DESC
                LIMIT %s OFFSET %s;
            """
            cur.execute(data_query, params + [limit, offset])
            rows = cur.fetchall()

            articles = []
            for r in rows:
                articles.append({
                    "id": str(r[0]),
                    "source_name": r[1],
                    "headline": r[2],
                    "article_url": r[3],
                    "scrape_status": r[4],
                    "entity_status": r[5] or "pending",
                    "quote_status": r[6] or "pending",
                    "published_at": r[7].isoformat() if r[7] else None,
                    "created_at": r[8].isoformat() if r[8] else None,
                    "scrape_attempts": r[9],
                    "scrape_error": r[10],
                    "embedding_status": r[11] or "pending",
                })

            return {
                "total": total,
                "offset": offset,
                "limit": limit,
                "articles": articles,
            }


def get_raw_table_sample(table_name: str, limit: int = 25) -> dict[str, Any]:
    """Inspect any database table schema and sample rows for debugging."""
    allowed_tables = {
        "articles",
        "article_embeddings",
        "quotes",
        "entities",
        "events",
        "event_articles",
        "event_analysis",
        "event_explanations",
    }
    if table_name not in allowed_tables:
        raise ValueError(f"Table '{table_name}' is not an accessible debug table.")

    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            # Get columns
            cur.execute(
                """
                SELECT column_name, data_type 
                FROM information_schema.columns 
                WHERE table_name = %s 
                ORDER BY ordinal_position;
                """,
                (table_name,),
            )
            columns = [{"name": r[0], "type": r[1]} for r in cur.fetchall()]

            # Fetch rows
            cur.execute(f"SELECT * FROM {table_name} ORDER BY 1 DESC LIMIT %s;", (limit,))
            raw_rows = cur.fetchall()

            rows = []
            for row in raw_rows:
                row_dict = {}
                for idx, col in enumerate(columns):
                    val = row[idx]
                    if val is not None and hasattr(val, "isoformat"):
                        val = val.isoformat()
                    elif isinstance(val, (bytes, bytearray)):
                        val = "<binary>"
                    elif col["name"] == "embedding":
                        val = f"<vector(768)>"
                    elif isinstance(val, dict):
                        val = json.dumps(val)
                    else:
                        val = str(val) if val is not None else None
                    row_dict[col["name"]] = val
                rows.append(row_dict)

            return {
                "table_name": table_name,
                "columns": columns,
                "total_sample_rows": len(rows),
                "rows": rows,
            }
