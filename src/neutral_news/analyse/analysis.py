"""
Analysis module for Media Lens.

Provides cross-article analysis across two primary dimensions:
1. Quote Distribution: Voice amplification, proportions, dominant roles, and omissions by source.
2. Missing Context: Entity coverage and omissions across competing news sources covering the same event.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from neutral_news.db.articles import (
    get_articles_for_event,
    retrieve_entities_by_article_id,
    retrieve_event_articles_id_by_source,
    retrieve_quotes_for_event,
)
from neutral_news.extract.constants import ROLE_LABELS
from neutral_news.ingest.rss import RSS_FEEDS

ALL_ROLES: list[str] = ROLE_LABELS + ["other"]


def analyse_quote_distribution(event_id: str, conn=None) -> dict[str, Any]:
    """Compute quote counts, role proportions, and voice diversity per source for an event.

    Returns structured evidence comparing how different outlets represent various voices
    (government, opposition, expert, police, citizen, etc.).
    """
    event_articles = get_articles_for_event(event_id, conn=conn)
    if not event_articles:
        return {
            "event_id": event_id,
            "sources_analyzed": [],
            "total_quotes": 0,
            "by_source": {},
        }

    # 1. Fetch all quotes linked to this event
    quotes = retrieve_quotes_for_event(event_id, conn=conn)

    # 2. Extract unique sources participating in the event
    sources = sorted({a["source_name"] for a in event_articles})

    # 3. Initialize per-source data structures
    source_role_counts: dict[str, dict[str, int]] = {
        source: {role: 0 for role in ALL_ROLES} for source in sources
    }
    source_quotes_detail: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for q in quotes:
        src = q["source_name"]
        role = q["role"] if q["role"] in ALL_ROLES else "other"
        if src in source_role_counts:
            source_role_counts[src][role] += 1
            source_quotes_detail[src].append(
                {
                    "speaker": q["speaker"],
                    "role": role,
                    "quote_text": q["quote_text"],
                    "headline": q["headline"],
                    "article_id": q["article_id"],
                }
            )

    # 4. Calculate distributions and metrics per source
    distribution_by_source: dict[str, dict[str, Any]] = {}
    for source, counts in source_role_counts.items():
        total_quotes = sum(counts.values())
        proportions = {
            role: round(count / total_quotes, 3) if total_quotes > 0 else 0.0
            for role, count in counts.items()
        }

        # Find dominant voice (highest proportion role among nonzero counts)
        dominant_role = (
            max(counts, key=lambda k: counts[k]) if total_quotes > 0 else None
        )

        # Identify omitted roles
        omitted_roles = [r for r in ROLE_LABELS if counts[r] == 0]

        distribution_by_source[source] = {
            "total_quotes": total_quotes,
            "counts": counts,
            "proportions": proportions,
            "dominant_role": dominant_role,
            "omitted_roles": omitted_roles,
            "quotes": source_quotes_detail[source],
        }

    return {
        "event_id": event_id,
        "sources_analyzed": sources,
        "total_quotes": len(quotes),
        "by_source": distribution_by_source,
    }


def analyse_missing_context(event_id: str, conn=None) -> dict[str, Any]:
    """Compute entity coverage and identify entities omitted by each source for an event.

    1. Group articles in the event by source.
    2. Retrieve extracted entities for each group.
    3. Compute universal entity set across all sources.
    4. Calculate missing entities per source (set difference).
    """
    event_articles = get_articles_for_event(event_id, conn=conn)
    if not event_articles:
        return {
            "event_id": event_id,
            "sources_analyzed": [],
            "universal_entity_count": 0,
            "missing_by_source": {},
        }

    # Only inspect sources present in this specific event
    sources = sorted({a["source_name"] for a in event_articles})

    # {source: [article_ids, ...]}
    source_articles = {
        source: retrieve_event_articles_id_by_source(event_id, source, conn=conn)
        for source in sources
    }

    # {source: {"Entity Name", ...}}
    source_entities: dict[str, set[str]] = {}
    for source, articles in source_articles.items():
        entities = retrieve_entities_by_article_id(articles, conn=conn)
        source_entities[source] = {e["text"] for e in entities}

    # Build universal set of all unique entities across all sources in this event
    universal_set: set[str] = set()
    for entities in source_entities.values():
        universal_set.update(entities)

    # Compute missing entities and presence for each source
    missing_context: dict[str, dict[str, Any]] = {}
    for source, entities in source_entities.items():
        missing = sorted(universal_set - entities)
        present = sorted(entities)
        missing_context[source] = {
            "present_count": len(present),
            "missing_count": len(missing),
            "missing_entities": missing,
            "present_entities": present,
        }

    return {
        "event_id": event_id,
        "sources_analyzed": sources,
        "universal_entity_count": len(universal_set),
        "missing_by_source": missing_context,
    }


def analyse_event(event_id: str, conn=None) -> dict[str, Any]:
    """Run both quote distribution and missing context analyses for a given event."""
    return {
        "event_id": event_id,
        "quote_distribution": analyse_quote_distribution(event_id, conn=conn),
        "missing_context": analyse_missing_context(event_id, conn=conn),
    }
