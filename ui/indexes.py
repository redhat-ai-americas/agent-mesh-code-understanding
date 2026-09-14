"""Discover GraphRAG indexes stored via the configured asset loader."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from catalog import git_slug

RESULT_DIRECTORY_EXPERIMENT_SUFFIX = "/code-refactoring/assets/result-directories"
INDEX_ARTIFACT_ROOT = "results/datasets/repos"
MULTI_REPO_ARTIFACT_PATH = f"{INDEX_ARTIFACT_ROOT}/multi-repo"
UPLOADED_TAG = "uploaded"


class IndexRunValidationError(LookupError):
    """Raised when an MLflow run cannot be used as a downloadable index."""


class MlflowUnavailableError(RuntimeError):
    """Raised when the configured MLflow service cannot be reached."""


class MlflowUploadError(RuntimeError):
    """Raised when an otherwise available MLflow service cannot log an upload."""


def result_directory_experiment_name(workspace: str | None = None) -> str:
    """Return the MLflow experiment that stores result-directory artifacts."""
    selected_workspace = (
        workspace or os.getenv("MLFLOW_WORKSPACE") or os.getenv("KFP_NAMESPACE") or "demo"
    ).strip()
    return f"{selected_workspace}{RESULT_DIRECTORY_EXPERIMENT_SUFFIX}"


def index_artifact_path(git_slug_value: str | None, multi_repo: bool = False) -> str:
    """Return the only artifact path accepted for an indexing run.

    Indexing jobs log GraphRAG output beneath the shared result-directory
    artifact root.  A single-repository index uses its generated slug as the
    next path component; a combined index always uses ``multi-repo``.
    """
    if multi_repo:
        return MULTI_REPO_ARTIFACT_PATH

    slug = str(git_slug_value or "").strip()
    if not slug:
        raise ValueError("git_slug is required for a single-repository index")
    if slug in {".", ".."} or "/" in slug or "\\" in slug:
        raise ValueError("git_slug must be a single path component")
    return f"{INDEX_ARTIFACT_ROOT}/{slug}"


def _as_bool(value: Any) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "y", "on"}


def _run_index_metadata(run: Any) -> dict[str, Any]:
    """Build stable download metadata from an MLflow run object."""
    tags = getattr(getattr(run, "data", None), "tags", None) or {}
    slug = str(tags.get("git_slug") or "")
    multi = _as_bool(tags.get("multi_repo"))
    uploaded = _as_bool(tags.get(UPLOADED_TAG))
    try:
        artifact_path = index_artifact_path(slug, multi_repo=multi)
    except ValueError as exc:
        raise IndexRunValidationError(str(exc)) from exc

    run_info = getattr(run, "info", None)
    started = getattr(run_info, "start_time", None)
    return {
        "git_slug": slug,
        "multi_repo": multi,
        "uploaded": uploaded,
        "run_id": str(getattr(run_info, "run_id", "")),
        "indexed_at": datetime.fromtimestamp(started / 1000, tz=timezone.utc).isoformat()
        if started
        else "",
        "artifact_path": artifact_path,
    }


def _public_index_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    """Return index fields needed by the browser without exposing artifact layout."""
    return {
        key: metadata[key]
        for key in ("git_slug", "multi_repo", "uploaded", "run_id", "indexed_at")
    }


def validate_index_run(client: Any, run_id: str) -> dict[str, Any]:
    """Validate and describe a downloadable indexing run.

    The experiment, category tag, and artifact path are all resolved here so
    callers never need to trust a path supplied by the browser.
    """
    experiment_name = result_directory_experiment_name()
    experiment = client.get_experiment_by_name(experiment_name)
    if experiment is None:
        raise IndexRunValidationError(f"No result-directory experiment found: {experiment_name}")

    try:
        run = client.get_run(run_id)
    except Exception as exc:
        raise IndexRunValidationError(f"MLflow run not found: {run_id}") from exc

    run_info = getattr(run, "info", None)
    if str(getattr(run_info, "experiment_id", "")) != str(experiment.experiment_id):
        raise IndexRunValidationError("MLflow run is not in the configured result-directory experiment")

    tags = getattr(getattr(run, "data", None), "tags", None) or {}
    if str(tags.get("category", "")).strip().lower() != "indexing":
        raise IndexRunValidationError("MLflow run is not an indexing run")

    return _run_index_metadata(run)


def create_mlflow_client() -> Any:
    """Create an MLflow client authenticated with the pod service account."""
    from mlflow.tracking import MlflowClient

    token_path = "/var/run/secrets/kubernetes.io/serviceaccount/token"
    if not os.environ.get("MLFLOW_TRACKING_TOKEN") and os.path.isfile(token_path):
        os.environ["MLFLOW_TRACKING_TOKEN"] = Path(token_path).read_text(encoding="utf-8").strip()

    return MlflowClient()


def _result_directory_experiment(client: Any) -> Any:
    """Find or create the experiment used for result-directory artifacts."""
    name = result_directory_experiment_name()
    try:
        experiment = client.get_experiment_by_name(name)
        if experiment is None:
            client.create_experiment(name)
            experiment = client.get_experiment_by_name(name)
    except Exception as exc:
        raise MlflowUnavailableError(f"Unable to access MLflow experiment {name}: {exc}") from exc
    if experiment is None:
        raise MlflowUnavailableError(f"Unable to create MLflow experiment: {name}")
    return experiment


def log_uploaded_index(client: Any, metadata: dict[str, Any], directory: Path) -> dict[str, Any]:
    """Store a validated extracted bundle in a fresh indexing MLflow run."""
    experiment = _result_directory_experiment(client)
    tags = {
        "category": "indexing",
        "git_slug": str(metadata["git_slug"]),
        "multi_repo": str(bool(metadata["multi_repo"])),
        UPLOADED_TAG: "true",
    }
    run_id = ""
    try:
        run = client.create_run(experiment.experiment_id, tags=tags)
        run_id = str(run.info.run_id)
        client.log_artifacts(
            run_id,
            str(directory),
            artifact_path=index_artifact_path(metadata["git_slug"], metadata["multi_repo"]),
        )
        if hasattr(client, "set_terminated"):
            client.set_terminated(run_id, status="FINISHED")
    except Exception as exc:
        if run_id and hasattr(client, "delete_run"):
            try:
                client.delete_run(run_id)
            except Exception:
                pass
        raise MlflowUploadError(f"Unable to upload index artifact to MLflow: {exc}") from exc

    return {
        "git_slug": tags["git_slug"],
        "multi_repo": bool(metadata["multi_repo"]),
        "uploaded": True,
        "run_id": run_id,
        "indexed_at": datetime.now(timezone.utc).isoformat(),
    }


def list_indexed_repos() -> dict[str, Any]:
    """Return indexed repositories discovered from MLflow artifact runs."""
    if os.getenv("ASSET_LOADER", "local").strip().lower() != "mlflow":
        return {
            "ok": True,
            "source": "local",
            "indexes": [],
            "message": "Index discovery requires ASSET_LOADER=mlflow in code-understanding-env.",
        }

    try:
        client = create_mlflow_client()
        experiment_name = result_directory_experiment_name()
        experiment = client.get_experiment_by_name(experiment_name)
        if experiment is None:
            return {
                "ok": True,
                "source": "mlflow",
                "indexes": [],
                "message": f"No MLflow experiment yet: {experiment_name}",
            }

        runs = client.search_runs(
            experiment_ids=[experiment.experiment_id],
            filter_string='tags.category = "indexing"',
            order_by=["attributes.start_time DESC"],
            max_results=200,
        )
        seen: set[tuple[str, bool]] = set()
        indexes: list[dict[str, Any]] = []
        for run in runs:
            try:
                metadata = _run_index_metadata(run)
            except IndexRunValidationError:
                continue
            key = (metadata["git_slug"], metadata["multi_repo"])
            if key in seen:
                continue
            seen.add(key)
            indexes.append(_public_index_metadata(metadata))
        return {"ok": True, "source": "mlflow", "indexes": indexes, "message": ""}
    except Exception as exc:
        return {"ok": False, "source": "mlflow", "indexes": [], "message": str(exc)}


def index_lookup(indexes: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Map git_slug -> index metadata."""
    return {item["git_slug"]: item for item in indexes if item.get("git_slug")}


def repo_is_indexed(git_repo: str, git_branch: str, indexes: list[dict[str, Any]]) -> bool:
    slug = git_slug(git_repo, git_branch)
    return any(item.get("git_slug") == slug and not item.get("multi_repo") for item in indexes)


def multi_repo_indexed(indexes: list[dict[str, Any]]) -> bool:
    return any(item.get("multi_repo") for item in indexes)


def queryable_repos(
    indexes: list[dict[str, Any]],
    catalog: list[dict[str, str]],
) -> list[dict[str, Any]]:
    """Catalog entries that have a GraphRAG index, plus optional multi-repo index."""
    from catalog import repo_key

    options: list[dict[str, Any]] = []
    for item in catalog:
        if repo_is_indexed(item["git_repo"], item["git_branch"], indexes):
            short = item["git_repo"].rsplit("/", 1)[-1]
            options.append(
                {
                    **item,
                    "label": f"{short} @ {item['git_branch']}",
                    "key": repo_key(item),
                    "use_global": False,
                }
            )
    if multi_repo_indexed(indexes):
        options.append(
            {
                "git_repo": "",
                "git_branch": "main",
                "label": "Combined multi-repo index",
                "key": "__multi_repo__",
                "use_global": True,
            }
        )
    return options


def default_query_key(options: list[dict[str, Any]]) -> str | None:
    for option in options:
        if "tic-tac-toe" in option.get("git_repo", ""):
            return option["key"]
    return options[0]["key"] if options else None
