import sys
import psycopg
from psycopg import errors

from neutral_news.config import DATABASE_URL
from neutral_news.db.articles import (
    get_pending_articles,
    insert_article,
    update_article_text,
)
from neutral_news.embed.embedder import embed_pending_articles
from neutral_news.ingest.rss import poll_all_feeds
from neutral_news.ingest.scraper import extract_text_from_url


def _scrape_pending_articles(conn, batch_size: int = 50) -> None:
    """Fetch and scrape full text for all pending articles in batches."""
    total_processed = 0
    while True:
        pending = get_pending_articles(limit=batch_size, conn=conn)
        if not pending:
            break

        print(f"[SCRAPE] Processing batch of {len(pending)} pending articles...")
        for article_id, url in pending:
            try:
                title, text = extract_text_from_url(url)
                if text:
                    update_article_text(
                        article_id=article_id,
                        full_text=text,
                        status="completed",
                        conn=conn,
                    )
                    print(f"  ✓ Processed: {url[:60]}...")
                else:
                    update_article_text(
                        article_id=article_id,
                        error="Failed to extract main text",
                        status="failed",
                        conn=conn,
                    )
                    print(f"  ✗ Failed (no text extracted): {url[:60]}...")
            except Exception as e:
                print(f"  ✗ Error extracting {url[:60]}: {e}")
                try:
                    update_article_text(
                        article_id=article_id,
                        error=str(e),
                        status="failed",
                        conn=conn,
                    )
                except Exception as update_err:
                    print(f"  ✗ Could not record failure status for {article_id}: {update_err}")

            total_processed += 1

        conn.commit()

    print(f"[SCRAPE] Finished scraping full text for {total_processed} articles.")


def run() -> None:
    """Execute the full pipeline: ingest → scrape → embed."""
    # 1. Poll RSS feeds from all sources
    feed = poll_all_feeds()
    print(f"[PIPELINE] Fetched {len(feed)} items across all RSS feeds.")

    try:
        with psycopg.connect(DATABASE_URL) as conn:
            # 2. Store raw RSS records
            for record in feed:
                insert_article(record, conn=conn)
            conn.commit()
            print("[PIPELINE] Saved all records to the database.")

            # 3. Scrape full text for pending articles
            print("[PIPELINE] Scraping full text for pending articles...")
            _scrape_pending_articles(conn)

            # 4. Generate embeddings for newly completed articles
            print("[PIPELINE] Generating embeddings for completed articles...")
            embed_pending_articles(conn)

    except errors.LockNotAvailable as exc:
        print(f"\n[FATAL] Database lock contention: a table or row is locked by another process.")
        print(f"Details: {exc}")
        print("Pipeline aborted gracefully. Please wait for the other transaction/migration to finish.")
        sys.exit(1)
    except errors.DeadlockDetected as exc:
        print(f"\n[FATAL] Database deadlock detected: two concurrent transactions conflicted.")
        print(f"Details: {exc}")
        print("Pipeline aborted gracefully. Safe to retry.")
        sys.exit(1)
    except psycopg.OperationalError as exc:
        print(f"\n[FATAL] Database connection failed or database is unavailable: {exc}")
        print("Pipeline aborted gracefully. Please verify that Postgres is running (`make db-up`).")
        sys.exit(1)
    except psycopg.Error as exc:
        print(f"\n[FATAL] Database error ({exc.__class__.__name__}): {exc}")
        print("Pipeline aborted gracefully.")
        sys.exit(1)


if __name__ == "__main__":
    run()

