"""
Shared constants for the extraction layer.

Centralised here to avoid circular imports between extract/ and llm/.
"""

ROLE_LABELS: list[str] = [
    "government",
    "opposition",
    "expert",
    "police",
    "citizen",
]
