
| From → To | What actually moves |
|---|---|
| RSS feed → Fetch full text | `article_url`, `source_name`, `published_at` |
| Fetch full text → Store raw | `article_id`, `full_text`, `headline`, `source_name`, `url`, `published_at` |
| Store raw → Extract entities/quotes | `article_id`, `full_text` |
| Extract → Generate embeddings | `article_id`, `headline`, list of `entity_names` |
| Generate embeddings → Group into events | `article_id`, `embedding_vector` |
| Group into events → Analyze | `event_id`, list of `article_id`s in that group |
| Extract (quotes) → Analyze | `article_id`, list of `(quote_text, speaker, role)` |
| Analyze → LLM explanation | `event_id`, `quote_distribution_counts`, `missing_topics_list` |
| LLM explanation → Frontend | `event_id`, `explanation_text`, underlying evidence (counts, missing list — so frontend can show it, not just prose) |

