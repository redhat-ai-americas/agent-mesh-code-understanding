"""FastAPI backend for the native Code Understanding OpenShift plugin."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

import catalog
import cluster
import indexes

STATIC_DIR = Path(__file__).resolve().parent / "static"


class FrameAncestorsMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = "frame-ancestors *"
        response.headers["X-Frame-Options"] = "ALLOWALL"
        return response


app = FastAPI(title="Code Understanding plugin API", docs_url=None, redoc_url=None)
app.add_middleware(FrameAncestorsMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class Repo(BaseModel):
    git_repo: str
    git_branch: str = "main"


class PipelineRequest(BaseModel):
    repos: list[Repo] = Field(default_factory=list)


class QueryRequest(BaseModel):
    question: str
    git_repo: str = ""
    git_branch: str = "main"
    use_global: bool | None = None


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/health")
def health() -> dict[str, str]:
    status = cluster.cluster_status()
    if not status.get("ok"):
        raise HTTPException(503, status.get("message") or "cluster unavailable")
    return {"status": "ok", "namespace": status["namespace"]}


@app.get("/api/status")
def status() -> dict[str, Any]:
    return cluster.cluster_status()


@app.get("/api/catalog")
def get_catalog() -> dict[str, Any]:
    entries = catalog.load_catalog()
    default = catalog.default_repo_entry()
    return {
        "repos": entries,
        "default_key": catalog.repo_key(default) if default else None,
    }


@app.get("/api/indexes")
def get_indexes() -> dict[str, Any]:
    data = indexes.list_indexed_repos()
    catalog_entries = catalog.load_catalog()
    options = indexes.queryable_repos(data.get("indexes") or [], catalog_entries)
    return {**data, "queryable": options}


@app.get("/api/jobs")
def get_jobs() -> dict[str, Any]:
    try:
        return {"jobs": cluster.list_recent_jobs()}
    except Exception as exc:
        raise HTTPException(503, str(exc)) from exc


@app.get("/api/jobs/{job_name}")
def get_job(job_name: str) -> dict[str, Any]:
    try:
        return cluster.job_snapshot(job_name)
    except Exception as exc:
        raise HTTPException(404, str(exc)) from exc


@app.post("/api/pipelines")
def start_pipeline(body: PipelineRequest) -> dict[str, str]:
    repos = [item.model_dump() for item in body.repos]
    try:
        return cluster.submit_pipeline_run(repos)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(500, str(exc)) from exc


@app.post("/api/query")
def start_query(body: QueryRequest) -> dict[str, str]:
    try:
        return cluster.submit_adhoc_query(
            body.question,
            git_repo=body.git_repo,
            git_branch=body.git_branch,
            use_global=body.use_global,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(500, str(exc)) from exc
