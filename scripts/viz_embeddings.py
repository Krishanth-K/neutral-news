"""
Debug script: Visualise article embeddings in 2D.

Fetches stored embeddings from the DB, reduces them to 2D via UMAP,
and writes an interactive Plotly scatter plot to embeddings_map.html.

Usage:
    make viz                         # default: up to 500 articles
    make viz LIMIT=200               # custom limit
    make viz METHOD=tsne             # use t-SNE instead of UMAP
    make viz OUT=my_map.html         # custom output filename

Dependencies (not in main requirements):
    pip install umap-learn plotly pandas
"""

from __future__ import annotations

import argparse
import sys

import numpy as np
import pandas as pd
import psycopg

# ── lazy imports so missing deps give a clear error message ──────────────────

def _import_umap():
    try:
        import umap  # noqa: PLC0415
        return umap
    except ImportError:
        print("[ERROR] umap-learn is not installed. Run: pip install umap-learn")
        sys.exit(1)


def _import_plotly():
    try:
        import plotly.express as px  # noqa: PLC0415
        return px
    except ImportError:
        print("[ERROR] plotly is not installed. Run: pip install plotly")
        sys.exit(1)


# ─────────────────────────────────────────────────────────────────────────────


def fetch_embeddings(db_url: str, limit: int) -> pd.DataFrame:
    """Pull embeddings + metadata from the database."""
    print(f"[VIZ] Fetching up to {limit} embedded articles from DB...")
    with psycopg.connect(db_url) as conn:
        from pgvector.psycopg import register_vector  # noqa: PLC0415
        register_vector(conn)
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    a.headline,
                    a.source_name,
                    a.published_at,
                    a.article_url,
                    e.embedding
                FROM article_embeddings e
                JOIN articles a ON a.id = e.article_id
                WHERE a.scrape_status = 'completed'
                ORDER BY a.published_at DESC NULLS LAST
                LIMIT %s;
                """,
                (limit,),
            )
            rows = cur.fetchall()

    if not rows:
        print("[VIZ] No embedded articles found in the database. Run `make run` first.")
        sys.exit(0)

    print(f"[VIZ] Fetched {len(rows)} articles.")
    headlines, sources, dates, urls, vectors = zip(*rows)

    return pd.DataFrame({
        "headline": headlines,
        "source":   sources,
        "date":     [str(d)[:10] if d else "unknown" for d in dates],
        "url":      urls,
        "vector":   [v.to_list() for v in vectors],
    })


def reduce_umap(X: np.ndarray, n_neighbors: int = 15, min_dist: float = 0.1) -> np.ndarray:
    umap = _import_umap()
    print("[VIZ] Running UMAP dimensionality reduction → 2D...")
    reducer = umap.UMAP(
        n_components=2,
        n_neighbors=n_neighbors,
        min_dist=min_dist,
        random_state=42,
        low_memory=False,
    )
    return reducer.fit_transform(X)


def reduce_tsne(X: np.ndarray) -> np.ndarray:
    try:
        from sklearn.manifold import TSNE  # noqa: PLC0415
    except ImportError:
        print("[ERROR] scikit-learn is not installed. Run: pip install scikit-learn")
        sys.exit(1)

    print("[VIZ] Running t-SNE dimensionality reduction → 2D...")
    # PCA pre-reduction keeps t-SNE fast on high-dim data
    from sklearn.decomposition import PCA  # noqa: PLC0415
    X_pca = PCA(n_components=50, random_state=42).fit_transform(X)
    return TSNE(n_components=2, perplexity=30, random_state=42, n_iter=1000).fit_transform(X_pca)


def build_plot(df: pd.DataFrame, method: str, out: str) -> None:
    px = _import_plotly()

    fig = px.scatter(
        df,
        x="x",
        y="y",
        color="source",
        hover_name="headline",
        hover_data={"source": True, "date": True, "url": True, "x": False, "y": False},
        title=f"Article Embedding Space ({method.upper()}) — {len(df)} articles",
        labels={"source": "News Outlet"},
        width=1100,
        height=750,
        opacity=0.75,
        template="plotly_white",
    )
    fig.update_traces(marker=dict(size=7))
    fig.update_layout(
        font=dict(family="Inter, sans-serif", size=13),
        legend=dict(title_text="Outlet", itemsizing="constant"),
    )
    fig.write_html(out)

    # Splice in a click handler and cursor style before </body>.
    # (post_script injects inside an existing <script> block and breaks the page.)
    click_html = """
<style>.plotly-graph-div { cursor: pointer; }</style>
<script>
(function() {
    function attachClickHandler() {
        var plots = document.querySelectorAll('.plotly-graph-div');
        plots.forEach(function(plot) {
            if (plot._clickHandlerAttached) return;
            plot._clickHandlerAttached = true;
            plot.on('plotly_click', function(data) {
                var pt = data.points[0];
                // customdata order matches hover_data declaration: [source, date, url, x, y]
                var url = pt.customdata ? pt.customdata[2] : null;
                if (url) window.open(url, '_blank');
            });
        });
    }
    if (document.readyState === 'complete') {
        setTimeout(attachClickHandler, 500);
    } else {
        window.addEventListener('load', function() { setTimeout(attachClickHandler, 500); });
    }
})();
</script>
"""
    with open(out, "r", encoding="utf-8") as f:
        html = f.read()
    html = html.replace("</body>", click_html + "</body>", 1)
    with open(out, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"[VIZ] Saved interactive map → {out}  (click any point to open the article)")
    print(f"[VIZ] Open it in your browser: file://{out}")


def main() -> None:
    # ── import here so PYTHONPATH is already set by the Makefile ────────────
    from neutral_news.config import DATABASE_URL  # noqa: PLC0415

    parser = argparse.ArgumentParser(
        description="Visualise article embeddings in 2D (UMAP or t-SNE)."
    )
    parser.add_argument(
        "--limit", "-n",
        type=int,
        default=500,
        help="Max number of articles to fetch (default: 500)",
    )
    parser.add_argument(
        "--method", "-m",
        choices=["umap", "tsne"],
        default="umap",
        help="Dimensionality reduction method (default: umap)",
    )
    parser.add_argument(
        "--out", "-o",
        default="embeddings_map.html",
        help="Output HTML filename (default: embeddings_map.html)",
    )
    args = parser.parse_args()

    df = fetch_embeddings(DATABASE_URL, args.limit)

    X = np.array(df["vector"].tolist())
    if args.method == "umap":
        coords = reduce_umap(X)
    else:
        coords = reduce_tsne(X)

    df["x"] = coords[:, 0]
    df["y"] = coords[:, 1]
    df.drop(columns=["vector"], inplace=True)

    build_plot(df, args.method, args.out)


if __name__ == "__main__":
    main()
