"""
Test script for Quote Distribution and Missing Context analysis.

Runs analysis on available events in the database and pretty-prints the structured evidence.
"""

from __future__ import annotations

import argparse
import json
import psycopg

from neutral_news.analyse import analyse_event, analyse_quote_distribution, analyse_missing_context
from neutral_news.config import DATABASE_URL
from neutral_news.db.articles import get_all_events


def main() -> None:
    parser = argparse.ArgumentParser(description="Test quote distribution and missing context analysis.")
    parser.add_argument("--event-id", type=str, default=None, help="Specific event UUID to analyze.")
    parser.add_argument("--limit", type=int, default=5, help="Number of events to analyze if no event-id specified.")
    args = parser.parse_args()

    events = []
    if args.event_id:
        events = [{"id": args.event_id, "title": "Specified Event", "article_count": "?"}]
    else:
        all_events = get_all_events()
        # Prefer events with multiple articles
        events = [e for e in all_events if e.get("article_count", 0) > 1][: args.limit]
        if not events:
            events = all_events[: args.limit]

    if not events:
        print("[WARN] No events found in the database. Run `make group` first to cluster articles into events.")
        return

    print(f"Found {len(events)} event(s) to analyze.\n" + "=" * 80)

    for i, ev in enumerate(events, 1):
        event_id = ev["id"]
        title = ev.get("title", "Untitled")
        art_count = ev.get("article_count", "N/A")

        print(f"\n[{i}/{len(events)}] EVENT: {title}")
        print(f"ID: {event_id} | Articles: {art_count}")
        print("-" * 80)

        # 1. Quote Distribution
        quote_analysis = analyse_quote_distribution(event_id)
        print("\n📊 QUOTE DISTRIBUTION:")
        print(f"Total quotes: {quote_analysis['total_quotes']}")
        print(f"Sources analyzed: {quote_analysis['sources_analyzed']}")

        for source, data in quote_analysis["by_source"].items():
            print(f"\n  • Source: {source} (Total quotes: {data['total_quotes']})")
            print(f"    Counts:      {data['counts']}")
            print(f"    Proportions: {data['proportions']}")
            print(f"    Dominant:    {data['dominant_role']}")
            print(f"    Omitted:     {data['omitted_roles']}")
            if data["quotes"]:
                print(f"    Sample Quote: \"{data['quotes'][0]['quote_text'][:80]}...\" (Speaker: {data['quotes'][0]['speaker']}, Role: {data['quotes'][0]['role']})")

        # 2. Missing Context
        missing_analysis = analyse_missing_context(event_id)
        print("\n🔍 MISSING CONTEXT (ENTITY OVERLAP):")
        print(f"Universal unique entities: {missing_analysis['universal_entity_count']}")

        for source, data in missing_analysis["missing_by_source"].items():
            print(f"\n  • Source: {source}")
            print(f"    Present count: {data['present_count']} | Missing count: {data['missing_count']}")
            if data["missing_entities"]:
                sample_missing = data["missing_entities"][:5]
                print(f"    Sample missing entities: {sample_missing}")

        print("\n" + "=" * 80)


if __name__ == "__main__":
    main()
