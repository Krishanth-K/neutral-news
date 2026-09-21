"""Background task runner for executing Make targets and pipeline operations."""

from __future__ import annotations

import asyncio
import os
import subprocess
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


class TaskInfo:
    def __init__(self, task_id: str, target: str, command: list[str], description: str):
        self.task_id = task_id
        self.target = target
        self.command = command
        self.description = description
        self.status = "running"  # "running", "completed", "failed", "stopped"
        self.created_at = datetime.now(timezone.utc).isoformat()
        self.finished_at: Optional[str] = None
        self.return_code: Optional[int] = None
        self.logs: list[str] = []
        self._lock = threading.Lock()
        self._process: Optional[subprocess.Popen] = None

    def add_log(self, line: str):
        with self._lock:
            # Strip trailing newlines and keep manageable buffer (max 1000 lines)
            clean_line = line.rstrip("\r\n")
            timestamp = datetime.now(timezone.utc).strftime("%H:%M:%S")
            self.logs.append(f"[{timestamp}] {clean_line}")
            if len(self.logs) > 1000:
                self.logs.pop(0)

    def to_dict(self) -> dict[str, Any]:
        with self._lock:
            return {
                "task_id": self.task_id,
                "target": self.target,
                "command": " ".join(self.command),
                "description": self.description,
                "status": self.status,
                "created_at": self.created_at,
                "finished_at": self.finished_at,
                "return_code": self.return_code,
                "log_count": len(self.logs),
                "recent_logs": self.logs[-20:],
            }

    def get_full_logs(self) -> list[str]:
        with self._lock:
            return list(self.logs)


class TaskManager:
    """Manages background task executions for Makefile commands and maintenance operations."""

    def __init__(self, repo_dir: str = "/home/krish/Dev/neutral-news"):
        self.repo_dir = repo_dir
        self.tasks: dict[str, TaskInfo] = {}
        self.target_definitions: dict[str, dict[str, Any]] = {
            "db-up": {
                "label": "DB Up",
                "description": "Start PostgreSQL container with pgvector on port 5433",
                "icon": "database",
                "category": "database",
                "variant": "success",
            },
            "db-down": {
                "label": "DB Down",
                "description": "Stop and remove PostgreSQL container",
                "icon": "database-zap",
                "category": "database",
                "variant": "danger",
            },
            "init-db": {
                "label": "Init DB",
                "description": "Initialize database extensions, schema, and indexes",
                "icon": "settings",
                "category": "database",
                "variant": "default",
            },
            "run": {
                "label": "Run Pipeline",
                "description": "Execute full pipeline: Ingest → Scrape → Embed → Extract → Group → Analyse",
                "icon": "play",
                "category": "pipeline",
                "variant": "primary",
            },
            "embed": {
                "label": "Embed Articles",
                "description": "Generate 768-dim embeddings for pending articles",
                "icon": "sparkles",
                "category": "pipeline",
                "variant": "default",
            },
            "clear-embed": {
                "label": "Clear Embeddings",
                "description": "Clear article_embeddings table and reset embedding status on all articles",
                "icon": "rotate-ccw",
                "category": "pipeline",
                "variant": "danger",
            },
            "extract": {
                "label": "Extract Entities",
                "description": "Extract spaCy named entities for pending articles",
                "icon": "tag",
                "category": "pipeline",
                "variant": "default",
            },
            "extract-quotes": {
                "label": "Extract Quotes",
                "description": "Extract quotes and identify speaker roles using Gemini LLM",
                "icon": "quote",
                "category": "pipeline",
                "variant": "default",
            },
            "group": {
                "label": "Group Events",
                "description": "Cluster articles into events via HAC and persist to PostgreSQL",
                "icon": "git-merge",
                "category": "pipeline",
                "variant": "default",
            },
            "analyse": {
                "label": "Analyse Events",
                "description": "Compute quote distributions and missing context across event articles",
                "icon": "bar-chart-2",
                "category": "analysis",
                "variant": "default",
            },
            "explain": {
                "label": "Generate Explanations",
                "description": "Generate neutral LLM explanations for multi-source events (skips already-explained)",
                "icon": "message-square",
                "category": "analysis",
                "variant": "primary",
            },
            "explain-force": {
                "label": "Regenerate Explanations",
                "description": "Regenerate LLM explanations for all eligible events, overwriting existing ones",
                "icon": "refresh-cw",
                "category": "analysis",
                "variant": "danger",
            },
            "test-rss": {
                "label": "Test RSS Feeds",
                "description": "Poll RSS feeds from The Hindu, Indian Express, and Times of India",
                "icon": "radio",
                "category": "testing",
                "variant": "default",
            },
            "test": {
                "label": "Run Tests",
                "description": "Run automated unittest suite for schema, CRUD, and analysis",
                "icon": "check-circle",
                "category": "testing",
                "variant": "default",
            },
            "view-db": {
                "label": "View DB Sample",
                "description": "Print recent articles from the database",
                "icon": "table",
                "category": "debug",
                "variant": "default",
            },
            "viz": {
                "label": "Generate Viz Map",
                "description": "Generate 2D embedding cluster visualization map (HTML)",
                "icon": "map",
                "category": "viz",
                "variant": "default",
            },
        }

    def get_available_targets(self) -> list[dict[str, Any]]:
        result = []
        for target, meta in self.target_definitions.items():
            # Find latest task status for this target
            latest_task = next(
                (t for t in reversed(list(self.tasks.values())) if t.target == target),
                None,
            )
            item = {
                "target": target,
                **meta,
                "latest_status": latest_task.status if latest_task else "idle",
                "latest_task_id": latest_task.task_id if latest_task else None,
            }
            result.append(item)
        return result

    def run_target(self, target: str, args: Optional[list[str]] = None) -> TaskInfo:
        cmd = ["make", target]
        if args:
            cmd.extend(args)

        task_id = str(uuid.uuid4())
        desc = self.target_definitions.get(target, {}).get(
            "description", f"Running make {target}"
        )
        task = TaskInfo(task_id, target, cmd, desc)
        self.tasks[task_id] = task

        # Run process in a separate daemon thread
        thread = threading.Thread(
            target=self._execute_process, args=(task,), daemon=True
        )
        thread.start()
        return task

    def _execute_process(self, task: TaskInfo):
        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"
        env["PYTHONPATH"] = "src"

        task.add_log(f"Starting command: {' '.join(task.command)} in {self.repo_dir}")
        try:
            process = subprocess.Popen(
                task.command,
                cwd=self.repo_dir,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                env=env,
            )
            task._process = process

            if process.stdout:
                for line in iter(process.stdout.readline, ""):
                    task.add_log(line)
                process.stdout.close()

            return_code = process.wait()
            task.return_code = return_code
            task.status = "completed" if return_code == 0 else "failed"
            task.add_log(
                f"Process finished with return code {return_code} ({task.status.upper()})"
            )
        except Exception as exc:
            task.status = "failed"
            task.add_log(f"Execution failed with exception: {exc}")
        finally:
            task.finished_at = datetime.now(timezone.utc).isoformat()

    def get_task(self, task_id: str) -> Optional[TaskInfo]:
        return self.tasks.get(task_id)

    def get_all_tasks(self, limit: int = 50) -> list[dict[str, Any]]:
        return [t.to_dict() for t in list(self.tasks.values())[-limit:]]


# Global singleton instance
task_manager = TaskManager()
