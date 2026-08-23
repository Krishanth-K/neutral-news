"""
Article text scraper.

Uses domain-specific extractors for known sites (more reliable than
generic trafilatura on pages with complex author-bio layouts), falling
back to trafilatura for unknown domains.
"""

from urllib.parse import urlparse

import httpx
import trafilatura
from bs4 import BeautifulSoup

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}
_MIN_PARAGRAPH_LEN = 40  # discard short nav/caption strings


def _fetch_html(url: str, timeout: float = 15.0) -> str | None:
    """Fetch raw HTML. Returns None on error."""
    try:
        r = httpx.get(url, headers=_HEADERS, timeout=timeout, follow_redirects=True)
        r.raise_for_status()
        return r.text
    except httpx.HTTPError as e:
        print(f"[SCRAPE] HTTP error for {url}: {e}")
        return None


# ── Domain-specific extractors ────────────────────────────────────────────────

def _extract_indian_express(html: str) -> tuple[str | None, str | None]:
    """
    Custom extractor for indianexpress.com.

    Target: div#pcl-full-content  (confirmed via DOM inspection)
    Noise:  .readmore, .paywall, .article-body-readmore (author bio lives here)
    """
    soup = BeautifulSoup(html, "lxml")

    # Title
    title_tag = soup.select_one("h1.native-article-title, h1")
    title = title_tag.get_text(strip=True) if title_tag else None

    # Body
    body = soup.select_one("#pcl-full-content")
    if not body:
        return title, None  # signal caller to fall back to trafilatura

    # Strip noise subtrees before collecting paragraphs
    for noise in body.select(
        '[class*="readmore"], [class*="paywall"], [class*="author"],'
        '[class*="social"], [class*="tags"], [class*="related"]'
    ):
        noise.decompose()

    paragraphs = [
        p.get_text(strip=True)
        for p in body.find_all("p")
        if len(p.get_text(strip=True)) >= _MIN_PARAGRAPH_LEN
    ]
    text = "\n\n".join(paragraphs) if paragraphs else None
    return title, text


def _extract_trafilatura(html: str) -> tuple[str | None, str | None]:
    """Generic trafilatura fallback."""
    metadata = trafilatura.extract_metadata(html)
    title = metadata.title if metadata else None
    text = trafilatura.extract(
        html,
        favor_precision=True,
        include_comments=False,
        include_tables=False,
    )
    return title, text


# ── Public API ────────────────────────────────────────────────────────────────

_DOMAIN_EXTRACTORS = {
    "indianexpress.com": _extract_indian_express,
}


def extract_text_from_url(url: str) -> tuple[str | None, str | None]:
    """
    Fetch and extract (title, body_text) from an article URL.

    Uses a domain-specific extractor when available; falls back to trafilatura.
    Returns (None, None) if the page cannot be fetched or no text found.
    """
    html = _fetch_html(url)
    if html is None:
        return None, None

    domain = urlparse(url).netloc.removeprefix("www.")

    extractor = _DOMAIN_EXTRACTORS.get(domain)
    if extractor:
        title, text = extractor(html)
        # Fall back to trafilatura if custom extractor returned nothing
        if not text:
            print(f"[SCRAPE] Custom extractor found no text for {url}, falling back to trafilatura")
            title, text = _extract_trafilatura(html)
    else:
        title, text = _extract_trafilatura(html)

    return title, text
