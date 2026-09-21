"""
Prompt builder for the LLM explainability layer.

Converts pre-computed analysis dicts (quote distribution + missing context)
into a structured, token-efficient prompt that asks Gemini to narrate the
evidence in plain, neutral language.

The LLM is given only facts — it must NOT infer, speculate, or label bias.
"""

from __future__ import annotations

from typing import Any

# Minimum number of sources that must mention an entity for it to be
# considered "notable enough" to include in the missing context section.
MIN_SOURCES_MENTIONING = 2

# Maximum number of missing entities to list per source (avoid prompt bloat)
MAX_MISSING_ENTITIES = 8

# Maximum number of quote examples to include per source
MAX_QUOTE_EXAMPLES = 2


def _fmt_percent(value: float) -> str:
    """Format a 0-1 fraction as a percentage string, e.g. '42%'."""
    return f"{round(value * 100)}%"


def _build_quote_section(quote_distribution: dict[str, Any]) -> str:
    """Render the quote distribution evidence as a readable text block."""
    by_source: dict[str, Any] = quote_distribution.get("by_source", {})
    if not by_source:
        return "No quote data is available for this event."

    lines: list[str] = []
    for source, data in sorted(by_source.items()):
        total = data.get("total_quotes", 0)
        dominant = data.get("dominant_role")
        omitted = data.get("omitted_roles", [])
        counts: dict[str, int] = data.get("counts", {})
        proportions: dict[str, float] = data.get("proportions", {})
        examples: list[dict] = data.get("quotes", [])

        lines.append(f"• {source}: {total} quote(s) total")
        if total > 0:
            role_breakdown = ", ".join(
                f"{role} {_fmt_percent(proportions.get(role, 0.0))} ({counts.get(role, 0)})"
                for role in counts
                if counts.get(role, 0) > 0
            )
            if role_breakdown:
                lines.append(f"  Breakdown: {role_breakdown}")
            if dominant:
                lines.append(f"  Dominant voice: {dominant}")
            if omitted:
                lines.append(f"  Voices absent: {', '.join(omitted)}")
            # Add a couple of example quotes for concreteness
            for ex in examples[:MAX_QUOTE_EXAMPLES]:
                speaker = ex.get("speaker") or "Unknown"
                role = ex.get("role", "other")
                snippet = (ex.get("quote_text") or "")[:120].strip()
                if snippet:
                    lines.append(f'  Example ({role}) — {speaker}: "{snippet}…"')
        else:
            lines.append("  No attributed quotes found.")

    return "\n".join(lines)


def _build_missing_context_section(missing_context: dict[str, Any]) -> str:
    """Render the missing context evidence as a readable text block.

    Only includes entities that are mentioned by at least MIN_SOURCES_MENTIONING
    outlets to filter out noisy single-source mentions.
    """
    missing_by_source: dict[str, Any] = missing_context.get("missing_by_source", {})
    sources = sorted(missing_by_source.keys())
    if not sources:
        return "No missing context data is available for this event."

    # Build a map: entity → set of sources that mention it
    entity_sources: dict[str, set[str]] = {}
    for source, data in missing_by_source.items():
        for entity in data.get("present_entities", []):
            entity_sources.setdefault(entity, set()).add(source)

    # Only entities mentioned by >= MIN_SOURCES_MENTIONING sources are notable
    notable_entities = {
        ent for ent, srcs in entity_sources.items()
        if len(srcs) >= MIN_SOURCES_MENTIONING
    }

    lines: list[str] = []
    any_notable_missing = False
    for source, data in sorted(missing_by_source.items()):
        missing = [e for e in (data.get("missing_entities") or []) if e in notable_entities]
        if not missing:
            lines.append(f"• {source}: No notable entities missing.")
        else:
            any_notable_missing = True
            truncated = missing[:MAX_MISSING_ENTITIES]
            suffix = f" (and {len(missing) - MAX_MISSING_ENTITIES} more)" if len(missing) > MAX_MISSING_ENTITIES else ""
            lines.append(f"• {source}: Missing {len(missing)} notable entity/entities — "
                         f"{', '.join(truncated)}{suffix}")

    if not any_notable_missing:
        return "All outlets covered the same key entities. No notable gaps found."

    return "\n".join(lines)


def build_prompt(
    event_title: str,
    quote_distribution: dict[str, Any],
    missing_context: dict[str, Any],
) -> str:
    """Build the full prompt for the LLM explanation call.

    Args:
        event_title: The title of the news event cluster.
        quote_distribution: Output from `analyse_quote_distribution()`.
        missing_context: Output from `analyse_missing_context()`.

    Returns:
        A structured prompt string ready to send to the LLM.
    """
    sources = sorted(quote_distribution.get("sources_analyzed", []))
    sources_str = ", ".join(sources) if sources else "multiple outlets"

    quote_section = _build_quote_section(quote_distribution)
    context_section = _build_missing_context_section(missing_context)

    prompt = f"""You are a neutral media analyst assistant. Your job is to write a clear, factual, \
one-paragraph summary (3–5 sentences) describing HOW different Indian news outlets covered \
a news event differently — based solely on the evidence below.

Rules:
- Report only what the evidence shows. Do NOT add opinions, inferences, or speculation.
- Do NOT use words like "biased", "slanted", "propaganda", or make moral judgments.
- Refer to outlets by name. Use plain English. No bullet points in your response.
- If evidence is thin (few quotes, few entities), say so briefly rather than overstate.

EVENT: {event_title}
SOURCES COMPARED: {sources_str}

--- QUOTE DISTRIBUTION EVIDENCE ---
{quote_section}

--- MISSING CONTEXT EVIDENCE ---
{context_section}

Write your neutral, factual summary now:"""

    return prompt
