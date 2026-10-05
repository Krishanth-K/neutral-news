#!/usr/bin/env python3
"""
Clustering hyperparameter tuner for neutral-news.

Workflow:
  1. Fetch all articles from a single day (dense with real stories).
  2. Display them numbered — YOU pick which articles to keep (30-40).
  3. YOU group them: type the indices of articles that cover the same event.
     e.g. "2 5 11" means articles 2, 5, 11 are the same story.
  4. Pairs are auto-derived: within-group = positive, cross-group = negative.
  5. Grid search runs in memory over (threshold x w_emb x w_ner).
  6. Best params printed + saved to grid_search_results.csv.

Usage:
    python scripts/tune_clustering.py                   # auto-pick busiest day
    python scripts/tune_clustering.py --date 2026-09-21 # specific date
    python scripts/tune_clustering.py --search           # re-run search on saved labels
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
from itertools import combinations
from pathlib import Path

import numpy as np
import psycopg
import torch
import torch.nn.functional as F
from dotenv import load_dotenv
from scipy.cluster.hierarchy import fcluster, linkage
from scipy.spatial.distance import squareform

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

load_dotenv()
DB_URL = os.environ["DATABASE_URL"]

SCRIPT_DIR = Path(__file__).parent
LABELS_CSV = SCRIPT_DIR / "labeled_pairs.csv"
RESULTS_CSV = SCRIPT_DIR / "grid_search_results.csv"

TIME_WINDOW_HRS = 48.0  # must match distance.py


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def fetch_busiest_day(conn) -> str:
    """Return the date (YYYY-MM-DD) with the most embedded articles."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT DATE(a.published_at) AS day, COUNT(*) AS n
            FROM articles a
            JOIN article_embeddings e ON e.article_id = a.id
            GROUP BY day
            ORDER BY n DESC
            LIMIT 1;
            """
        )
        row = cur.fetchone()
    return str(row[0])


def fetch_articles_for_date(conn, date: str) -> list[dict]:
    """Return all embedded articles published on a given date, ordered by time."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT a.id, a.headline, a.source_name, a.published_at, e.embedding
            FROM articles a
            JOIN article_embeddings e ON e.article_id = a.id
            WHERE DATE(a.published_at) = %s
            ORDER BY a.published_at;
            """,
            (date,),
        )
        rows = cur.fetchall()

    return [
        {
            "id": str(r[0]),
            "headline": r[1],
            "source": r[2],
            "published_at": r[3],
            "embedding": r[4],
        }
        for r in rows
    ]


def fetch_entities(conn, article_ids: list[str]) -> dict[str, set]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT article_id, text, label FROM entities WHERE article_id = ANY(%s);",
            (article_ids,),
        )
        rows = cur.fetchall()

    result: dict[str, set] = {}
    for aid, text, label in rows:
        result.setdefault(str(aid), set()).add((text, label))
    return result


# ---------------------------------------------------------------------------
# Phase 1 -- Display articles
# ---------------------------------------------------------------------------

def display_articles(articles: list[dict]) -> None:
    """Print all articles numbered for the user to review."""
    print(f"\n{'='*75}")
    print(f"  {len(articles)} articles available — pick 30-40 to work with")
    print(f"{'='*75}")
    for idx, a in enumerate(articles):
        t = a["published_at"].strftime("%H:%M") if a["published_at"] else "??:??"
        print(f"  [{idx:>3}]  {t}  [{a['source'][:15]:<15}]  {a['headline']}")
    print()


def select_articles(articles: list[dict]) -> list[dict]:
    """
    Ask the user which article indices to keep.
    Returns the subset in the order they were entered.

    Accepts:
      - space/comma-separated numbers: 0 3 5 7 12 ...
      - 'all' to keep everything (not recommended if > 50 articles)
    """
    print("  Step 1 — Select articles to use (30-40 recommended).")
    print("  Enter indices separated by spaces or commas. Type 'all' to keep everything.")
    print()

    while True:
        raw = input("  Your selection > ").strip()
        if not raw:
            print("  → Please enter at least 2 indices.")
            continue

        if raw.lower() == "all":
            return articles

        # Parse indices
        tokens = raw.replace(",", " ").split()
        try:
            indices = [int(t) for t in tokens]
        except ValueError:
            print("  → Invalid input. Enter numbers separated by spaces (e.g. 0 2 5 11).")
            continue

        invalid = [i for i in indices if i < 0 or i >= len(articles)]
        if invalid:
            print(f"  → Out-of-range indices: {invalid}. Valid range: 0–{len(articles)-1}.")
            continue

        if len(set(indices)) < 2:
            print("  → Select at least 2 distinct articles.")
            continue

        selected = [articles[i] for i in dict.fromkeys(indices)]  # preserve order, deduplicate
        print(f"\n  ✓ Selected {len(selected)} articles.\n")
        return selected


# ---------------------------------------------------------------------------
# Phase 1 -- Grouping
# ---------------------------------------------------------------------------

def display_selected(articles: list[dict]) -> None:
    """Re-display only the selected articles with new 0-based indices."""
    print(f"{'='*75}")
    print(f"  Selected articles (use THESE indices for grouping)")
    print(f"{'='*75}")
    for idx, a in enumerate(articles):
        t = a["published_at"].strftime("%H:%M") if a["published_at"] else "??:??"
        print(f"  [{idx:>2}]  {t}  [{a['source'][:15]:<15}]  {a['headline']}")
    print()


def collect_groups(articles: list[dict]) -> list[list[int]]:
    """
    Ask the user to define groups of same-event articles.

    Each line = one group = space/comma-separated indices of articles that
    cover the same news event.
    Single articles (no match) can be left ungrouped — they'll each become
    their own singleton group, pairing as negatives against everything else.

    Returns list of groups, where each group is a list of article indices.
    Example: [[0, 3, 7], [1, 5], [2], [4], [6]]
    """
    n = len(articles)
    print("  Step 2 — Group same-event articles.")
    print("  Each line = one group (articles covering the same story).")
    print("  Enter space-separated indices. Leave a line blank and press Enter to finish.")
    print("  Articles NOT mentioned become singletons (their own group).")
    print("  Example:")
    print("    0 3 7    ← articles 0, 3, 7 are about the same event")
    print("    1 5      ← articles 1 and 5 are about a different shared event")
    print("    (blank)  ← done")
    print()

    groups: list[list[int]] = []
    mentioned: set[int] = set()

    while True:
        raw = input(f"  Group {len(groups)+1} > ").strip()
        if not raw:
            break

        tokens = raw.replace(",", " ").split()
        try:
            indices = [int(t) for t in tokens]
        except ValueError:
            print("  → Invalid input. Enter numbers separated by spaces.")
            continue

        invalid = [i for i in indices if i < 0 or i >= n]
        if invalid:
            print(f"  → Out-of-range: {invalid}. Valid range 0–{n-1}.")
            continue

        already = [i for i in indices if i in mentioned]
        if already:
            print(f"  → Indices {already} already in a group. Skipping duplicates.")
            indices = [i for i in indices if i not in mentioned]

        if not indices:
            continue

        groups.append(indices)
        mentioned.update(indices)
        print(f"  ✓ Group {len(groups)}: {indices}")

    # Singletons — articles not placed in any group
    singletons = [[i] for i in range(n) if i not in mentioned]
    if singletons:
        print(f"\n  {len(singletons)} articles not in any group → treated as singletons.")
    groups.extend(singletons)

    return groups


# ---------------------------------------------------------------------------
# Phase 1 -- Derive pairs from groups
# ---------------------------------------------------------------------------

def derive_pairs(groups: list[list[int]], articles: list[dict]) -> list[dict]:
    """
    Auto-generate labeled pairs from user-defined groups.

    Positive pairs (label=1): all pairs within the same group (same event).
    Negative pairs (label=0): cross-group pairs — sampled to avoid explosion.
    """
    positive_pairs: list[tuple[int, int]] = []
    for group in groups:
        for i, j in combinations(group, 2):
            positive_pairs.append((min(i, j), max(i, j)))

    negative_pairs: list[tuple[int, int]] = []
    seen_neg: set[tuple[int, int]] = set()
    for g1_idx in range(len(groups)):
        for g2_idx in range(g1_idx + 1, len(groups)):
            for i in groups[g1_idx]:
                for j in groups[g2_idx]:
                    key = (min(i, j), max(i, j))
                    if key not in seen_neg:
                        seen_neg.add(key)
                        negative_pairs.append(key)

    # Cap negatives to ~3x positives to keep it balanced
    max_neg = max(len(positive_pairs) * 3, 30)
    if len(negative_pairs) > max_neg:
        import random
        random.shuffle(negative_pairs)
        negative_pairs = negative_pairs[:max_neg]

    labeled: list[dict] = []
    for i, j in positive_pairs:
        labeled.append({
            "id_a": articles[i]["id"], "id_b": articles[j]["id"],
            "headline_a": articles[i]["headline"], "headline_b": articles[j]["headline"],
            "label": 1,
        })
    for i, j in negative_pairs:
        labeled.append({
            "id_a": articles[i]["id"], "id_b": articles[j]["id"],
            "headline_a": articles[i]["headline"], "headline_b": articles[j]["headline"],
            "label": 0,
        })

    print(f"\n  ✓ Generated {len(positive_pairs)} positive pairs + {len(negative_pairs)} negative pairs = {len(labeled)} total.")
    return labeled


# ---------------------------------------------------------------------------
# Distance component builders
# ---------------------------------------------------------------------------

def _parse_embedding(raw) -> np.ndarray:
    if hasattr(raw, "to_numpy"):
        return raw.to_numpy()
    if isinstance(raw, np.ndarray):
        return raw
    if isinstance(raw, (list, tuple)):
        return np.array(raw, dtype=np.float32)
    if isinstance(raw, str):
        return np.fromstring(raw.strip("[]"), sep=",", dtype=np.float32)
    return np.array(raw, dtype=np.float32)


def build_component_matrices(
    articles: list[dict],
    entities_by_article: dict[str, set],
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return (emb_dist, time_dist, ner_dist) -- each shape (n, n)."""
    n = len(articles)
    ids = [a["id"] for a in articles]

    # Embedding distance
    raw_embs = [_parse_embedding(a["embedding"]) for a in articles]
    embs = torch.tensor(np.array(raw_embs), dtype=torch.float32)
    normed = F.normalize(embs, p=2, dim=1)
    cos_sim = (normed @ normed.T).numpy()
    emb_dist = np.clip(1.0 - cos_sim, 0.0, None).astype(np.float32)

    # Time distance
    time_dist = np.zeros((n, n), dtype=np.float32)
    for i in range(n):
        for j in range(i + 1, n):
            t_i = articles[i]["published_at"]
            t_j = articles[j]["published_at"]
            if t_i and t_j:
                hrs = abs((t_i - t_j).total_seconds() / 3600)
                d = min(hrs / TIME_WINDOW_HRS, 1.0)
            else:
                d = 0.0
            time_dist[i, j] = time_dist[j, i] = d

    # NER Jaccard distance
    ner_dist = np.zeros((n, n), dtype=np.float32)
    for i in range(n):
        e_i = entities_by_article.get(ids[i], set())
        for j in range(i + 1, n):
            e_j = entities_by_article.get(ids[j], set())
            if not e_i or not e_j:
                d = 1.0
            else:
                union = len(e_i | e_j)
                d = 1.0 - len(e_i & e_j) / union if union else 1.0
            ner_dist[i, j] = ner_dist[j, i] = d

    np.fill_diagonal(emb_dist, 0.0)
    return emb_dist, time_dist, ner_dist


# ---------------------------------------------------------------------------
# Phase 2 -- Grid search
# ---------------------------------------------------------------------------

def cluster_with_params(
    emb_dist: np.ndarray,
    time_dist: np.ndarray,
    ner_dist: np.ndarray,
    article_ids: list[str],
    threshold: float,
    w_emb: float,
    w_ner: float,
) -> dict[str, int]:
    w_time = round(1.0 - w_emb - w_ner, 6)
    D = w_emb * emb_dist + w_time * time_dist + w_ner * ner_dist
    np.fill_diagonal(D, 0.0)

    n = len(article_ids)
    if n < 2:
        return {article_ids[0]: 1}

    condensed = squareform(D, checks=False)
    Z = linkage(condensed, method="complete")
    labels = fcluster(Z, t=threshold, criterion="distance")
    return {article_ids[i]: int(labels[i]) for i in range(n)}


def evaluate(clusters: dict[str, int], labeled: list[dict]) -> tuple[float, float, float]:
    tp = fp = fn = tn = 0
    for row in labeled:
        a_id, b_id = row["id_a"], row["id_b"]
        if a_id not in clusters or b_id not in clusters:
            continue
        predicted_same = clusters[a_id] == clusters[b_id]
        actual_same = row["label"] == 1

        if predicted_same and actual_same:
            tp += 1
        elif predicted_same and not actual_same:
            fp += 1
        elif not predicted_same and actual_same:
            fn += 1
        else:
            tn += 1

    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
    return precision, recall, f1


def grid_search(
    emb_dist: np.ndarray,
    time_dist: np.ndarray,
    ner_dist: np.ndarray,
    article_ids: list[str],
    labeled: list[dict],
) -> list[dict]:
    thresholds = [0.25, 0.28, 0.30, 0.32, 0.33, 0.35, 0.37, 0.38, 0.40]
    w_embs = [0.35, 0.40, 0.45, 0.50, 0.55, 0.60]
    w_ners = [0.15, 0.20, 0.25, 0.30, 0.35, 0.40, 0.45]

    combos = [(t, we, wn) for t in thresholds for we in w_embs for wn in w_ners if we + wn <= 1.0]
    results = []

    print(f"\n  Running grid search over {len(combos)} param combos...")

    for done, (threshold, w_emb, w_ner) in enumerate(combos, 1):
        clusters = cluster_with_params(emb_dist, time_dist, ner_dist, article_ids, threshold, w_emb, w_ner)
        precision, recall, f1 = evaluate(clusters, labeled)
        w_time = round(1.0 - w_emb - w_ner, 6)
        results.append({
            "threshold": threshold,
            "w_emb": w_emb,
            "w_time": w_time,
            "w_ner": w_ner,
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "f1": round(f1, 4),
        })
        print(f"  {done}/{len(combos)}\r", end="", flush=True)

    results.sort(key=lambda r: r["f1"], reverse=True)
    return results


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def print_results(results: list[dict], labeled: list[dict]) -> None:
    n_pos = sum(1 for r in labeled if r["label"] == 1)
    n_neg = sum(1 for r in labeled if r["label"] == 0)
    print(f"\n  Ground truth: {n_pos} positive pairs, {n_neg} negative pairs")

    top = results[:10]
    print(f"\n{'='*70}")
    print(f"  TOP 10 PARAM COMBOS  (sorted by F1)")
    print(f"{'='*70}")
    print(f"  {'thresh':>6}  {'w_emb':>6}  {'w_time':>6}  {'w_ner':>6}  {'P':>6}  {'R':>6}  {'F1':>6}")
    print(f"  {'-'*62}")
    for r in top:
        marker = "  <- best" if r is top[0] else ""
        print(
            f"  {r['threshold']:>6.2f}  {r['w_emb']:>6.2f}  {r['w_time']:>6.2f}  "
            f"{r['w_ner']:>6.2f}  {r['precision']:>6.3f}  {r['recall']:>6.3f}  {r['f1']:>6.3f}{marker}"
        )

    best = top[0]
    print(f"\n  RECOMMENDED SETTINGS:")
    print(f"    distance_threshold = {best['threshold']}")
    print(f"    weight_embedding   = {best['w_emb']}")
    print(f"    weight_time        = {best['w_time']}")
    print(f"    weight_entity      = {best['w_ner']}")
    print(f"\n  CURRENT SETTINGS (for comparison):")
    print(f"    distance_threshold = 0.40")
    print(f"    weight_embedding   = 0.55")
    print(f"    weight_time        = 0.25")
    print(f"    weight_entity      = 0.20")
    print()


def save_labels(labeled: list[dict], path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["id_a", "id_b", "headline_a", "headline_b", "label"])
        writer.writeheader()
        writer.writerows(labeled)
    print(f"  ✓ Labels saved -> {path}")


def load_labels(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        r["label"] = int(r["label"])
    print(f"  ✓ Loaded {len(rows)} labeled pairs from {path}")
    return rows


def save_results(results: list[dict], path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["threshold", "w_emb", "w_time", "w_ner", "precision", "recall", "f1"])
        writer.writeheader()
        writer.writerows(results)
    print(f"  ✓ Full results saved -> {path}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Tune clustering hyperparameters.")
    parser.add_argument("--date", type=str, default=None, help="Date to pull articles from (YYYY-MM-DD). Defaults to busiest day.")
    parser.add_argument("--search", action="store_true", help="Skip labeling, re-run grid search on saved labels.")
    args = parser.parse_args()

    # ---- Phase 2 only (re-run search on existing labels) ----------------
    if args.search:
        if not LABELS_CSV.exists():
            print(f"  No labels file at {LABELS_CSV}. Run without --search first.")
            sys.exit(1)

        labeled = load_labels(LABELS_CSV)
        article_ids_needed = list({r["id_a"] for r in labeled} | {r["id_b"] for r in labeled})

    else:
        # ---- Phase 1: Fetch, display, select, group ---------------------
        print("\n  Connecting to database...")
        with psycopg.connect(DB_URL) as conn:
            date = args.date or fetch_busiest_day(conn)
            print(f"  Fetching articles for {date}...")
            all_articles = fetch_articles_for_date(conn, date)

        if len(all_articles) < 5:
            print(f"  Only {len(all_articles)} articles on {date}. Try a different date.")
            sys.exit(1)

        print(f"  Found {len(all_articles)} articles on {date}.")

        # Step 1: Show all, user picks a subset
        display_articles(all_articles)
        selected = select_articles(all_articles)

        # Step 2: Re-display selected, user groups them
        display_selected(selected)
        groups = collect_groups(selected)

        if not any(len(g) > 1 for g in groups):
            print("\n  No groups with more than 1 article — no positive pairs possible.")
            print("  Add at least one group of 2+ articles that cover the same event.")
            sys.exit(1)

        # Step 3: Auto-derive pairs from groups
        labeled = derive_pairs(groups, selected)
        save_labels(labeled, LABELS_CSV)
        article_ids_needed = list({r["id_a"] for r in labeled} | {r["id_b"] for r in labeled})

    # ---- Phase 2: Build matrices + grid search --------------------------
    print(f"\n  Fetching embeddings + entities for {len(article_ids_needed)} articles...")
    with psycopg.connect(DB_URL) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT a.id, a.headline, a.source_name, a.published_at, e.embedding
                FROM articles a
                JOIN article_embeddings e ON e.article_id = a.id
                WHERE a.id = ANY(%s)
                ORDER BY a.id;
                """,
                (article_ids_needed,),
            )
            rows = cur.fetchall()

        articles_map = {
            str(r[0]): {"id": str(r[0]), "headline": r[1], "source": r[2], "published_at": r[3], "embedding": r[4]}
            for r in rows
        }
        entities_by_article = fetch_entities(conn, list(articles_map.keys()))

    articles_list = list(articles_map.values())
    ordered_ids = [a["id"] for a in articles_list]

    print(f"  Building component distance matrices ({len(articles_list)}x{len(articles_list)})...")
    emb_dist, time_dist, ner_dist = build_component_matrices(articles_list, entities_by_article)

    results = grid_search(emb_dist, time_dist, ner_dist, ordered_ids, labeled)
    print_results(results, labeled)
    save_results(results, RESULTS_CSV)


if __name__ == "__main__":
    main()
