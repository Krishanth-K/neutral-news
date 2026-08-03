import psycopg
from db import DATABASE_URL, insert_article, get_pending_articles, update_article_text
from scrape.extract_articles import extract_text_from_url
from scrape.poll_rss import poll_all_feeds


def process_pending_articles(conn, batch_size: int = 50):
    """
    Fetches and processes all pending articles in batches until none remain.
    """
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
                update_article_text(
                    article_id=article_id,
                    error=str(e),
                    status="failed",
                    conn=conn,
                )
                print(f"  ✗ Error extracting {url[:60]}: {e}")

            total_processed += 1

        conn.commit()

    print(f"[SCRAPE] Finished scraping full text for {total_processed} articles.")


def pipeline():
    # 1. Poll RSS feeds from all sources
    feed = poll_all_feeds()
    print(f"[PIPELINE] Fetched {len(feed)} items across all RSS feeds.")

    # 2. Store records and process pending articles
    with psycopg.connect(DATABASE_URL) as conn:
        for record in feed:
            insert_article(record, conn=conn)
        conn.commit()
        print("[PIPELINE] Saved all records to the database.")

        print("[PIPELINE] Scraping full text for pending articles...")
        process_pending_articles(conn)


if __name__ == "__main__":
    pipeline()

     
