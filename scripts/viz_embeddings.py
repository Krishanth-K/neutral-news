"""
Debug script: Visualise article embeddings in 2D with cluster boundaries.

Fetches stored embeddings from the DB, reduces them to 2D via UMAP (or t-SNE),
clusters articles using Hierarchical Agglomerative Clustering (HAC),
computes smooth 2D cluster boundaries, and writes an interactive Plotly HTML map.

Usage:
    make viz                            # default: up to 500 articles, HAC threshold 0.40
    make viz LIMIT=200                  # custom limit
    make viz METHOD=tsne                # use t-SNE instead of UMAP
    make viz THRESHOLD=0.35             # custom HAC distance cutoff
    make viz OUT=my_map.html            # custom output filename

Dependencies (not in main requirements):
    pip install umap-learn plotly pandas scipy
"""

from __future__ import annotations

import argparse
import html
import sys
from typing import Any

import numpy as np
import pandas as pd
import psycopg
from scipy.interpolate import splprep, splev
from scipy.spatial import ConvexHull

from neutral_news.embed.cluster import cluster_articles_hac


# ── lazy imports so missing deps give a clear error message ──────────────────

def _import_umap():
    try:
        import umap  # noqa: PLC0415
        return umap
    except ImportError:
        print("[ERROR] umap-learn is not installed. Run: pip install umap-learn")
        sys.exit(1)


def _import_plotly_go():
    try:
        import plotly.colors as pcolors  # noqa: PLC0415
        import plotly.graph_objects as go  # noqa: PLC0415
        return go, pcolors
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
                    a.id,
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
    ids, headlines, sources, dates, urls, vectors = zip(*rows)

    return pd.DataFrame({
        "id":       [str(i) for i in ids],
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
    from sklearn.decomposition import PCA  # noqa: PLC0415
    X_pca = PCA(n_components=min(50, X.shape[1], X.shape[0]), random_state=42).fit_transform(X)
    perplexity = min(30, max(5, (len(X) - 1) // 3))
    try:
        return TSNE(n_components=2, perplexity=perplexity, random_state=42, max_iter=1000).fit_transform(X_pca)
    except TypeError:
        return TSNE(n_components=2, perplexity=perplexity, random_state=42, n_iter=1000).fit_transform(X_pca)  # type: ignore


def run_hac(
    vectors: np.ndarray,
    article_ids: list[str],
    threshold: float = 0.40,
    linkage: str = "complete",
) -> dict[int, dict]:
    """Computes pairwise cosine distance matrix and clusters articles with cluster_articles_hac."""
    print(f"[VIZ] Clustering articles with HAC (threshold={threshold}, linkage={linkage})...")
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    norms[norms == 0] = 1e-12
    norm_X = vectors / norms

    cosine_sim = norm_X @ norm_X.T
    cosine_dist = np.clip(1.0 - cosine_sim, 0.0, 2.0)
    np.fill_diagonal(cosine_dist, 0.0)

    clusters = cluster_articles_hac(
        distances=cosine_dist,
        article_ids=article_ids,
        distance_threshold=threshold,
        linkage_method=linkage,
    )
    print(f"[VIZ] HAC identified {len(clusters)} clusters ({sum(1 for c in clusters.values() if c['size'] > 1)} multi-article clusters).")
    return clusters


def compute_cluster_boundary(
    points: np.ndarray,
    pad: float,
    n_smooth: int = 100,
) -> tuple[np.ndarray, np.ndarray]:
    """Generates a smoothed 2D padded boundary polygon enclosing the given points."""
    n = len(points)
    if n == 0:
        return np.array([]), np.array([])

    if n == 1:
        angles = np.linspace(0, 2 * np.pi, 36)
        x = points[0, 0] + pad * np.cos(angles)
        y = points[0, 1] + pad * np.sin(angles)
        return x, y

    if n == 2:
        p0, p1 = points[0], points[1]
        vec = p1 - p0
        length = float(np.linalg.norm(vec))
        if length < 1e-6:
            angles = np.linspace(0, 2 * np.pi, 36)
            return p0[0] + pad * np.cos(angles), p0[1] + pad * np.sin(angles)

        u = vec / length
        n_vec = np.array([-u[1], u[0]])
        angles_p1 = np.linspace(-np.pi / 2, np.pi / 2, 20)
        angles_p0 = np.linspace(np.pi / 2, 3 * np.pi / 2, 20)

        poly_pts = []
        for a in angles_p1:
            poly_pts.append(p1 + pad * (np.cos(a) * u + np.sin(a) * n_vec))
        for a in angles_p0:
            poly_pts.append(p0 + pad * (np.cos(a) * u + np.sin(a) * n_vec))
        poly_pts.append(poly_pts[0])
        arr = np.array(poly_pts)
        return arr[:, 0], arr[:, 1]

    # n >= 3: Padded Convex Hull with smooth fillets
    try:
        hull = ConvexHull(points)
        hull_pts = points[hull.vertices]
    except Exception:
        # Collinear fallback: project onto dominant principal axis
        centroid = np.mean(points, axis=0)
        _, _, vt = np.linalg.svd(points - centroid)
        proj = (points - centroid) @ vt[0]
        min_idx, max_idx = int(np.argmin(proj)), int(np.argmax(proj))
        return compute_cluster_boundary(points[[min_idx, max_idx]], pad=pad, n_smooth=n_smooth)

    centroid = np.mean(hull_pts, axis=0)
    n_v = len(hull_pts)
    offset_pts = []

    for i in range(n_v):
        p_prev = hull_pts[(i - 1) % n_v]
        p_curr = hull_pts[i]
        p_next = hull_pts[(i + 1) % n_v]

        e1 = p_curr - p_prev
        norm1 = np.linalg.norm(e1)
        n1 = np.array([-e1[1], e1[0]]) / (norm1 if norm1 > 0 else 1.0)
        if np.dot(n1, p_curr - centroid) < 0:
            n1 = -n1

        e2 = p_next - p_curr
        norm2 = np.linalg.norm(e2)
        n2 = np.array([-e2[1], e2[0]]) / (norm2 if norm2 > 0 else 1.0)
        if np.dot(n2, p_next - centroid) < 0:
            n2 = -n2

        angle1 = np.arctan2(n1[1], n1[0])
        angle2 = np.arctan2(n2[1], n2[0])
        diff = (angle2 - angle1) % (2 * np.pi)
        n_arc = max(3, int(np.ceil(diff / (np.pi / 8))))
        arc_angles = np.linspace(angle1, angle1 + diff, n_arc)
        for a in arc_angles:
            offset_pts.append(p_curr + pad * np.array([np.cos(a), np.sin(a)]))

    offset_pts = np.array(offset_pts)

    if len(offset_pts) > 4:
        try:
            tck, _ = splprep([offset_pts[:, 0], offset_pts[:, 1]], s=0, per=True)
            u_fine = np.linspace(0, 1, n_smooth)
            x_smooth, y_smooth = splev(u_fine, tck)
            return np.asarray(x_smooth), np.asarray(y_smooth)
        except Exception:
            pass

    offset_pts = np.vstack([offset_pts, offset_pts[0]])
    return offset_pts[:, 0], offset_pts[:, 1]


def build_plot(
    df: pd.DataFrame,
    clusters: dict[int, dict],
    method: str,
    threshold: float,
    linkage: str,
    min_cluster_size: int,
    pad_override: float | None,
    out: str | None = None,
) -> Any:
    go, pcolors = _import_plotly_go()

    # Determine auto padding from 2D coordinate spread
    x_range = float(df["x"].max() - df["x"].min())
    y_range = float(df["y"].max() - df["y"].min())
    auto_pad = max(x_range, y_range) * 0.024
    pad = pad_override if pad_override is not None else max(auto_pad, 0.15)

    # Color palette for clusters and sources
    cluster_palette = (
        pcolors.qualitative.Dark24
        + pcolors.qualitative.Light24
        + pcolors.qualitative.Alphabet
        + pcolors.qualitative.Plotly
    )

    # Build lookup maps for cluster attributes
    article_to_cluster: dict[str, int] = {}
    is_medoid_map: dict[str, bool] = {}
    for cid, cinfo in clusters.items():
        for aid in cinfo["article_ids"]:
            article_to_cluster[aid] = cid
            is_medoid_map[aid] = (aid == cinfo["medoid_id"])

    df["cluster_id"] = df["id"].map(article_to_cluster)
    df["is_medoid"] = df["id"].map(is_medoid_map)

    # Multi-article clusters sorted by size descending
    multi_clusters = [
        (cid, cinfo) for cid, cinfo in sorted(
            clusters.items(),
            key=lambda item: item[1]["size"],
            reverse=True,
        )
        if cinfo["size"] >= min_cluster_size
    ]

    fig = go.Figure()

    # ── 1. Boundary Traces (one polygon per multi-article cluster) ────────────
    boundary_trace_indices: list[int] = []

    for idx, (cid, cinfo) in enumerate(multi_clusters):
        c_df = df[df["id"].isin(cinfo["article_ids"])]
        c_pts = c_df[["x", "y"]].to_numpy()

        bx, by = compute_cluster_boundary(c_pts, pad=pad)
        if len(bx) == 0:
            continue

        base_color = cluster_palette[idx % len(cluster_palette)]
        # Parse hex or rgb to rgba
        if base_color.startswith("#"):
            rgb = [int(base_color.lstrip("#")[i:i+2], 16) for i in (0, 2, 4)]
            fill_color = f"rgba({rgb[0]}, {rgb[1]}, {rgb[2]}, 0.12)"
            line_color = f"rgba({rgb[0]}, {rgb[1]}, {rgb[2]}, 0.75)"
        else:
            fill_color = "rgba(100, 100, 100, 0.12)"
            line_color = "rgba(100, 100, 100, 0.75)"

        # Summary text for boundary hover
        sources_count = c_df["source"].value_counts().to_dict()
        source_summary = ", ".join(f"{s}: {cnt}" for s, cnt in sources_count.items())
        medoid_row = df[df["id"] == cinfo["medoid_id"]]
        medoid_headline = medoid_row.iloc[0]["headline"] if not medoid_row.empty else "N/A"
        date_min, date_max = c_df["date"].min(), c_df["date"].max()
        date_span = date_min if date_min == date_max else f"{date_min} → {date_max}"

        boundary_hover = (
            f"<b>Cluster #{cid}</b> ({cinfo['size']} articles)<br>"
            f"<b>Medoid:</b> {html.escape(medoid_headline[:85])}...<br>"
            f"<b>Sources:</b> {html.escape(source_summary)}<br>"
            f"<b>Dates:</b> {date_span}"
        )

        trace = go.Scatter(
            x=bx,
            y=by,
            fill="toself",
            fillcolor=fill_color,
            line=dict(color=line_color, width=1.5, dash="solid"),
            mode="lines",
            name=f"Cluster #{cid} ({cinfo['size']} arts)",
            text=boundary_hover,
            hoverinfo="text",
            hoveron="fills+points",
            legendgroup="clusters",
            legendgrouptitle_text="Clusters",
            showlegend=False,
            visible=True,
        )
        boundary_trace_indices.append(len(fig.data))
        fig.add_trace(trace)

    # ── 2. Article Scatter Points: By Outlet (Default View) ───────────────────
    outlet_trace_indices: list[int] = []
    unique_sources = sorted(df["source"].unique())

    source_palette = pcolors.qualitative.Plotly + pcolors.qualitative.Safe + pcolors.qualitative.Pastel
    for s_idx, source in enumerate(unique_sources):
        s_df = df[df["source"] == source]
        hover_texts = []
        custom_urls = []
        for _, row in s_df.iterrows():
            cid = row["cluster_id"]
            med_flag = " ⭐ [Medoid]" if row["is_medoid"] else ""
            c_size = clusters[cid]["size"] if cid in clusters else 1
            htext = (
                f"<b>{html.escape(row['headline'])}</b><br>"
                f"<b>Outlet:</b> {html.escape(row['source'])}<br>"
                f"<b>Date:</b> {row['date']}<br>"
                f"<b>Cluster:</b> #{cid} ({c_size} articles){med_flag}<br>"
                f"<i>(Click point to open article)</i>"
            )
            hover_texts.append(htext)
            custom_urls.append(row["url"])

        trace = go.Scatter(
            x=s_df["x"],
            y=s_df["y"],
            mode="markers",
            name=source,
            text=hover_texts,
            customdata=custom_urls,
            hoverinfo="text",
            marker=dict(
                size=8, 
                opacity=0.85, 
                color=source_palette[s_idx % len(source_palette)]
            ),
            legendgroup="outlets",
            legendgrouptitle_text="News Outlets",
            showlegend=True,
            visible=True,
        )
        outlet_trace_indices.append(len(fig.data))
        fig.add_trace(trace)

    # ── 3. Article Scatter Points: By Cluster (Alternate Color View) ─────────
    cluster_point_trace_indices: list[int] = []
    all_cids = sorted(clusters.keys(), key=lambda c: clusters[c]["size"], reverse=True)

    for c_idx, cid in enumerate(all_cids):
        cinfo = clusters[cid]
        c_df = df[df["id"].isin(cinfo["article_ids"])]
        if c_df.empty:
            continue

        hover_texts = []
        custom_urls = []
        for _, row in c_df.iterrows():
            med_flag = " ⭐ [Medoid]" if row["is_medoid"] else ""
            htext = (
                f"<b>{html.escape(row['headline'])}</b><br>"
                f"<b>Outlet:</b> {html.escape(row['source'])}<br>"
                f"<b>Date:</b> {row['date']}<br>"
                f"<b>Cluster:</b> #{cid} ({cinfo['size']} articles){med_flag}<br>"
                f"<i>(Click point to open article)</i>"
            )
            hover_texts.append(htext)
            custom_urls.append(row["url"])

        base_color = cluster_palette[c_idx % len(cluster_palette)]
        trace = go.Scatter(
            x=c_df["x"],
            y=c_df["y"],
            mode="markers",
            name=f"Cluster #{cid} ({cinfo['size']})",
            text=hover_texts,
            customdata=custom_urls,
            hoverinfo="text",
            marker=dict(size=8, opacity=0.85, color=base_color),
            legendgroup="cluster_pts",
            legendgrouptitle_text="Clusters",
            showlegend=(cinfo["size"] >= min_cluster_size),
            visible=False,
        )
        cluster_point_trace_indices.append(len(fig.data))
        fig.add_trace(trace)

    # ── 4. Medoid Star Markers ───────────────────────────────────────────────
    medoid_df = df[df["is_medoid"] & (df["cluster_id"].isin([c[0] for c in multi_clusters]))]
    if not medoid_df.empty:
        med_hovers = [
            f"<b>Cluster #{r['cluster_id']} Representative (Medoid)</b><br>"
            f"<b>Headline:</b> {html.escape(r['headline'])}<br>"
            f"<b>Outlet:</b> {r['source']}<br>"
            f"<b>Date:</b> {r['date']}"
            for _, r in medoid_df.iterrows()
        ]
        medoid_trace = go.Scatter(
            x=medoid_df["x"],
            y=medoid_df["y"],
            mode="markers",
            marker=dict(symbol="star", size=11, color="rgba(30,30,30,0.85)", line=dict(color="white", width=1)),
            name="Cluster Medoids",
            text=med_hovers,
            customdata=medoid_df["url"].tolist(),
            hoverinfo="text",
            showlegend=True,
            visible=True,
        )
        fig.add_trace(medoid_trace)
        medoid_trace_idx = len(fig.data) - 1
    else:
        medoid_trace_idx = None

    # Total trace count
    total_traces = len(fig.data)

    def visibility_vector(outlets: bool, cluster_pts: bool, boundaries: bool, medoids: bool) -> list[bool]:
        vec = [False] * total_traces
        if boundaries:
            for idx in boundary_trace_indices:
                vec[idx] = True
        if outlets:
            for idx in outlet_trace_indices:
                vec[idx] = True
        if cluster_pts:
            for idx in cluster_point_trace_indices:
                vec[idx] = True
        if medoids and medoid_trace_idx is not None:
            vec[medoid_trace_idx] = True
        return vec

    # ── 5. Layout with Interactive Control Buttons ───────────────────────────
    updatemenus = [
        # Button 1: Point Coloring Mode (By News Outlet vs By Cluster)
        dict(
            type="buttons",
            direction="left",
            active=0,
            x=0.0,
            xanchor="left",
            y=1.12,
            yanchor="top",
            pad={"r": 10, "t": 10},
            buttons=[
                dict(
                    label="🎨 Color by News Outlet",
                    method="update",
                    args=[{"visible": visibility_vector(outlets=True, cluster_pts=False, boundaries=True, medoids=True)}],
                ),
                dict(
                    label="🏷️ Color by Cluster",
                    method="update",
                    args=[{"visible": visibility_vector(outlets=False, cluster_pts=True, boundaries=True, medoids=True)}],
                ),
            ],
        ),
        # Button 2: Toggle Cluster Boundaries
        dict(
            type="buttons",
            direction="left",
            active=0,
            x=0.36,
            xanchor="left",
            y=1.12,
            yanchor="top",
            pad={"r": 10, "t": 10},
            buttons=[
                dict(
                    label="⭕ Show Boundaries",
                    method="restyle",
                    args=[{"visible": True}, boundary_trace_indices],
                ),
                dict(
                    label="🚫 Hide Boundaries",
                    method="restyle",
                    args=[{"visible": False}, boundary_trace_indices],
                ),
            ],
        ),
    ]

    total_multi_articles = sum(c[1]["size"] for c in multi_clusters)
    subtitle = (
        f"{len(df)} articles | {len(multi_clusters)} multi-article clusters "
        f"({total_multi_articles} clustered) | HAC (threshold={threshold:.2f}, {linkage})"
    )

    fig.update_layout(
        title=dict(
            text=f"<b>Article Embedding Space ({method.upper()})</b><br><span style='font-size:12px;color:#555;'>{subtitle}</span>",
            x=0.0,
            y=0.98,
        ),
        font=dict(family="Inter, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif", size=13),
        legend=dict(
            title_text="Legend",
            itemsizing="constant",
            bgcolor="rgba(255, 255, 255, 0.85)",
            bordercolor="rgba(200, 200, 200, 0.6)",
            borderwidth=1,
            yanchor="top",
            y=1.0,
            xanchor="left",
            x=1.02,
        ),
        width=1200,
        height=800,
        template="plotly_white",
        updatemenus=updatemenus,
        margin=dict(l=60, r=220, t=110, b=60),
    )

    if out is None:
        return fig

    fig.write_html(out)

    # Splice in interactive click handler to open articles in new tab
    click_html = """
<style>
.plotly-graph-div { cursor: pointer; }
.modebar-container { top: 10px !important; right: 10px !important; }
</style>
<script>
(function() {
    function attachClickHandler() {
        var plots = document.querySelectorAll('.plotly-graph-div');
        plots.forEach(function(plot) {
            if (plot._clickHandlerAttached) return;
            plot._clickHandlerAttached = true;
            plot.on('plotly_click', function(data) {
                if (!data || !data.points || data.points.length === 0) return;
                var pt = data.points[0];
                var url = pt.customdata;
                if (Array.isArray(url)) {
                    url = url[0];
                }
                if (url && typeof url === 'string' && url.startsWith('http')) {
                    window.open(url, '_blank');
                }
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
        html_content = f.read()
    html_content = html_content.replace("</body>", click_html + "</body>", 1)
    with open(out, "w", encoding="utf-8") as f:
        f.write(html_content)

    print(f"[VIZ] Saved interactive map → {out}  (click any point to open article)")
    print(f"[VIZ] Open it in your browser: file://{out}")
    return fig


def main() -> None:
    from neutral_news.config import DATABASE_URL  # noqa: PLC0415

    parser = argparse.ArgumentParser(
        description="Visualise article embeddings in 2D with HAC cluster boundaries."
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
        "--threshold", "-t",
        type=float,
        default=0.40,
        help="HAC distance cutoff threshold (default: 0.40)",
    )
    parser.add_argument(
        "--linkage", "-l",
        choices=["complete", "average"],
        default="complete",
        help="HAC linkage method (default: complete)",
    )
    parser.add_argument(
        "--min-cluster-size",
        type=int,
        default=2,
        help="Minimum cluster size to draw a boundary around (default: 2)",
    )
    parser.add_argument(
        "--pad",
        type=float,
        default=None,
        help="Boundary padding radius (default: auto-calculated from coordinates)",
    )
    parser.add_argument(
        "--out", "-o",
        default="embeddings_map.html",
        help="Output HTML filename (default: embeddings_map.html)",
    )
    parser.add_argument(
        "--dash",
        action="store_true",
        help="Run an interactive Dash web app with real-time threshold slider",
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

    if args.dash:
        try:
            import dash
            from dash import dcc, html, Input, Output
        except ImportError:
            print("[ERROR] Dash is not installed. Run: pip install dash")
            sys.exit(1)

        app = dash.Dash(__name__)
        
        app.layout = html.Div([
            html.H2("Article Embedding Visualisation"),
            html.Div([
                html.Label("HAC Distance Threshold: "),
                html.Span(id="threshold-output", style={"fontWeight": "bold"}),
                dcc.Slider(
                    id="threshold-slider",
                    min=0.10,
                    max=1.00,
                    step=0.01,
                    value=args.threshold,
                    marks={i/10: str(i/10) for i in range(1, 11)},
                )
            ], style={"padding": "20px"}),
            dcc.Graph(id="embedding-graph", style={"height": "80vh"})
        ], style={"fontFamily": "sans-serif"})

        @app.callback(
            [Output("embedding-graph", "figure"), Output("threshold-output", "children")],
            [Input("threshold-slider", "value")]
        )
        def update_graph(threshold):
            # Re-run clustering
            clusters = run_hac(
                vectors=X,
                article_ids=df["id"].tolist(),
                threshold=threshold,
                linkage=args.linkage,
            )
            fig = build_plot(
                df=df.copy(),
                clusters=clusters,
                method=args.method,
                threshold=threshold,
                linkage=args.linkage,
                min_cluster_size=args.min_cluster_size,
                pad_override=args.pad,
                out=None,  # Do not save to file
            )
            return fig, f"{threshold:.2f}"

        print("\n[VIZ] Starting Dash app... Open http://127.0.0.1:8050 in your browser.")
        app.run(debug=True, use_reloader=False)
        return

    # Normal static HTML generation
    clusters = run_hac(
        vectors=X,
        article_ids=df["id"].tolist(),
        threshold=args.threshold,
        linkage=args.linkage,
    )

    build_plot(
        df=df,
        clusters=clusters,
        method=args.method,
        threshold=args.threshold,
        linkage=args.linkage,
        min_cluster_size=args.min_cluster_size,
        pad_override=args.pad,
        out=args.out,
    )

if __name__ == "__main__":
    main()
