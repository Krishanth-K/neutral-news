import trafilatura

def extract_text_from_url(url: str) -> tuple[str | None, str | None]:
    """
    Fetches and extracts the main article text and heading from a URL using trafilatura.
    Returns a tuple of (title, text), either of which may be None if extraction fails.
    """
    downloaded = trafilatura.fetch_url(url)
    if downloaded is None:
        return None, None

    # Extract metadata to get the article title/heading
    metadata = trafilatura.extract_metadata(downloaded)
    title = metadata.title if metadata else None

    # Extract text, stripping HTML, ads, nav, etc.
    text = trafilatura.extract(downloaded)
    return title, text
