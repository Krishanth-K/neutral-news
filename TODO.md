# Media Lens — V1 Roadmap & TODO

> **Goal:** A working, demoable end-to-end system that compares how 4 Indian English-language outlets report the same event, using **quote distribution** and **missing context detection** as the single analysis dimension.

---

## Current Status (as of Aug 2026)

| Component | Status | Notes |
|---|---|---|
| RSS Polling | ✅ Done | 3 feeds (The Hindu, Indian Express, ToI) via `ingest/rss.py` |
| DB Schema | ✅ Done | All 6 tables created (`articles`, `article_embeddings`, `quotes`, `events`, `event_articles`, `event_explanations`) |
| Pipeline Skeleton | ✅ Done | `pipeline.py` orchestrates ingest → scrape → embed |
| Full-Text Scraper | ✅ Done | `ingest/scraper.py` using trafilatura; wired into pipeline |
| NLP Extraction | ❌ Not started | — |
| Embedding Generation | 🔨 Scaffolded | `embed/embedder.py` written; needs `sentence-transformers` install & test |
| Event Grouping | ❌ Not started | — |
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

## Phase 2 — Full-Text Scraper Worker

> *Corresponds to diagram box 3 ("Async Scraper Worker"). Currently not implemented.*

### What this does
Picks up articles with `scrape_status = 'pending'`, fetches the full web page, extracts the article body text (stripping nav/ads/boilerplate), and updates the row with `full_text` + `scrape_status = 'completed'`.

### Tasks

- [x] **Choose an article extraction library** → `trafilatura`
- [x] Write `src/neutral_news/ingest/scraper.py`
  - [x] For each article: fetch HTML → extract clean body text via trafilatura
  - [x] `UPDATE articles SET full_text = ..., scraped_at = NOW(), scrape_status = 'completed'`
  - [x] Handle failures: set `scrape_error`, set status to `'failed'`
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

> *Corresponds to diagram box 4 ("Extract"). Not started.*

### What this does
For each `completed` article, extract:
1. **Named entities** (people, organizations, locations) — using spaCy
2. **Quotes with attribution** (quote text, speaker name, speaker role) — using LLM

### Tasks

- [ ] Install spaCy + download English model (`en_core_web_sm` or `en_core_web_trf` for better accuracy)
- [ ] Write `src/neutral_news/extract/entities.py`
  - [ ] Load article full text → run spaCy NER → return list of `(entity_text, entity_label)`
  - [ ] Store extracted entities (decide: new `entities` table, or JSONB column on `articles`)
- [ ] Write `src/neutral_news/extract/quotes.py`
  - [ ] Design LLM prompt: given article text, extract structured JSON of `{quote_text, speaker, role}`
  - [ ] Define abstract LLM interface (so you can swap providers later)
  - [ ] Insert results into `quotes` table
- [ ] Add `make extract` target to Makefile
- [ ] Wire into `pipeline.py` after scraping
- [ ] Test: verify extracted entities and quotes look correct for sample articles

> **Note:** The `quotes` table already exists in the schema (`quote_text`, `speaker`, `role`). An `entities` table does **not** exist yet — you'll need to either add one or use a JSONB column.

---

## Phase 4 — Embedding Generation & Event Grouping

> *Corresponds to diagram box 5 ("Embed & Group"). Not started.*

### What this does
1. Generate a semantic embedding for each article (headline + body text)
2. Cluster articles about the same real-world event using embedding similarity + time-window constraints
3. Store the clusters as `events` with linked `event_articles`

### Tasks

- [ ] Install `sentence-transformers`
- [x] Write `src/neutral_news/embed/embedder.py`
  - [x] Load `all-MiniLM-L6-v2` model (384-dim — matches `vector(384)` in DB schema)
  - [x] For each `completed` article without an embedding: generate embedding
  - [x] Insert into `article_embeddings` table; skip if already exists
  - [x] Wire into `pipeline.py` as stage 4
- [ ] Test: run pipeline end-to-end; verify `article_embeddings` rows are populated
- [ ] Write `src/neutral_news/embed/group_events.py`
  - [ ] Fetch all embeddings from `article_embeddings`
  - [ ] Cluster using cosine similarity threshold + published_at time window (e.g. 48 hours)
  - [ ] Algorithm options: agglomerative clustering, or simple pairwise threshold with union-find
  - [ ] Create `events` rows with a generated title (e.g. most common headline in cluster)
  - [ ] Insert `event_articles` mappings
  - [ ] Handle incremental updates: new articles may join existing events
- [ ] Add `make embed` and `make group` targets to Makefile
- [ ] Test: verify that articles about the same story cluster together across sources

> **Important:** The event grouping doesn't need to be perfect for V1. A simple cosine similarity threshold (e.g. > 0.7) within a 48-hour window is "good enough" to group 4 articles about the same story. Iterate on accuracy later.

---

## Phase 5 — Analysis (Quote Distribution + Missing Context)

> *Corresponds to diagram box 6 ("Analyze"). Not started. This is the core V1 analysis dimension.*

### What this does
For each event (group of articles), compute:
1. **Quote distribution:** For each article, count quotes by speaker role (government / opposition / expert / citizen / etc.). Show which voices each source amplifies or ignores.
2. **Missing context:** Entities or key facts mentioned by ≥ N-1 sources but absent from a specific source. ("Mentioned by 3 of 4 sources, missing from X.")

### Tasks

- [ ] Write `src/neutral_news/analyze/quote_distribution.py`
  - [ ] For a given `event_id`, fetch all `quotes` for each article in the event
  - [ ] Aggregate by `role`: count per article per role
  - [ ] Output: `{article_id: {govt: 3, opposition: 1, expert: 2, citizen: 0}, ...}`
- [ ] Write `src/neutral_news/analyze/missing_context.py`
  - [ ] For a given `event_id`, fetch entities for each article in the event
  - [ ] Find entities present in ≥ 3 of 4 articles but absent from ≤ 1 article
  - [ ] Output: `[{entity: "Supreme Court", present_in: ["Hindu", "IE", "NDTV"], missing_from: ["ToI"]}, ...]`
- [ ] Write `src/neutral_news/analyze/analyze_event.py` (orchestrator)
  - [ ] Calls both analysis functions for a given event
  - [ ] Returns combined structured evidence
- [ ] Add `make analyze` target to Makefile
- [ ] Wire into `pipeline.py`
- [ ] Test: verify analysis output makes intuitive sense for sample events

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
| Article extraction library | `trafilatura` (recommended), `newspaper4k`, `readability-lxml`, `beautifulsoup4` | ⏳ Decide in Phase 2 |
| Entities storage | New `entities` table vs JSONB column on `articles` | ⏳ Decide in Phase 3 |
| Event clustering algorithm | Agglomerative clustering vs pairwise threshold + union-find | ⏳ Decide in Phase 4 |
| LLM provider | Gemini / OpenAI / Ollama | ⏳ Decide in Phase 6 |
| Frontend tech | FastAPI + Jinja2 templates, React/Next.js, or plain HTML/JS | ⏳ Decide in Phase 7 |

---

## Dependency Summary

```
Phase 1 (RSS Ingest) ✅
    ↓
Phase 2 (Full-Text Scraper) ← CURRENT PRIORITY
    ↓
Phase 3 (NLP Extraction)  ─── requires Phase 2 output (full_text)
    ↓                          ⎤
Phase 4 (Embed & Group)   ─── requires Phase 2 output (full_text)
    ↓                          ⎦ Can be built in parallel
Phase 5 (Analysis)         ─── requires Phase 3 (quotes/entities) + Phase 4 (events)
    ↓
Phase 6 (LLM Explanation)  ─── requires Phase 5 (structured evidence)
    ↓
Phase 7 (API & Frontend)   ─── requires Phase 6 (explanations)
    ↓
Phase 8 (Polish & Demo)    ─── requires everything above
```

> **Phase 3 and Phase 4 can be built in parallel** since they both depend only on Phase 2 output. Embedding generation and NLP extraction are independent of each other.
