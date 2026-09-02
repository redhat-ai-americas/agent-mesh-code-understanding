"""Repository catalog loaded from the committed sample list plus session extras."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
_PACKAGED_CATALOG = ROOT / "repo_list.json"


def _workflow_catalog() -> Path | None:
    for parent in [ROOT, *ROOT.parents]:
        candidate = parent / "workflows/examples/code_understanding/assets/repos/repo_list.json"
        if candidate.is_file():
            return candidate
    return None


_REPO_CATALOG = _workflow_catalog()
DEFAULT_CATALOG = _PACKAGED_CATALOG if _PACKAGED_CATALOG.is_file() else (_REPO_CATALOG or _PACKAGED_CATALOG)


def _normalize(entry: dict[str, Any]) -> dict[str, str]:
    repo = (entry.get("git_repo") or "").strip()
    branch = (entry.get("git_branch") or "main").strip() or "main"
    return {"git_repo": repo, "git_branch": branch}


def repo_key(entry: dict[str, str]) -> str:
    return f"{entry['git_repo']}|{entry['git_branch']}"


def git_slug(git_repo: str, git_branch: str) -> str:
    from urllib.parse import urlparse

    path = urlparse(git_repo.strip()).path.strip("/")
    parts = path.removesuffix(".git").split("/")
    if len(parts) < 2:
        name = parts[-1] if parts else "repo"
        return f"{name}-{git_branch}"[:255]
    owner, name = parts[-2], parts[-1]
    return f"{owner}-{name}-{git_branch}"[:255]


def load_catalog(extra: list[dict[str, str]] | None = None) -> list[dict[str, str]]:
    entries: list[dict[str, str]] = []
    seen: set[str] = set()

    if DEFAULT_CATALOG.is_file():
        raw = json.loads(DEFAULT_CATALOG.read_text())
        if isinstance(raw, list):
            for item in raw:
                if isinstance(item, dict) and item.get("git_repo"):
                    normalized = _normalize(item)
                    key = repo_key(normalized)
                    if key not in seen:
                        seen.add(key)
                        entries.append(normalized)

    for item in extra or []:
        if item.get("git_repo"):
            normalized = _normalize(item)
            key = repo_key(normalized)
            if key not in seen:
                seen.add(key)
                entries.append(normalized)

    return entries


DEFAULT_REPO = {
    "git_repo": "https://github.com/agapebondservant/tic-tac-toe-sample",
    "git_branch": "main",
}


def default_repo_entry() -> dict[str, str] | None:
    """Return tic-tac-toe sample when present, else env preselect, else first catalog entry."""
    catalog = load_catalog()
    for item in catalog:
        if "tic-tac-toe-sample" in item["git_repo"]:
            return item
    pre = env_preselect()
    if pre:
        return _normalize(pre)
    return catalog[0] if catalog else None


def env_preselect() -> dict[str, str] | None:
    repo = os.getenv("GIT_REPO", "").strip()
    if not repo:
        return None
    return {
        "git_repo": repo,
        "git_branch": os.getenv("GIT_BRANCH", "main").strip() or "main",
    }
