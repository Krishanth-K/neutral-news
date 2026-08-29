"""
Named entity extraction from article full text using spaCy.

Extracts relevant entities (PERSON, ORG, GPE, LOC, EVENT, LAW, NORP)
and stores them in the entities table.
"""

from __future__ import annotations

import spacy

from neutral_news.db.articles import insert_entity

# Focus only on entity types relevant for news comparison & clustering
RELEVANT_LABELS = {
    "PERSON",  # People: e.g., "Narendra Modi", "Rahul Gandhi"
    "ORG",     # Organizations: e.g., "Supreme Court", "BJP", "RBI", "Tata"
    "GPE",     # Geopolitical entities: e.g., "India", "Delhi", "Punjab"
    "LOC",     # Non-GPE locations: e.g., "Red Fort", "Himalayas"
    "EVENT",   # Named events: e.g., "G20 Summit", "Farmers Protest"
    "LAW",     # Named laws / acts: e.g., "Farm Bills", "Section 144"
    "NORP",    # Nationalities, religious/political groups: e.g., "Congress", "Indian"
}

_nlp = None


def _get_nlp():
    """Lazy-load the spaCy NLP pipeline (loaded once, cached in memory)."""
    global _nlp
    if _nlp is None:
        _nlp = spacy.load("en_core_web_trf")
    return _nlp


def extract_entities_from_text(text: str) -> list[tuple[str, str]]:
    """Extract and deduplicate relevant named entities from raw text."""
    if not text or not text.strip():
        return []

    doc = _get_nlp()(text)
    entities = []
    seen = set()

    for ent in doc.ents:
        clean_text = " ".join(ent.text.split()).strip()
        if ent.label_ in RELEVANT_LABELS and len(clean_text) > 1:
            key = (clean_text.lower(), ent.label_)
            if key not in seen:
                seen.add(key)
                entities.append((clean_text, ent.label_))

    return entities


def get_articles_needing_extraction(conn, limit: int = 50) -> list[tuple[str, str]]:
    """Return completed articles pending entity extraction."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT a.id, a.full_text
            FROM articles a
            WHERE a.scrape_status = 'completed'
              AND a.full_text IS NOT NULL
              AND a.entity_extraction_status IS NULL
            LIMIT %s;
            """,
            (limit,),
        )
        return cur.fetchall()


def _set_status(article_id: str, status: str, conn) -> None:
    """Update entity_extraction_status for an article."""
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE articles
            SET entity_extraction_status = %s,
                updated_at = NOW()
            WHERE id = %s;
            """,
            (status, article_id),
        )


def extract_article_entities(article_id: str, text: str, conn) -> list[tuple[str, str]]:
    """Extract entities for a single article, save them to DB, and mark completed."""
    entities = extract_entities_from_text(text)

    for ent_text, ent_label in entities:
        insert_entity(article_id, ent_text, ent_label, conn=conn)

    _set_status(article_id, "completed", conn)
    return entities


def extract_named_entities(
    conn, limit: int | None = None, batch_size: int = 50
) -> None:
    """Extract and store named entities for completed articles in batches."""
    total = 0
    while True:
        fetch_limit = (
            min(batch_size, limit - total) if limit is not None else batch_size
        )
        if fetch_limit <= 0:
            break

        rows = get_articles_needing_extraction(conn, limit=fetch_limit)
        if not rows:
            break

        print(f"[EXTRACT] Processing batch of {len(rows)} articles...")
        for article_id, text in rows:
            try:
                extracted = extract_article_entities(article_id, text, conn)
                print(f"  ✓ Extracted {len(extracted)} entities for article {article_id}")
            except Exception as e:
                print(f"  ✗ Failed for article {article_id}: {e}")
                conn.rollback()
                # _set_status(article_id, "failed", conn)
            total += 1

        conn.commit()
        if limit is not None and total >= limit:
            break

    print(f"[EXTRACT] Done. Processed {total} articles.")
