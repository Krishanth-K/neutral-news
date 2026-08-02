"""
RSS Feed Polling Module for Media Lens / Neutral News.

Fetches and standardizes article metadata (headline, article_url, published_at, source_name)
from RSS feeds according to the project specifications.
"""

import time
from datetime import datetime, timezone

import feedparser
import httpx

# V1 Outlets as specified in IDEA.md
THE_HINDU_RSS_URL = "https://www.thehindu.com/news/national/feeder/default.rss"
INDIAN_EXPRESS_RSS_URL = "https://indianexpress.com/section/india/feed/"
TIMES_OF_INDIA_RSS_URL = "https://timesofindia.indiatimes.com/rssfeeds/-2128936835.cms"
NDTV_RSS_URL = "https://feeds.feedburner.com/ndtvnews-india-news"

RSS_FEEDS = {
    "The Hindu": THE_HINDU_RSS_URL,
    "Indian Express": INDIAN_EXPRESS_RSS_URL,
    "Times of India": TIMES_OF_INDIA_RSS_URL,
    "NDTV": NDTV_RSS_URL,
}

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}


def _infer_source_name(url: str, feed_title: str | None = None) -> str:
    """Infer the news source name from the URL or feed title."""
    for source_name, feed_url in RSS_FEEDS.items():
        if url == feed_url:
            return source_name

    url_lower = url.lower()
    if "thehindu.com" in url_lower:
        return "The Hindu"
    if "indianexpress.com" in url_lower:
        return "Indian Express"
    if "indiatimes.com" in url_lower:
        return "Times of India"
    if "ndtv.com" in url_lower or "ndtvnews" in url_lower:
        return "NDTV"

    return feed_title or "Unknown Source"


def _format_published_date(entry: feedparser.FeedParserDict) -> str:
    """Format published timestamp into ISO 8601 string in UTC."""
    pub_tuple = entry.get("published_parsed") or entry.get("updated_parsed")
    if pub_tuple and isinstance(pub_tuple, (time.struct_time, tuple)) and len(pub_tuple) >= 6:
        try:
            year, month, day, hour, minute, second = (int(pub_tuple[i]) for i in range(6))
            dt = datetime(year, month, day, hour, minute, second, tzinfo=timezone.utc)
            return dt.isoformat()
        except (TypeError, ValueError):
            pass

    pub_val = entry.get("published") or entry.get("updated") or ""
    if isinstance(pub_val, str):
        return pub_val
    return str(pub_val) if pub_val else ""


def fetch_url(url: str, timeout: float = 10.0, headers: dict | None = None) -> str | None:
    """
    Fetch raw text content from a URL using httpx.

    Args:
        url: The web page or feed URL to fetch.
        timeout: Request timeout in seconds.
        headers: Optional custom HTTP headers (defaults to DEFAULT_HEADERS).

    Returns:
        Response text content if successful, or None if the request failed.
    """
    if headers is None:
        headers = DEFAULT_HEADERS

    try:
        response = httpx.get(
            url,
            headers=headers,
            timeout=timeout,
            follow_redirects=True,
        )
        response.raise_for_status()
        return response.text
    except httpx.HTTPError as exc:
        print(f"[ERROR] Failed to fetch URL {url}: {exc}")
        return None


def poll_rss(url: str, source_name: str | None = None, timeout: float = 10.0) -> list[dict]:
    """
    Fetch and parse news articles from an RSS feed URL.

    Args:
        url: The RSS feed URL to fetch.
        source_name: Optional explicit name of the news outlet.
        timeout: Request timeout in seconds.

    Returns:
        List of dictionaries, each containing:
            - headline (str): Article title
            - article_url (str): Link to full article
            - published_at (str): Publication timestamp (ISO 8601 UTC)
            - source_name (str): Name of the newspaper source
    """
    raw_xml = fetch_url(url, timeout=timeout)
    if not raw_xml:
        return []

    feed = feedparser.parse(raw_xml)
    if feed.bozo and not feed.entries:
        print(f"[WARNING] Feed parsing warning/error for {url}: {feed.bozo_exception}")

    resolved_source = source_name or _infer_source_name(url, feed.feed.get("title"))

    articles = []
    for entry in feed.entries:
        headline = entry.get("title", "").strip()
        article_url = entry.get("link", "").strip()

        if not headline or not article_url:
            continue

        published_at = _format_published_date(entry)

        articles.append({
            "headline": headline,
            "article_url": article_url,
            "published_at": published_at,
            "source_name": resolved_source,
        })

    return articles


def poll_all_feeds(timeout: float = 10.0) -> list[dict]:
    """
    Poll all configured V1 RSS feeds (The Hindu, Indian Express, Times of India, NDTV).

    Returns:
        Combined list of article metadata dictionaries across all sources.
    """
    all_articles = []
    for source_name, url in RSS_FEEDS.items():
        articles = poll_rss(url=url, source_name=source_name, timeout=timeout)
        all_articles.extend(articles)
    return all_articles


if __name__ == "__main__":
    print("Testing RSS feed poller...")
    results = poll_all_feeds()
    print(f"\nSuccessfully fetched total {len(results)} articles across all feeds.")
    if results:
        print("\nSample article record:")
        print(results[0])
