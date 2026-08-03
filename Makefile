.PHONY: help db-up db-down init-db run test-rss view-db

SRC = src

# Default target
help:
	@echo "Available commands:"
	@echo "  make db-up     - Start Postgres (pgvector) container using Docker"
	@echo "  make db-down   - Stop and remove Postgres container"
	@echo "  make init-db   - Initialize Postgres database extensions & schema"
	@echo "  make view-db   - View recent articles in the database"
	@echo "  make run       - Run the full pipeline (ingest → scrape → embed)"
	@echo "  make test-rss  - Test RSS polling module"

db-up:
	@echo "Starting PostgreSQL with pgvector on port 5433..."
	@docker run -d \
		--name neutral_news_db \
		-e POSTGRES_DB=neutral_news \
		-e POSTGRES_USER=postgres \
		-e POSTGRES_PASSWORD=postgres \
		-p 5433:5432 \
		pgvector/pgvector:pg16 || docker start neutral_news_db

db-down:
	@echo "Stopping PostgreSQL container..."
	@docker stop neutral_news_db || true
	@docker rm neutral_news_db || true

init-db:
	@echo "Initializing database..."
	PYTHONPATH=$(SRC) python3 -m neutral_news.db.schema

view-db:
	@echo "Viewing records in database..."
	PYTHONPATH=$(SRC) python3 -c "from neutral_news.db.articles import view_articles; view_articles(10)"

run:
	@echo "Running pipeline..."
	PYTHONPATH=$(SRC) python3 main.py

test-rss:
	@echo "Testing RSS feed poller..."
	PYTHONPATH=$(SRC) python3 -m neutral_news.ingest.rss
