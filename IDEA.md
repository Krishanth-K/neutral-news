# Project: Media Lens

### An Explainable Multilingual News Comparison Platform

## Vision

Most people consume news from only one source. Every newspaper has its own editorial perspective, political leaning, and choice of what information to emphasize or omit. Instead of telling users *which source is correct*, this platform exposes how different newspapers report the same event, allowing readers to make informed decisions themselves.

The goal is **not** to classify an article as "left" or "right."

The goal is to answer:

> **"How is the same event being portrayed across different newspapers?"**

This shifts the application from being a "bias detector" to becoming an **evidence explorer**.

---

# V1 Scope (Actual Build Plan)

Everything below this section (Core Features onward) describes the **full long-term vision**. It is intentionally broad and stays in this doc as the roadmap / "where this is going" story for interviews and the README.

**V1 is a deliberately narrow slice of that vision, scoped to be buildable solo in 2-4 weeks.** The goal of v1 is a working, demoable end-to-end system — not partial coverage of every feature below.

### V1 Constraints (cut from the full vision, on purpose)

* **Sources:** 4 English-language Indian outlets only (e.g. The Hindu, Indian Express, Times of India). No Tamil/Hindi/regional sources yet — cross-lingual comparison is a v2+ extension, not v1.
* **Collection:** RSS feeds only, no Playwright/custom scraping, no paywall handling. Avoids the highest-grind, lowest-signal work.
* **Event matching:** basic — headline/entity/time-window similarity via embeddings. Doesn't need to be perfect, just good enough to group 4 articles about the same story.
* **Analysis dimension:** pick ONE to build well instead of five shallow ones —
  **Quote Distribution + Missing Context Detection.**
  * Quote distribution: who's quoted (govt / opposition / experts / citizens) and in what proportion, extracted per article.
  * Missing context: facts/entities present in most articles but absent from a specific one, surfaced as explicit evidence ("mentioned by 3 of 4 sources, missing from X").
* **Explanation layer:** LLM is used only to generate the final human-readable explanation from structured evidence (counts, missing-entity lists) — not to do the underlying extraction. This preserves the "not just an LLM wrapper" claim, but only for this one dimension, honestly.
* **Frontend:** simple side-by-side comparison view + evidence panel. No timeline, no heatmap, no chat interface yet.

### Explicitly NOT in v1 (deferred to the full-vision roadmap below)

* Multilingual / cross-lingual comparison
* Sentiment & emotional framing detection
* Headline framing analysis
* Focus/topic classification (government, economy, religion, etc.)
* Timeline view, bias history, regional coverage, AI chat
* Vector DB / Qdrant / Milvus infra — a simple Postgres table is enough at this scale
* Custom crawlers, paywall handling

### Why this scope

A working 4-source, single-dimension demo is something you can actually walk someone through end to end — search a real event, show the comparison, show the evidence behind it. That's a stronger resume/interview artifact than an unfinished pipeline that nominally covers everything below but doesn't run. The full vision stays written down as the roadmap; it's not abandoned, just sequenced.

---

# Core Features

## 1. Event Aggregation

Given either:

* a news article
* a headline
* a search query

the system gathers articles about the same event from multiple newspapers.

Example:

```
Search:
"Farmers Protest"
↓
Articles from

- Dinamalar
- The Hindu
- Indian Express
- Times of India
- NDTV
- Deccan Herald
- etc.
```

---

## 2. Event Comparison

Instead of showing articles independently, compare them side-by-side.

For every event:

### Common Facts

Facts reported by nearly every newspaper.

Example:

* Protest occurred
* Bill introduced
* Police deployed

---

### Unique Information

Information only mentioned by specific newspapers.

Example:

Only Newspaper A mentions:
* Supreme Court response

Only Newspaper B mentions:
* Farmer union statement

Only Newspaper C mentions:
* Economic projections

---

## 3. Narrative Analysis

Rather than assigning arbitrary political labels, identify measurable editorial differences.

Possible dimensions:

### Focus

Government

Opposition

Economy

Religion

Law

International

Civil Rights

Public Opinion

---

### Emotional Framing

Identify emotionally loaded language.

Example:

Positive framing

* Historic
* Successful
* Landmark

Negative framing

* Controversial
* Violent
* Failed
* Chaotic

---

### Quote Distribution

Who gets quoted?

Government Officials

Opposition Leaders

Experts

Academics

Police

Witnesses

NGOs

Citizens

Example:

```
Government
65%

Opposition
15%

Experts
10%

Citizens
10%
```

---

### Source Diversity

How many independent viewpoints does each article include?

---

### Headline Framing

Compare headlines covering the same event.

Example:

```
Government Passes Historic Reform

vs

Controversial Bill Sparks Nationwide Protest
```

Same event.

Completely different framing.

---

### Missing Context

Identify important facts mentioned by several newspapers but omitted by others.

Example:

"This article does not mention the Supreme Court ruling discussed by four other publications."

---

# Explainability

The system should **never** output:

> "This article is 82% biased."

Instead it should provide evidence.

Example:

```
Government quoted:
6

Opposition quoted:
0

Experts quoted:
1

Emotionally loaded words:
27

Missing topics:
- Supreme Court response
- Police statement
```

The user should be able to understand **why** a particular narrative appears the way it does.

---

# Technical Pipeline

```
News Sources

↓

Crawler

↓

Article Extraction

↓

Language Detection

↓

Translation (if required)

↓

Cleaning

↓

Embedding Generation

↓

Vector Database

↓

Event Clustering

↓

Cross-document Analysis

↓

LLM Explanation Layer

↓

Frontend
```

---

# Major Technical Challenges

## 1. News Collection

Collect articles from multiple Indian newspapers.

Challenges:

* Different HTML structures
* Dynamic websites
* Paywalls
* Rate limits
* Multiple languages

---

## 2. Event Detection

Determine whether different articles discuss the same event.

Possible signals:

* Semantic embeddings
* Named entities
* Publication time
* Headline similarity
* Geographic location

---

## 3. Cross-Lingual Understanding

Compare reports across Indian languages.

Examples:

Tamil

Hindi

Malayalam

Kannada

English

Marathi

Gujarati

All describing the same event.

This requires multilingual embeddings or translation before comparison.

---

## 4. Narrative Extraction

Automatically identify:

* recurring themes
* emphasis
* omissions
* quoted sources
* sentiment
* framing

without relying solely on LLM prompting.

---

# Possible Technology Stack

## Backend

* Python
* FastAPI

---

## NLP

* spaCy
* sentence-transformers
* HuggingFace Transformers

---

## Databases

Relational Database

* PostgreSQL

Vector Database

* Qdrant
* Milvus

---

## Crawling

* Playwright
* Newspaper RSS feeds
* Custom scrapers

---

## Frontend

Lightweight HTML/CSS interface with JavaScript.

---

## Deployment

* Docker
* Linux VPS
* Nginx

---

# Why This Project Is Interesting

This is **not** another LLM wrapper.

The interesting problems are:

* Information Retrieval
* Semantic Search
* Cross-document Analysis
* Event Clustering
* Explainable AI
* Cross-lingual NLP
* Vector Databases
* Knowledge Extraction

The LLM should be the final explanation layer, not the core of the system.

---

# Future Extensions

## Timeline View

Track how reporting changes over time.

---

## Bias History

Measure how each newspaper frames recurring topics over months or years.

---

## Interactive Comparison

Select any two newspapers and compare their coverage.

---

## Bias Heatmap

Visualize differences in:

* source diversity
* sentiment
* framing
* topic emphasis

---

## Regional Coverage

Compare reporting between:

* National media
* State media
* Local newspapers

---

## AI Chat

Allow users to ask:

* "What facts are common across all reports?"
* "Which paper focused most on the economy?"
* "Show articles that omitted police statements."

---

# Long-Term Vision

Create an explainable multilingual news intelligence platform that helps readers understand **how narratives differ**, rather than telling them what to believe.

The system should promote critical thinking by presenting measurable evidence instead of opaque bias scores.

---

# Resume Value

This project demonstrates experience in:

* Information Retrieval
* NLP
* Semantic Search
* Embedding Models
* Vector Databases
* Explainable AI
* Web Crawling
* Cross-Lingual Machine Learning
* Distributed Data Pipelines
* Full-Stack Development

Rather than being another "AI summarizes text" application, this project focuses on solving a challenging information retrieval and multilingual analysis problem with transparent, evidence-based outputs.



# Decision Log

## Embedding issue

Used "all-MiniLM-L6-v2" for embedding, but its was not "smart" enough.
Slightly related documents are clustered very close together.

The *small context window* of 256 tokens is the issue.
MiniLM works on *shared vocabulary*, not semantic meaning

"nomic-ai/nomic-embed-text-v1.5" is semantic, and has a larger token window.
This model requires *task_prefixes* for each usecase. (search_document for documents, search_query for queries etc).
