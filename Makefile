.PHONY: help db-up db-down init-db run embed test-rss view-db viz

SRC = src

# Visualisation defaults (override on the command line)
LIMIT ?= 500
METHOD ?= umap
OUT    ?= embeddings_map.html

# Default target
help:
	@echo "Available commands:"
	@echo "  make db-up          - Start Postgres (pgvector) container using Docker"
	@echo "  make db-down        - Stop and remove Postgres container"
	@echo "  make init-db        - Initialize Postgres database extensions & schema"
	@echo "  make view-db        - View recent articles in the database"
	@echo "  make run            - Run the full pipeline (ingest → scrape → embed)"
	@echo "  make embed          - Run only the embedding step on completed articles"
	@echo "  make test-rss       - Test RSS polling module"
	@echo "  make viz            - Visualise embeddings in 2D (opens embeddings_map.html)"
	@echo "    LIMIT=500           Max articles to fetch (default: 500)"
	@echo "    METHOD=umap|tsne    Reduction method      (default: umap)"
	@echo "    OUT=file.html       Output filename        (default: embeddings_map.html)"

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

embed:
	@echo "Running embedding step..."
	PYTHONPATH=$(SRC) python3 -c "import psycopg; from neutral_news.config import DATABASE_URL; from neutral_news.embed.embedder import embed_pending_articles; conn = psycopg.connect(DATABASE_URL); embed_pending_articles(conn); conn.commit(); conn.close()"

test-rss:
	@echo "Testing RSS feed poller..."
	PYTHONPATH=$(SRC) python3 -m neutral_news.ingest.rss

viz:
	@echo "Visualising embeddings (method=$(METHOD), limit=$(LIMIT), out=$(OUT))..."
	PYTHONPATH=$(SRC) python3 scripts/viz_embeddings.py \
		--limit $(LIMIT) \
		--method $(METHOD) \
		--out $(OUT)
