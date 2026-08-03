# Media Lens

> An explainable news comparison platform — not a bias score, an evidence explorer.

Media Lens ingests articles about the same event from multiple Indian English-language newspapers and exposes **how** each outlet covers it differently. Instead of outputting an opaque "bias percentage", the system surfaces structured, verifiable evidence: who gets quoted, whose voices are absent, and which facts a source omits that every other source reports.

---

## The Problem

Most readers consume news from a single outlet. Every newspaper has an editorial perspective, a set of voices it amplifies, and facts it chooses to emphasise or ignore. Traditional "bias detectors" collapse this nuance into a single score — which is itself an editorial judgment, and an unverifiable one.

Media Lens takes a different approach:

> **"How is the same event being portrayed across different newspapers?"**

This shifts the tool from *verdict* to *evidence*.

---

## V1 Scope

V1 is a deliberately narrow end-to-end pipeline — demoable and honest, not wide and incomplete.

| Dimension | V1 Decision |
|---|---|
| Sources | 3 English-language Indian outlets — The Hindu, Indian Express, Times of India |
| Collection | RSS feeds only (no Playwright, no paywall handling) |
| Event matching | Semantic embedding similarity + 48-hour time window |
| Analysis | **Quote distribution** + **Missing context detection** only |
| Explanation | LLM narrates pre-computed structured evidence — not a raw LLM call |
| Frontend | Side-by-side comparison view + evidence panel |

Everything beyond this scope is documented in [`IDEA.md`](IDEA.md) as the long-term roadmap.

---

## Pipeline Status

| Phase | Component | Status | Notes |
|---|---|---|---|
| 1 | RSS Ingest & Parse | ✅ Done | `ingest/rss.py` — The Hindu, Indian Express, ToI |
| 1 | DB Schema | ✅ Done | 6 tables: `articles`, `article_embeddings`, `quotes`, `events`, `event_articles`, `event_explanations` |
| 1 | Pipeline Skeleton | ✅ Done | `pipeline.py` polls RSS → inserts into DB |
| 2 | Full-Text Scraper | ✅ Done | `ingest/scraper.py` — trafilatura; wired into pipeline |
| 3 | NLP Extraction | 📋 Planned | spaCy NER + LLM quote extraction |
| 4 | Embedding Generation | 🔨 In progress | `embed/embedder.py` scaffolded; needs `sentence-transformers` install |
| 4 | Event Grouping | 📋 Planned | Cosine similarity + time-window clustering |
| 5 | Analysis | 📋 Planned | Quote distribution + missing context per event |
| 6 | LLM Explanation | 📋 Planned | LLM narrates structured evidence |
| 7 | API & Frontend | 📋 Planned | FastAPI + comparison UI |

---

## Documentation

| Document | Description |
|---|---|
| [`docs/data_flow.md`](docs/data_flow.md) | Full system data flow with Mermaid diagram and data movement table |
| [`IDEA.md`](IDEA.md) | Long-term vision, all analysis dimensions, technical challenges |
| [`TODO.md`](TODO.md) | Phase-by-phase task breakdown, open decisions, dependency graph |

---

## Quick Start

### Prerequisites

- Python ≥ 3.12
- Docker (for the PostgreSQL + pgvector container)
- `uv` or `pip` for Python dependencies

### 1. Start the database

```bash
make db-up       # spins up pgvector/pgvector:pg16 on port 5433
make init-db     # creates extensions (uuid-ossp, vector) + all 6 tables
```

### 2. Install Python dependencies

```bash
pip install -r requirements.txt
# or: uv pip install -r requirements.txt
```

### 3. Run the pipeline

```bash
make run         # polls all RSS feeds → inserts metadata → scrapes full text
```

### 4. Inspect the database

```bash
make view-db     # prints the 10 most recent articles and their scrape status
```

### 5. Test individual modules

```bash
make test-rss    # runs ingest/rss.py standalone and prints a sample article record
```

---

## Make Targets

```
make help        # list all available targets
make db-up       # start Postgres (pgvector) container
make db-down     # stop and remove Postgres container
make init-db     # initialize extensions and schema
make run         # run the full pipeline
make test-rss    # test the RSS polling module
make view-db     # inspect recent articles in the database
```

---

## Tech Stack

| Concern | Choice |
|---|---|
| Language | Python 3.12 |
| Database | PostgreSQL 16 via Docker (`pgvector/pgvector:pg16`) |
| Vector storage | pgvector extension — `vector(384)` column on `article_embeddings` |
| RSS parsing | `feedparser` + `httpx` |
| Article extraction | `trafilatura` |
| NLP | `spaCy` — NER; LLM — quote attribution |
| Embeddings | `sentence-transformers` — `all-MiniLM-L6-v2` (384-dim, pgvector) |
| API | FastAPI (planned) |
| Containerisation | Docker |

---

## Project Structure

```
neutral-news/
├── main.py                     # Thin entry point — calls pipeline.run()
├── src/
│   └── neutral_news/           # Main package
│       ├── config.py           # DATABASE_URL and environment variables
│       ├── pipeline.py         # Orchestrator: ingest → scrape → embed
│       ├── db/
│       │   ├── schema.py       # SCHEMA_SQL + init_db()
│       │   └── articles.py     # CRUD: insert, query, update articles
│       ├── ingest/
│       │   ├── rss.py          # RSS fetching and parsing
│       │   └── scraper.py      # Article body extraction (trafilatura)
│       └── embed/
│           └── embedder.py     # Embedding generation + pgvector storage
│
├── docs/
│   ├── data_flow.md            # System data flow documentation
│   ├── data_flow_diagram.png   # Visual data flow diagram
│   └── architecture_diagram.png
│
├── Makefile                    # All dev commands
├── IDEA.md                     # Long-term vision & roadmap
├── TODO.md                     # Phase-by-phase task tracker
├── pyrightconfig.json
└── .python-version
```

---

## Database Schema

Six tables back the full pipeline. The `articles` table is the central staging area; all downstream tables reference it by UUID.

```
articles               — raw RSS metadata + scraped full text + status queue
article_embeddings     — 384-dim semantic embedding per article
quotes                 — extracted (quote_text, speaker, role) per article
events                 — clustered groups of articles covering the same story
event_articles         — many-to-many: event ↔ article
event_explanations     — LLM-generated narrative + structured evidence JSONB
```

The `scrape_status` lifecycle per article row:

```
pending → processing → completed
                    ↘ failed
```

---

## What "Explainable" Means Here

The system will never output:

> *"This article is 73% biased."*

Instead, it outputs structured evidence the user can evaluate themselves:

```
Source: Times of India
─────────────────────────────────────
Quote distribution
  Government officials    6
  Opposition leaders      0
  Independent experts     1
  Citizens / witnesses    0

Missing context (mentioned by 3 of 4 sources, absent here)
  · Supreme Court ruling on MSP guarantee
  · Statement from farmers' union leadership
```

The LLM explanation layer narrates this evidence in plain language — it does not generate the underlying numbers.

---

## Author

Krishanth — 3rd year CSE, Amrita Vishwa Vidyapeetham.
