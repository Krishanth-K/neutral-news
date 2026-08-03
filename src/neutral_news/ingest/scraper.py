"""
Article text scraper.

Fetches and extracts the main body text from article URLs using trafilatura.
"""

import trafilatura


def extract_text_from_url(url: str) -> tuple[str | None, str | None]:
    """Fetch and extract the main article text and title from a URL.

    Returns:
        A tuple of (title, text), either of which may be None if extraction fails.
    """
    downloaded = trafilatura.fetch_url(url)
    if downloaded is None:
        return None, None

    metadata = trafilatura.extract_metadata(downloaded)
    title = metadata.title if metadata else None

    text = trafilatura.extract(downloaded)
    return title, text
