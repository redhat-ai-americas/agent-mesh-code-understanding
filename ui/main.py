"""FastAPI backend for the Code Understanding console."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from starlette.background import BackgroundTask
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.body_limit import RequestBodyLimitMiddleware
from starlette.requests import Request

import catalog
import cluster
import downloads
import index_storage
import indexes
import uploads

STATIC_DIR = Path(__file__).resolve().parent / "static"
MULTIPART_OVERHEAD_BYTES = 64 * 1024


class FrameAncestorsMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = "frame-ancestors *"
        response.headers["X-Frame-Options"] = "ALLOWALL"
        return response


app = FastAPI(title="Code Understanding console", docs_url=None, redoc_url=None)
app.add_middleware(FrameAncestorsMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(
    RequestBodyLimitMiddleware,
    max_body_size=index_storage.configured_max_index_bytes() + MULTIPART_OVERHEAD_BYTES,
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


@app.get("/api/indexes/{run_id}/download")
def download_index(run_id: str) -> FileResponse:
    """Stream a validated GraphRAG index bundle to the browser."""
    if os.getenv("ASSET_LOADER", "local").strip().lower() != "mlflow":
        raise HTTPException(
            status_code=503,
            detail="Index downloads require ASSET_LOADER=mlflow in code-understanding-env.",
        )

    try:
        client = indexes.create_mlflow_client()
        metadata = indexes.validate_index_run(client, run_id)
    except indexes.IndexRunValidationError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Unable to validate MLflow index run: {exc}") from exc

    workspace = index_storage.create_index_workspace()
    try:
        archive_path, filename = downloads.create_index_archive(
            client,
            metadata,
            workspace,
            index_storage.configured_max_index_bytes(),
        )
    except Exception as exc:
        index_storage.cleanup_index_workspace(workspace)
        if isinstance(exc, downloads.DownloadTooLargeError):
            raise HTTPException(status_code=413, detail=str(exc)) from exc
        if isinstance(exc, FileNotFoundError):
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        raise HTTPException(status_code=502, detail=f"Unable to download MLflow index artifact: {exc}") from exc

    return FileResponse(
        path=archive_path,
        media_type="application/gzip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        background=BackgroundTask(index_storage.cleanup_index_workspace, workspace),
    )


@app.post("/api/indexes/upload")
def upload_index(
    file: UploadFile = File(...),
) -> dict[str, Any]:
    """Validate one portable tar.gz bundle and log it as a fresh MLflow index run."""
    workspace: Path | None = None
    try:
        if os.getenv("ASSET_LOADER", "local").strip().lower() != "mlflow":
            raise HTTPException(
                status_code=503,
                detail="Index uploads require ASSET_LOADER=mlflow in code-understanding-env.",
            )
        if not (file.filename or "").lower().endswith(".tar.gz"):
            raise HTTPException(status_code=400, detail="Upload one .tar.gz index bundle.")

        max_bytes = index_storage.configured_max_index_bytes()
        if file.size is not None and file.size > max_bytes:
            raise HTTPException(
                status_code=413,
                detail=f"Uploaded archive exceeds the maximum size of {max_bytes} bytes.",
            )

        try:
            client = indexes.create_mlflow_client()
        except Exception as exc:
            raise HTTPException(status_code=503, detail=f"MLflow is unavailable: {exc}") from exc

        workspace = index_storage.create_index_workspace()
        metadata = uploads.extract_uploaded_index(
            file.file,
            workspace / "artifact",
            max_bytes,
        )
        return indexes.log_uploaded_index(client, metadata, workspace / "artifact")
    except uploads.IndexArchiveTooLargeError as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from exc
    except uploads.IndexArchiveError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except indexes.MlflowUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except indexes.MlflowUploadError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    finally:
        try:
            file.file.close()
        finally:
            if workspace is not None:
                index_storage.cleanup_index_workspace(workspace)


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
