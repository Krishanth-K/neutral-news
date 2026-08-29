.PHONY: help db-up db-down init-db run embed extract test-rss view-db viz

SRC = src

# Extract optional positional limit argument (e.g. `make extract 10`, `make view-db 20`)
ifeq ($(filter-out help db-up db-down init-db run test-rss,$(firstword $(MAKECMDGOALS))),$(firstword $(MAKECMDGOALS)))
  RUN_ARGS := $(wordlist 2,$(words $(MAKECMDGOALS)),$(MAKECMDGOALS))
  ifneq ($(RUN_ARGS),)
    LIMIT := $(firstword $(RUN_ARGS))
    $(eval $(RUN_ARGS):;@:)
  endif
endif

# Visualisation defaults (override on the command line)
METHOD ?= umap
OUT    ?= embeddings_map.html

# Default target
help:
	@echo "Available commands:"
	@echo "  make db-up          - Start Postgres (pgvector) container using Docker"
	@echo "  make db-down        - Stop and remove Postgres container"
	@echo "  make init-db        - Initialize Postgres database extensions & schema"
	@echo "  make view-db [N]    - View recent articles in the database (default: 10)"
	@echo "  make run            - Run the full pipeline (ingest → scrape → embed)"
	@echo "  make embed [N]      - Run embedding step (optional limit: all or N articles)"
	@echo "  make extract [N]    - Run entity extraction (optional limit: all or N articles)"
	@echo "  make test-rss       - Test RSS polling module"
	@echo "  make viz [N]        - Visualise embeddings in 2D (opens embeddings_map.html, default limit: 500)"
	@echo "    METHOD=umap|tsne    Reduction method for viz (default: umap)"
	@echo "    OUT=file.html       Output filename for viz   (default: embeddings_map.html)"

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
	@echo "Viewing records in database (limit=$(or $(LIMIT),10))..."
	PYTHONPATH=$(SRC) python3 -c "from neutral_news.db.articles import view_articles; view_articles(limit=$(or $(LIMIT),10))"

run:
	@echo "Running pipeline..."
	PYTHONPATH=$(SRC) python3 main.py

embed:
	@echo "Running embedding step$(if $(LIMIT), (limit=$(LIMIT)),)..."
	PYTHONPATH=$(SRC) python3 -c "import psycopg; from neutral_news.config import DATABASE_URL; from neutral_news.embed.embedder import embed_pending_articles; conn = psycopg.connect(DATABASE_URL); embed_pending_articles(conn, limit=$(if $(LIMIT),$(LIMIT),None)); conn.commit(); conn.close()"

extract:
	@echo "Running entity extraction step$(if $(LIMIT), (limit=$(LIMIT)),)..."
	PYTHONPATH=$(SRC) python3 -c "import psycopg; from neutral_news.config import DATABASE_URL; from neutral_news.extract.entities import extract_named_entities; conn = psycopg.connect(DATABASE_URL); extract_named_entities(conn, limit=$(if $(LIMIT),$(LIMIT),None)); conn.commit(); conn.close()"

test-rss:
	@echo "Testing RSS feed poller..."
	PYTHONPATH=$(SRC) python3 -m neutral_news.ingest.rss

viz:
	@echo "Visualising embeddings (method=$(METHOD), limit=$(or $(LIMIT),500), out=$(OUT))..."
	PYTHONPATH=$(SRC) python3 scripts/viz_embeddings.py \
		--limit $(or $(LIMIT),500) \
		--method $(METHOD) \
		--out $(OUT)
