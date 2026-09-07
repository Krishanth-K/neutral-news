# Media Lens — V1 Roadmap & TODO

> **Goal:** A working, demoable end-to-end system that compares how 4 Indian English-language outlets report the same event, using **quote distribution** and **missing context detection** as the single analysis dimension.

---

## Current Status (as of Sep 2026)

| Component | Status | Notes |
|---|---|---|
| RSS Polling | ✅ Done | 3 feeds (The Hindu, Indian Express, ToI) via `ingest/rss.py` |
| DB Schema | ✅ Done | All 7 tables created (`articles`, `article_embeddings` [768-dim], `quotes`, `entities`, `events`, `event_articles`, `event_explanations`) |
| Pipeline Skeleton | ✅ Done | `pipeline.py` orchestrates ingest → scrape → embed |
| Full-Text Scraper | ✅ Done | `ingest/scraper.py` using domain extractors + trafilatura fallback; duplicate handling |
| NLP Extraction | 🔨 In progress | spaCy NER completed via `extract/entities.py` (`make extract`); LLM quote extraction pending |
| Embedding Generation | ✅ Done | `embed/embedder.py` with `nomic-embed-text-v1.5` (768-dim, task prefixes); wired into pipeline |
| Event Grouping | 🔨 In progress | Distance matrix (`embed/distance.py`) & HAC (`embed/cluster.py`) implemented; DB persistence & event titling pending |
| Analysis | ❌ Not started | — |
| LLM Explanation | ❌ Not started | — |
| API / Frontend | ❌ Not started | — |

---

## Phase 1 — RSS Ingest & Parse ✅

> *Corresponds to diagram box 1. Already working.*

- [x] Configure RSS feed URLs (`ingest/rss.py`)
- [x] Fetch + parse RSS XML via `httpx` + `feedparser`
- [x] Standardise output to `{headline, article_url, published_at, source_name}`
- [x] Insert into `articles` table with `ON CONFLICT DO NOTHING`
- [x] Makefile targets: `make run`, `make test-rss`, `make view-db`

**No remaining work.** Move on.

---

## Phase 2 — Full-Text Scraper Worker ✅

> *Corresponds to diagram box 3 ("Async Scraper Worker"). Already working.*

### What this does
Picks up articles with `scrape_status = 'pending'`, fetches the full web page, extracts the article body text (stripping nav/ads/boilerplate), and updates the row with `full_text` + `scrape_status = 'completed'`.

### Tasks

- [x] **Choose an article extraction library** → `trafilatura` + custom domain extractors
- [x] Write `src/neutral_news/ingest/scraper.py`
  - [x] For each article: fetch HTML → extract clean body text via domain extractors or trafilatura fallback
  - [x] `UPDATE articles SET full_text = ..., scraped_at = NOW(), scrape_status = 'completed'`
  - [x] Handle failures: set `scrape_error`, set status to `'failed'`
  - [x] Handle duplicate `full_text` gracefully using savepoints and unique hash index
- [x] Wire into `pipeline.py` after RSS ingest
- [x] Manually verify: run pipeline end-to-end, check `view-db` shows `completed` articles with full text

### Article Extraction Library Decision

You need a library that takes raw HTML and returns just the article body text (no nav bars, ads, sidebars, etc.). Here are the options:

| Library | Approach | Pros | Cons | Best For |
|---|---|---|---|---|
| **`trafilatura`** | Heuristic + ML hybrid; purpose-built for web article extraction | Best accuracy on news articles in benchmarks; handles metadata (author, date) too; fast; actively maintained | Slightly heavier install; opinionated output format | **This project** — news-specific, high accuracy out of the box |
| **`newspaper3k` / `newspaper4k`** | Heuristic (text density + DOM structure) | Popular, simple API (`Article.parse()`); extracts authors, images too | Original `newspaper3k` is unmaintained; `newspaper4k` fork is newer but less battle-tested | Quick prototypes, well-known sites |
| **`readability-lxml`** | Port of Mozilla's Readability (used in Firefox Reader View) | Very fast; good for clean article pages | Returns HTML not plain text (needs extra step); struggles with complex layouts | When you want the "reader mode" approach |
| **`beautifulsoup4`** + custom selectors | Manual CSS/XPath selectors per source | Full control; most precise | Massive maintenance burden; breaks when sites change HTML | Only if other libs fail on specific sites |

**Recommendation: Use `trafilatura`.** It's the most accurate for news article extraction, handles Indian news sites well, and requires zero per-site configuration. If a specific outlet's extraction is poor, you can always add a `beautifulsoup4` fallback for just that source.

---

## Phase 3 — NLP Extraction (Entities + Quotes)

> *Corresponds to diagram box 4 ("Extract"). In progress.*

### What this does
For each `completed` article, extract:
1. **Named entities** (people, organizations, locations, laws, etc.) — using spaCy
2. **Quotes with attribution** (quote text, speaker name, speaker role) — using LLM

### Tasks

- [x] Install spaCy + download English transformer model (`en_core_web_trf`)
- [x] Write `src/neutral_news/extract/entities.py`
  - [x] Load article full text → run spaCy NER on relevant labels (`PERSON`, `ORG`, `GPE`, `LOC`, `EVENT`, `LAW`, `NORP`)
  - [x] Store extracted entities in dedicated `entities` table (`article_id`, `text`, `label`)
  - [x] Manage `entity_extraction_status` on `articles`
- [x] Add `make extract [N]` target to Makefile
- [x] Wire entity extraction into `pipeline.py` after scraping
- [ ] Write `src/neutral_news/extract/quotes.py`
  - [ ] Design LLM prompt: given article text, extract structured JSON of `{quote_text, speaker, role}`
  - [ ] Define abstract LLM interface (so you can swap providers later)
  - [ ] Insert results into `quotes` table
- [ ] Add `make extract-quotes` target to Makefile
- [ ] Test: verify extracted entities and quotes look correct for sample articles

> **Note:** Both `quotes` (`quote_text`, `speaker`, `role`) and `entities` (`article_id`, `text`, `label`) tables already exist in the database schema.

---

## Phase 4 — Embedding Generation & Event Grouping

> *Corresponds to diagram box 5 ("Embed & Group"). In progress.*

### What this does
1. Generate semantic embeddings for each article (`nomic-embed-text-v1.5`, 768-dim)
2. Compute composite pairwise distance matrix (semantic similarity + time window + entity Jaccard)
3. Cluster articles about the same real-world event using Hierarchical Agglomerative Clustering (HAC)
4. Store the clusters as `events` with linked `event_articles` and cluster medoids

### Tasks

- [x] Install `sentence-transformers` & dependencies
- [x] Write `src/neutral_news/embed/embedder.py`
  - [x] Load `nomic-ai/nomic-embed-text-v1.5` model (768-dim — matches `vector(768)` in DB schema)
  - [x] Apply task prefix (`search_document: `)
  - [x] For each `completed` article without an embedding: generate embedding
  - [x] Insert into `article_embeddings` table; skip if already exists
  - [x] Wire into `pipeline.py` as stage 4
  - [x] Add `make embed [N]` target to Makefile
- [x] Test: run pipeline end-to-end; verify `article_embeddings` rows are populated
- [x] Write `src/neutral_news/embed/distance.py`
  - [x] Compute composite pairwise distance matrix ($0.55 \cdot \text{embedding} + 0.25 \cdot \text{time} + 0.20 \cdot \text{entity}$)
  - [x] Test pairwise distance on article pairs (`scripts/test_distance_matrix.py`)
- [x] Write `src/neutral_news/embed/cluster.py`
  - [x] Implement Hierarchical Agglomerative Clustering (HAC) with complete/average linkage
  - [x] Compute cluster medoid for representative article selection
- [x] Build 2D embedding space visualization & tuning tools
  - [x] UMAP / t-SNE reduction with cluster boundary polygons (`scripts/viz_embeddings.py`, `make viz`)
  - [x] Interactive Dash app with live threshold slider (`make viz-dash`)
- [x] Write event persistence logic (`src/neutral_news/embed/group_events.py` or `persist_events()`)
  - [x] Create `events` rows with generated titles (e.g. from cluster medoid headline)
  - [x] Insert `event_articles` mappings
  - [ ] Handle incremental updates: new articles joining existing events
- [x] Add `make group` target to Makefile and wire into `pipeline.py`
- [ ] Address edge cases in distance metric (non-linear time scaling, dynamic windows per `docs/problems.md`)
- [ ] Test: verify that articles about the same story cluster together across sources

> **Design Choice:** We use Hierarchical Agglomerative Clustering (HAC) with complete linkage to eliminate the chaining flaw of graph methods and the order-dependency flaw of single-pass clustering. A composite distance metric combines semantic similarity (55%), publication time delta (25%), and spaCy entity Jaccard overlap (20%). See `docs/clustering.md`.

---

## Phase 5 — Analysis (Quote Distribution + Missing Context)

> *Corresponds to diagram box 6 ("Analyze"). Not started. This is the core V1 analysis dimension.*

### What this does
For each event (group of articles), compute:
1. **Quote distribution:** For each article, count quotes by speaker role (government / opposition / expert / citizen / etc.). Show which voices each source amplifies or ignores.
2. **Missing context:** Entities or key facts mentioned by ≥ N-1 sources but absent from a specific source. ("Mentioned by 3 of 4 sources, missing from X.")

### Tasks

- [x] Write quote distribution analysis in `src/neutral_news/analyse/analysis.py`
  - [x] For a given `event_id`, fetch all `quotes` for each article in the event
  - [x] Aggregate by `role`: count per source/article per role
  - [x] Output: `{event_id, sources_analyzed, by_source: {total_quotes, counts, proportions, dominant_role, omitted_roles, quotes}}`
- [x] Write missing context analysis in `src/neutral_news/analyse/analysis.py`
  - [x] For a given `event_id`, fetch entities for each article/source in the event
  - [x] Universal entity set union and per-source set difference calculation
  - [x] Output: `{event_id, sources_analyzed, universal_entity_count, missing_by_source: {present_count, missing_count, missing_entities, present_entities}}`
- [x] Write combined orchestrator `analyse_event()` in `src/neutral_news/analyse/analysis.py`
- [x] Add `make analyse` target to Makefile
- [ ] Wire analysis into `pipeline.py` / Phase 6 (LLM explanation layer)
- [x] Test: `scripts/test_analysis.py` for verifying structured analysis evidence


---

## Phase 6 — LLM Explanation Layer

> *Corresponds to diagram box 7 ("Explain"). Not started.*

### What this does
Takes the **structured evidence** (quote counts, missing entity lists) and generates a human-readable explanation. The LLM is NOT doing the analysis — it's just narrating pre-computed evidence.

### Tasks

- [ ] Write `src/neutral_news/explain/llm_interface.py`
  - [ ] Abstract interface: `explain(evidence: dict) -> str`
  - [ ] Implement concrete adapter (Gemini / OpenAI / Ollama — decide later)
  - [ ] Prompt design: given quote distribution counts + missing context list, produce a clear, neutral narrative
- [ ] Write `src/neutral_news/explain/explain_event.py`
  - [ ] For a given `event_id`, fetch analysis results
  - [ ] Call LLM interface to generate explanation
  - [ ] Store result in `event_explanations` table (with `evidence` JSONB column)
- [ ] Add `make explain` target to Makefile
- [ ] Wire into `pipeline.py`
- [ ] Test: verify explanations are accurate and backed by evidence

> **Note:** LLM provider decision deferred. Design the interface now so any provider can be swapped in. The prompt is more important than the provider for V1.

---

## Phase 7 — API & Frontend

> *Corresponds to the "Frontend" node in the diagram. Not started. Decision deferred to after backend is working.*

### What this does
Expose the data via a FastAPI REST API. Build a frontend that shows side-by-side article comparison with an evidence panel.

### Tasks

- [ ] Write `src/neutral_news/api/app.py` (FastAPI)
  - [ ] `GET /events` — list all events with metadata
  - [ ] `GET /events/{event_id}` — event detail: articles, quote distribution, missing context, explanation
  - [ ] `GET /articles/{article_id}` — single article detail
- [ ] Build frontend (tech TBD)
  - [ ] Event list page: browse recent events
  - [ ] Event comparison page:
    - [ ] Side-by-side article cards (headline, source, snippet)
    - [ ] Quote distribution chart per article
    - [ ] Missing context panel ("mentioned by X, missing from Y")
    - [ ] LLM-generated explanation section
- [ ] Add `make serve` target to Makefile

---

## Phase 8 — Integration, Polish & Demo Readiness

### Tasks

- [ ] End-to-end test: `make run` polls → scrapes → extracts → embeds → groups → analyzes → explains
- [ ] Error handling & logging throughout the pipeline
- [ ] Add proper `.env` file for configuration (DB URL, LLM API keys, etc.)
- [ ] Update `.gitignore` (add `.env`, `venv/`, etc.)
- [ ] Write `README.md` with:
  - [ ] Project description & motivation
  - [ ] Architecture diagram
  - [ ] Setup instructions (Docker, Python deps, env vars)
  - [ ] Usage / demo walkthrough
- [ ] Record a demo GIF/video for the README

---

## Open Decisions

| Decision | Options | Status |
|---|---|---|
| Article extraction library | `trafilatura` (recommended), `newspaper4k`, `readability-lxml`, `beautifulsoup4` | ✅ Decided: `trafilatura` + custom domain extractors |
| Entities storage | New `entities` table vs JSONB column on `articles` | ✅ Decided: Dedicated `entities` table |
| Event clustering algorithm | Agglomerative clustering vs pairwise threshold + union-find | ✅ Decided: HAC (complete linkage) on multi-factor distance matrix |
| LLM provider | Gemini / OpenAI / Ollama | ⏳ Decide in Phase 6 |
| Frontend tech | FastAPI + Jinja2 templates, React/Next.js, or plain HTML/JS | ⏳ Decide in Phase 7 |

---

## Dependency Summary

```
Phase 1 (RSS Ingest) ✅
    ↓
Phase 2 (Full-Text Scraper) ✅
    ↓
Phase 3 (NLP Extraction)  ─── spaCy NER ✅ / LLM Quotes ⏳    ← CURRENT PRIORITY
    ↓                                                            ⎤
Phase 4 (Embed & Group)   ─── Embeddings ✅ / HAC ✅ / DB Persist ⏳  ← CURRENT PRIORITY
    ↓                                                            ⎦
Phase 5 (Analysis)         ─── requires Phase 3 (quotes/entities) + Phase 4 (events)
    ↓
Phase 6 (LLM Explanation)  ─── requires Phase 5 (structured evidence)
    ↓
Phase 7 (API & Frontend)   ─── requires Phase 6 (explanations)
    ↓
Phase 8 (Polish & Demo)    ─── requires everything above
```

> **Phase 3 (LLM quote extraction) and Phase 4 (event DB persistence & pipeline wiring) can be completed in parallel.** Embedding generation, spaCy entity extraction, distance calculation, and HAC clustering algorithms are already built.
