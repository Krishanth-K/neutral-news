"""
LLM explanation orchestrator for Media Lens (Phase 6).

For a given event_id:
  1. Checks whether a fresh explanation already exists (skips unless force=True)
  2. Fetches the event title and pre-computed analysis evidence
  3. Builds a structured prompt via explain/prompt.py
  4. Calls Gemini Flash via llm/gemini.py
  5. Persists the result to event_explanations table

Can also be run as a standalone CLI script:
    python -m neutral_news.explain.explain_event [--force] [--event-id UUID]
"""

from __future__ import annotations

import argparse
import json
import logging
import sys

import psycopg

from neutral_news.config import DATABASE_URL
from neutral_news.db.articles import (
    get_all_events,
    get_event_analysis,
    get_event_explanation,
    upsert_event_explanation,
)
from neutral_news.explain.prompt import build_prompt
from neutral_news.llm.gemini import generate_explanation

log = logging.getLogger(__name__)

# Only explain events with at least this many distinct sources — single-source
# events produce trivial "one outlet covered this" explanations.
MIN_SOURCES_FOR_EXPLANATION = 2


def _get_event_title(event_id: str, conn) -> str | None:
    """Fetch the title of an event from the database."""
    with conn.cursor() as cur:
        cur.execute("SELECT title FROM events WHERE id = %s;", (event_id,))
        row = cur.fetchone()
        return row[0] if row else None


def explain_event(event_id: str, conn, force: bool = False) -> str | None:
    """Generate and persist an LLM explanation for a single event.

    Args:
        event_id: UUID string of the event to explain.
        conn: Active psycopg connection.
        force: If True, regenerate even if an explanation already exists.

    Returns:
        The generated explanation text, or None if skipped/failed.
    """
    # 1. Check for existing explanation
    if not force:
        existing = get_event_explanation(event_id, conn=conn)
        if existing:
            log.debug("Skipping event %s — explanation already exists.", event_id)
            return existing

    # 2. Fetch event title
    event_title = _get_event_title(event_id, conn)
    if not event_title:
        log.warning("Event %s not found — skipping.", event_id)
        return None

    # 3. Fetch analysis (from cached event_analysis table, or live computation)
    analysis = get_event_analysis(event_id, conn=conn)

    if analysis:
        quote_distribution = analysis.get("quote_distribution") or {}
        missing_context = analysis.get("missing_context") or {}
    else:
        # Fall back to live analysis if not yet persisted
        from neutral_news.analyse import analyse_event
        live = analyse_event(event_id, conn=conn)
        quote_distribution = live.get("quote_distribution") or {}
        missing_context = live.get("missing_context") or {}

    # 4. Skip single-source events
    sources = quote_distribution.get("sources_analyzed", [])
    if len(sources) < MIN_SOURCES_FOR_EXPLANATION:
        log.debug(
            "Skipping event %s — only %d source(s) (%s).",
            event_id,
            len(sources),
            sources,
        )
        return None

    # 5. Build prompt and call LLM
    prompt = build_prompt(
        event_title=event_title,
        quote_distribution=quote_distribution,
        missing_context=missing_context,
    )

    explanation_text = generate_explanation(prompt)
    if not explanation_text:
        log.warning("LLM returned empty explanation for event %s.", event_id)
        return None

    # 6. Persist to event_explanations
    evidence = {
        "quote_distribution": quote_distribution,
        "missing_context": missing_context,
    }
    upsert_event_explanation(
        event_id=event_id,
        explanation_text=explanation_text,
        evidence=evidence,
        conn=conn,
    )

    return explanation_text


def explain_all_events(conn, force: bool = False) -> int:
    """Generate explanations for all eligible events.

    Args:
        conn: Active psycopg connection.
        force: If True, regenerate explanations even for events that have one.

    Returns:
        Number of explanations generated.
    """
    events = get_all_events(conn=conn)
    generated = 0
    skipped = 0

    for event in events:
        event_id = event["id"]
        try:
            result = explain_event(event_id, conn=conn, force=force)
            if result is not None:
                print(f"  ✓ Explained event: {event.get('title', event_id)[:70]}")
                generated += 1
            else:
                skipped += 1
        except Exception as e:
            print(f"  ✗ Failed for event {event_id}: {e}")
            conn.rollback()

    conn.commit()
    print(f"[EXPLAIN] Done. Generated {generated} explanation(s), skipped {skipped}.")
    return generated


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate LLM explanations for Media Lens events."
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Regenerate explanations even if they already exist.",
    )
    parser.add_argument(
        "--event-id",
        metavar="UUID",
        help="Explain a single event by ID (default: all eligible events).",
    )
    args = parser.parse_args()

    try:
        with psycopg.connect(DATABASE_URL) as conn:
            if args.event_id:
                result = explain_event(args.event_id, conn=conn, force=args.force)
                if result:
                    print(f"[EXPLAIN] Generated explanation:\n\n{result}")
                else:
                    print("[EXPLAIN] No explanation generated (skipped or failed).")
                conn.commit()
            else:
                print(f"[EXPLAIN] Generating explanations for all eligible events"
                      f"{' (force mode)' if args.force else ''}...")
                explain_all_events(conn, force=args.force)
    except psycopg.OperationalError as exc:
        print(f"[FATAL] Database connection failed: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
