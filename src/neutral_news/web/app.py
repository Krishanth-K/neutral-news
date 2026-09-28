"""FastAPI web application for Media Lens (Neutral News)."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from neutral_news.web.services import (
    get_database_stats,
    get_debug_articles_table,
    get_event_detail_with_analysis,
    get_events_feed,
    get_raw_table_sample,
    get_sources_list,
)
from neutral_news.web.tasks import task_manager

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
TEMPLATES_DIR = BASE_DIR / "templates"

app = FastAPI(
    title="Media Lens",
    description="An explainable news comparison platform — not a bias score, an evidence explorer.",
    version="1.0.0",
)

# CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static files if directory exists
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/", response_class=HTMLResponse)
async def serve_index(request: Request):
    """Serve the single-page application."""
    index_path = TEMPLATES_DIR / "index.html"
    if not index_path.exists():
        raise HTTPException(status_code=404, detail="Template index.html not found.")
    return HTMLResponse(content=index_path.read_text(encoding="utf-8"))


# ------------------------------------------------------------------------------
# News & Event API Routes
# ------------------------------------------------------------------------------


@app.get("/api/events")
async def list_events(
    search: Optional[str] = Query(None, description="Search keyword in headlines or event titles"),
    source: Optional[str] = Query(None, description="Filter by source name"),
    multi_only: bool = Query(False, description="Only return events covered by multiple sources"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page"),
):
    """Fetch paginated event feed."""
    try:
        data = get_events_feed(
            search=search,
            source=source,
            multi_source_only=multi_only,
            page=page,
            page_size=page_size,
        )
        return data
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to fetch events: {exc}")


@app.get("/api/events/{event_id}")
async def get_event(event_id: str):
    """Fetch deep event details, cross-source articles, quotes, missing context analysis, and related events."""
    try:
        data = get_event_detail_with_analysis(event_id)
        if not data:
            raise HTTPException(status_code=404, detail="Event not found.")
        return data
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to load event details: {exc}")


@app.get("/api/sources")
async def list_sources():
    """List available sources with their article counts."""
    try:
        return get_sources_list()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to fetch sources: {exc}")


# ------------------------------------------------------------------------------
# Debug & Pipeline API Routes
# ------------------------------------------------------------------------------


@app.get("/api/debug/stats")
async def debug_stats():
    """Get database statistics and queue metrics."""
    try:
        return get_database_stats()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to fetch DB stats: {exc}")


@app.get("/api/debug/articles")
async def debug_articles(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    search: Optional[str] = Query(None),
    source: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
):
    """Fetch raw article records with status filter and search for debugging."""
    try:
        return get_debug_articles_table(
            limit=limit,
            offset=offset,
            search=search,
            source=source,
            status=status,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to fetch articles table: {exc}")


@app.get("/api/debug/tables/{table_name}")
async def debug_table_view(
    table_name: str,
    limit: int = Query(25, ge=1, le=100),
):
    """Inspect schema and raw sample records of any internal table."""
    try:
        return get_raw_table_sample(table_name=table_name, limit=limit)
    except ValueError as val_err:
        raise HTTPException(status_code=400, detail=str(val_err))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to inspect table '{table_name}': {exc}")


@app.get("/api/debug/targets")
async def list_make_targets():
    """List all available make pipeline options with their metadata and current state."""
    return task_manager.get_available_targets()


@app.post("/api/debug/run/{target}")
async def run_make_target(
    target: str,
    request: Request,
):
    """Trigger execution of any Make target in the background."""
    if target not in task_manager.target_definitions:
        raise HTTPException(status_code=400, detail=f"Target '{target}' is not a recognized make option.")

    body = {}
    try:
        body = await request.json()
    except Exception:
        pass

    args = body.get("args") if isinstance(body.get("args"), list) else None

    # For commands taking a numeric limit or threshold
    if "limit" in body and body["limit"]:
        if args is None:
            args = []
        args.append(str(body["limit"]))

    task = task_manager.run_target(target=target, args=args)
    return task.to_dict()


@app.get("/api/debug/tasks")
async def list_tasks(limit: int = Query(20, ge=1, le=100)):
    """List recent background tasks."""
    return task_manager.get_all_tasks(limit=limit)


@app.get("/api/debug/tasks/{task_id}")
async def get_task_status(task_id: str):
    """Get status and live log output for a specific background task."""
    task = task_manager.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found.")
    
    task_dict = task.to_dict()
    task_dict["logs"] = task.get_full_logs()
    return task_dict


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("neutral_news.web.app:app", host="0.0.0.0", port=8000, reload=True)
