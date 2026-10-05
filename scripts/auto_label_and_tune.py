#!/usr/bin/env python3
"""
Fully automated clustering hyperparameter tuner.
Auto-labels using tight dual criteria, then grid searches.
  Positive: cosine_sim > 0.72 AND NER jaccard > 0.15 AND time < 12h
  Negative: cosine_sim < 0.48 AND NER jaccard < 0.05
"""
from __future__ import annotations
import csv, os, random
from pathlib import Path
import numpy as np
import psycopg
import torch
import torch.nn.functional as F
from dotenv import load_dotenv
from scipy.cluster.hierarchy import fcluster, linkage
from scipy.spatial.distance import squareform

load_dotenv(dotenv_path=Path(__file__).parent.parent / ".env")
DB_URL = os.environ["DATABASE_URL"]
SCRIPT_DIR = Path(__file__).parent
LABELS_CSV = SCRIPT_DIR / "labeled_pairs.csv"
RESULTS_CSV = SCRIPT_DIR / "grid_search_results.csv"
TIME_WINDOW_HRS = 48.0
POS_COS_SIM, POS_NER_JAC, POS_TIME_HRS = 0.72, 0.15, 12.0
NEG_COS_SIM, NEG_NER_JAC = 0.48, 0.05

def _parse_emb(raw):
    if hasattr(raw, "to_numpy"): return raw.to_numpy()
    if isinstance(raw, np.ndarray): return raw
    if isinstance(raw, (list,tuple)): return np.array(raw, dtype=np.float32)
    if isinstance(raw, str): return np.fromstring(raw.strip("[]"), sep=",", dtype=np.float32)
    return np.array(raw, dtype=np.float32)

def fetch_top_days(conn, n=5):
    with conn.cursor() as cur:
        cur.execute("""
            SELECT DATE(a.published_at) AS day, COUNT(*) AS cnt
            FROM articles a JOIN article_embeddings e ON e.article_id = a.id
            GROUP BY day ORDER BY cnt DESC LIMIT %s;
        """, (n,))
        return [str(r[0]) for r in cur.fetchall()]

def fetch_articles(conn, date):
    with conn.cursor() as cur:
        cur.execute("""
            SELECT a.id, a.headline, a.source_name, a.published_at, e.embedding
            FROM articles a JOIN article_embeddings e ON e.article_id = a.id
            WHERE DATE(a.published_at) = %s ORDER BY a.published_at;
        """, (date,))
        rows = cur.fetchall()
    return [{"id":str(r[0]),"headline":r[1],"source":r[2],"published_at":r[3],"embedding":r[4]} for r in rows]

def fetch_entities(conn, ids):
    with conn.cursor() as cur:
        cur.execute("SELECT article_id, text, label FROM entities WHERE article_id = ANY(%s);", (ids,))
        rows = cur.fetchall()
    result = {}
    for aid, text, label in rows:
        result.setdefault(str(aid), set()).add((text, label))
    return result

def auto_label(articles, ents):
    n = len(articles)
    embs = torch.tensor(np.array([_parse_emb(a["embedding"]) for a in articles]), dtype=torch.float32)
    cos_sim_mat = (F.normalize(embs,p=2,dim=1) @ F.normalize(embs,p=2,dim=1).T).numpy()

    pos, neg = [], []
    for i in range(n):
        e_i = ents.get(articles[i]["id"], set())
        t_i = articles[i]["published_at"]
        for j in range(i+1, n):
            sim = float(cos_sim_mat[i,j])
            t_j = articles[j]["published_at"]
            hrs = abs((t_i - t_j).total_seconds()/3600) if t_i and t_j else 999
            e_j = ents.get(articles[j]["id"], set())
            union = len(e_i | e_j)
            ner_jac = len(e_i & e_j)/union if union else 0.0

            if sim > POS_COS_SIM and ner_jac > POS_NER_JAC and hrs < POS_TIME_HRS:
                pos.append((i,j))
            elif sim < NEG_COS_SIM and ner_jac < NEG_NER_JAC:
                neg.append((i,j))

    random.shuffle(neg)
    neg = neg[:max(len(pos)*3, 20)]

    labeled = []
    for i,j in pos:
        labeled.append({"id_a":articles[i]["id"],"id_b":articles[j]["id"],
                         "headline_a":articles[i]["headline"],"headline_b":articles[j]["headline"],"label":1})
    for i,j in neg:
        labeled.append({"id_a":articles[i]["id"],"id_b":articles[j]["id"],
                         "headline_a":articles[i]["headline"],"headline_b":articles[j]["headline"],"label":0})
    return labeled

def build_matrices(articles, ents):
    n = len(articles)
    ids = [a["id"] for a in articles]
    embs = torch.tensor(np.array([_parse_emb(a["embedding"]) for a in articles]), dtype=torch.float32)
    normed = F.normalize(embs,p=2,dim=1)
    emb_dist = np.clip(1.0-(normed@normed.T).numpy(), 0.0, None).astype(np.float32)

    time_dist = np.zeros((n,n), dtype=np.float32)
    for i in range(n):
        for j in range(i+1,n):
            t_i,t_j = articles[i]["published_at"],articles[j]["published_at"]
            d = min(abs((t_i-t_j).total_seconds()/3600)/TIME_WINDOW_HRS,1.0) if t_i and t_j else 0.0
            time_dist[i,j]=time_dist[j,i]=d

    ner_dist = np.zeros((n,n), dtype=np.float32)
    for i in range(n):
        e_i = ents.get(ids[i], set())
        for j in range(i+1,n):
            e_j = ents.get(ids[j], set())
            union=len(e_i|e_j)
            d = 1.0-len(e_i&e_j)/union if (union and e_i and e_j) else 1.0
            ner_dist[i,j]=ner_dist[j,i]=d

    np.fill_diagonal(emb_dist,0.0)
    return emb_dist, time_dist, ner_dist

def cluster_with(emb,time,ner,ids,threshold,w_emb,w_ner):
    w_t = round(1.0-w_emb-w_ner,6)
    D = w_emb*emb + w_t*time + w_ner*ner
    np.fill_diagonal(D,0.0)
    if len(ids)<2: return {ids[0]:1}
    Z = linkage(squareform(D,checks=False), method="complete")
    labels = fcluster(Z, t=threshold, criterion="distance")
    return {ids[i]:int(labels[i]) for i in range(len(ids))}

def evaluate(clusters, labeled):
    tp=fp=fn=tn=0
    for r in labeled:
        if r["id_a"] not in clusters or r["id_b"] not in clusters: continue
        pred = clusters[r["id_a"]]==clusters[r["id_b"]]
        act = r["label"]==1
        if pred and act: tp+=1
        elif pred and not act: fp+=1
        elif not pred and act: fn+=1
        else: tn+=1
    p = tp/(tp+fp) if (tp+fp)>0 else 0.0
    r = tp/(tp+fn) if (tp+fn)>0 else 0.0
    f1= 2*p*r/(p+r) if (p+r)>0 else 0.0
    return p,r,f1

def grid_search(emb,time,ner,ids,labeled):
    thresholds=[0.25,0.28,0.30,0.32,0.33,0.35,0.37,0.38,0.40]
    w_embs=[0.35,0.40,0.45,0.50,0.55,0.60]
    w_ners=[0.15,0.20,0.25,0.30,0.35,0.40,0.45]
    combos=[(t,we,wn) for t in thresholds for we in w_embs for wn in w_ners if we+wn<=1.0]
    results=[]
    print(f"\n  Grid search: {len(combos)} combos...", flush=True)
    for done,(threshold,w_emb,w_ner) in enumerate(combos,1):
        clusters=cluster_with(emb,time,ner,ids,threshold,w_emb,w_ner)
        p,r,f1=evaluate(clusters,labeled)
        results.append({"threshold":threshold,"w_emb":w_emb,"w_time":round(1-w_emb-w_ner,6),
                         "w_ner":w_ner,"precision":round(p,4),"recall":round(r,4),"f1":round(f1,4)})
        print(f"  {done}/{len(combos)}\r",end="",flush=True)
    results.sort(key=lambda x: x["f1"], reverse=True)
    return results

def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default=None)
    parser.add_argument("--all-days", action="store_true")
    args = parser.parse_args()

    print("\n  Connecting to DB...")
    with psycopg.connect(DB_URL) as conn:
        dates = fetch_top_days(conn, 5) if args.all_days else [args.date or fetch_top_days(conn,1)[0]]
        print(f"  Dates: {dates}")

        all_articles = []
        for date in dates:
            day = fetch_articles(conn, date)
            all_articles.extend(day)
            print(f"  {date}: {len(day)} articles")

        ents = fetch_entities(conn, [a["id"] for a in all_articles])

    print(f"\n  Total: {len(all_articles)} articles. Auto-labeling...")
    labeled = auto_label(all_articles, ents)
    n_pos = sum(1 for r in labeled if r["label"]==1)
    n_neg = sum(1 for r in labeled if r["label"]==0)
    print(f"  -> {n_pos} positive, {n_neg} negative pairs")

    if n_pos == 0:
        print("\n  No positive pairs found. Try --all-days or lower thresholds.")
        return

    # Show what was detected as same-event
    print("\n  Detected same-event pairs:")
    for r in labeled:
        if r["label"]==1:
            print(f"    + {r['headline_a'][:70]}")
            print(f"      {r['headline_b'][:70]}")

    # Save labels
    with LABELS_CSV.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["id_a","id_b","headline_a","headline_b","label"])
        w.writeheader(); w.writerows(labeled)

    # Re-fetch embeddings for labeled subset
    labeled_ids = list({r["id_a"] for r in labeled}|{r["id_b"] for r in labeled})
    print(f"\n  Building matrices for {len(labeled_ids)} articles...")
    with psycopg.connect(DB_URL) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT a.id, a.headline, a.source_name, a.published_at, e.embedding
                FROM articles a JOIN article_embeddings e ON e.article_id = a.id
                WHERE a.id = ANY(%s) ORDER BY a.id;
            """, (labeled_ids,))
            rows = cur.fetchall()
        ents_sub = fetch_entities(conn, labeled_ids)

    articles_list = [{"id":str(r[0]),"headline":r[1],"source":r[2],"published_at":r[3],"embedding":r[4]} for r in rows]
    ordered_ids = [a["id"] for a in articles_list]
    emb,time,ner = build_matrices(articles_list, ents_sub)
    results = grid_search(emb, time, ner, ordered_ids, labeled)

    # Report
    top = results[:15]
    print(f"\n  Ground truth: {n_pos} pos + {n_neg} neg pairs")
    print(f"\n{'='*72}")
    print(f"  TOP 15 PARAM COMBOS (F1 sorted)")
    print(f"{'='*72}")
    print(f"  {'thresh':>6}  {'w_emb':>6}  {'w_time':>6}  {'w_ner':>6}  {'P':>6}  {'R':>6}  {'F1':>6}")
    print(f"  {'-'*64}")
    for i,r in enumerate(top):
        mark = "  <- best" if i==0 else ""
        print(f"  {r['threshold']:>6.2f}  {r['w_emb']:>6.2f}  {r['w_time']:>6.2f}  "
              f"{r['w_ner']:>6.2f}  {r['precision']:>6.3f}  {r['recall']:>6.3f}  {r['f1']:>6.3f}{mark}")
    best = top[0]
    print(f"\n  RECOMMENDED:")
    print(f"    distance_threshold = {best['threshold']}")
    print(f"    weight_embedding   = {best['w_emb']}")
    print(f"    weight_time        = {best['w_time']}")
    print(f"    weight_entity      = {best['w_ner']}")
    print(f"\n  CURRENT (baseline):")
    print(f"    distance_threshold=0.40  w_emb=0.55  w_time=0.25  w_ner=0.20")

    with RESULTS_CSV.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["threshold","w_emb","w_time","w_ner","precision","recall","f1"])
        w.writeheader(); w.writerows(results)
    print(f"\n  Full results -> {RESULTS_CSV}\n")

if __name__ == "__main__":
    main()
