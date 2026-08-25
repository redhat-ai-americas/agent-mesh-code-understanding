"""Discover GraphRAG indexes stored via the configured asset loader."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

from catalog import git_slug


def _mlflow_client():
    import mlflow
    from mlflow.tracking import MlflowClient

    token_path = "/var/run/secrets/kubernetes.io/serviceaccount/token"
    if not os.environ.get("MLFLOW_TRACKING_TOKEN") and os.path.isfile(token_path):
        with open(token_path, encoding="utf-8") as handle:
            os.environ["MLFLOW_TRACKING_TOKEN"] = handle.read().strip()

    return mlflow, MlflowClient()


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
        mlflow, client = _mlflow_client()
        workspace = os.getenv("MLFLOW_WORKSPACE", os.getenv("KFP_NAMESPACE", "demo"))
        experiment_name = f"{workspace}/code-refactoring/assets/result-directories"
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
            tags = run.data.tags
            slug = tags.get("git_slug", "")
            multi = str(tags.get("multi_repo", "false")).lower() == "true"
            key = (slug, multi)
            if key in seen:
                continue
            seen.add(key)
            started = run.info.start_time
            indexes.append(
                {
                    "git_slug": slug,
                    "multi_repo": multi,
                    "run_id": run.info.run_id,
                    "indexed_at": datetime.fromtimestamp(started / 1000, tz=timezone.utc).isoformat()
                    if started
                    else "",
                }
            )
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
