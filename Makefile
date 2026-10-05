.PHONY: help db-up db-down tunnel-up tunnel-down up down init-db run embed clear-embed reset-embed clear-embeddings extract extract-quotes group group-full test-rss view-db viz test analyse test-analysis explain explain-force serve ui

SRC = src

# Extract optional positional limit argument (e.g. `make extract 10`, `make view-db 20`)
ifeq ($(filter-out help db-up db-down init-db run test-rss clear-embed reset-embed clear-embeddings,$(firstword $(MAKECMDGOALS))),$(firstword $(MAKECMDGOALS)))
  RUN_ARGS := $(wordlist 2,$(words $(MAKECMDGOALS)),$(MAKECMDGOALS))
  ifneq ($(RUN_ARGS),)
    LIMIT := $(firstword $(RUN_ARGS))
    $(eval $(RUN_ARGS):;@:)
  endif
endif

# Visualisation defaults (override on the command line)
METHOD    ?= umap
OUT       ?= embeddings_map.html
THRESHOLD ?= 0.40

# Default target
help:
	@echo "Available commands:"
	@echo "  make db-up          - Start Postgres (pgvector) container"
	@echo "  make db-down        - Stop Postgres container"
	@echo "  make tunnel-up      - Start Cloudflare tunnel container"
	@echo "  make tunnel-down    - Stop Cloudflare tunnel container"
	@echo "  make up             - Start all services (DB + tunnel)"
	@echo "  make down           - Stop all services"
	@echo "  make init-db        - Initialize Postgres database extensions & schema"
	@echo "  make view-db [N]    - View recent articles in the database (default: 10)"
	@echo "  make run            - Run the full pipeline (ingest → scrape → embed → group)"
	@echo "  make embed [N]      - Run embedding step (optional limit: all or N articles)"
	@echo "  make clear-embed    - Clear article_embeddings table and reset embedding status"
	@echo "  make extract [N]    - Run entity extraction (optional limit: all or N articles)"
	@echo "  make extract-quotes [N] - Run LLM quote extraction (optional limit: all or N articles)"
	@echo "  make group          - Incremental event grouping (new articles only; preserves existing events)"
	@echo "  make group-full     - Full recluster: clear all events and regroup the entire corpus"
	@echo "  make analyse [N]    - Run quote distribution and missing context analysis"
	@echo "  make test           - Run automated unit and integration tests"
	@echo "  make test-rss       - Test RSS polling module"
	@echo "  make viz [N]        - Visualise embeddings in 2D with cluster boundaries (default limit: 500)"
	@echo "    METHOD=umap|tsne    Reduction method for viz (default: umap)"
	@echo "    THRESHOLD=0.40      HAC distance threshold (default: 0.40)"
	@echo "    OUT=file.html       Output filename for viz   (default: embeddings_map.html)"
	@echo "  make viz-dash [N]   - Interactive live Dash app for threshold tuning"
	@echo "  make explain        - Generate LLM explanations for all eligible multi-source events"
	@echo "  make explain-force  - Regenerate LLM explanations even for already-explained events"
	@echo "  make serve          - Start Media Lens web UI server on http://localhost:8000"
	@echo "  make ui             - Alias for make serve"

db-up:
	@echo "Starting PostgreSQL with pgvector on port 5433..."
	@docker start neutral_news_db 2>/dev/null || docker compose up -d db

db-down:
	@echo "Stopping PostgreSQL container..."
	@docker stop neutral_news_db 2>/dev/null || docker compose stop db

tunnel-up:
	@echo "Starting Cloudflare tunnel..."
	@docker compose up -d cloudflared

tunnel-down:
	@echo "Stopping Cloudflare tunnel..."
	@docker compose down cloudflared

up:
	@echo "Starting all services (DB + tunnel)..."
	@docker compose up -d

down:
	@echo "Stopping all services..."
	@docker compose down

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

clear-embed:
	@echo "Clearing embedding table and resetting article embedding status..."
	PYTHONPATH=$(SRC) python3 -m neutral_news.embed.embedder --clear

reset-embed: clear-embed
clear-embeddings: clear-embed


extract:
	@echo "Running entity extraction step$(if $(LIMIT), (limit=$(LIMIT)),)..."
	PYTHONPATH=$(SRC) python3 -c "import psycopg; from neutral_news.config import DATABASE_URL; from neutral_news.extract.entities import extract_named_entities; conn = psycopg.connect(DATABASE_URL); extract_named_entities(conn, limit=$(if $(LIMIT),$(LIMIT),None)); conn.commit(); conn.close()"

extract-quotes:
	@echo "Running quote extraction step$(if $(LIMIT), (limit=$(LIMIT)),)..."
	PYTHONPATH=$(SRC) python3 -c "import psycopg; from neutral_news.config import DATABASE_URL; from neutral_news.extract.quotes import extract_quotes_pipeline; conn = psycopg.connect(DATABASE_URL); extract_quotes_pipeline(conn, limit=$(if $(LIMIT),$(LIMIT),None)); conn.commit(); conn.close()"

group:
	@echo "Running incremental event grouping (threshold=$(THRESHOLD))..."
	PYTHONPATH=$(SRC) python3 -m neutral_news.embed.group_events --threshold $(THRESHOLD)

group-full:
	@echo "Running FULL recluster — clears all events and regroups entire corpus (threshold=$(THRESHOLD))..."
	PYTHONPATH=$(SRC) python3 -m neutral_news.embed.group_events --full --threshold $(THRESHOLD)

analyse:
	@echo "Running quote distribution and missing context analysis..."
	PYTHONPATH=$(SRC) python3 scripts/test_analysis.py $(if $(LIMIT),--limit $(LIMIT),)

test:
	@echo "Running automated unit and integration tests..."
	PYTHONPATH=$(SRC) python3 -m unittest discover -s tests

test-analysis: analyse

test-rss:
	@echo "Testing RSS feed poller..."
	PYTHONPATH=$(SRC) python3 -m neutral_news.ingest.rss

viz:
	@echo "Visualising embeddings (method=$(METHOD), limit=$(or $(LIMIT),500), threshold=$(THRESHOLD), out=$(OUT))..."
	PYTHONPATH=$(SRC) python3 scripts/viz_embeddings.py \
		--limit $(or $(LIMIT),500) \
		--method $(METHOD) \
		--threshold $(THRESHOLD) \
		--out $(OUT)

viz-dash:
	@echo "Starting interactive viz dash server (method=$(METHOD), limit=$(or $(LIMIT),500))..."
	PYTHONPATH=$(SRC) python3 scripts/viz_embeddings.py \
		--limit $(or $(LIMIT),500) \
		--method $(METHOD) \
		--dash

explain:
	@echo "Generating LLM explanations for all eligible multi-source events..."
	PYTHONPATH=$(SRC) python3 -m neutral_news.explain.explain_event

explain-force:
	@echo "Regenerating LLM explanations (force mode)..."
	PYTHONPATH=$(SRC) python3 -m neutral_news.explain.explain_event --force

serve:
	@echo "Starting Media Lens web UI server on http://localhost:8000..."
	PYTHONPATH=$(SRC) uvicorn neutral_news.web.app:app --host 0.0.0.0 --port 8000 --reload

ui: serve

