"""Create and stream downloadable GraphRAG index bundles."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
import re
import shutil
import tarfile
import tempfile
from typing import Any


DEFAULT_MAX_DOWNLOAD_BYTES = 5 * 1024**3
MAX_DOWNLOAD_BYTES_ENV_NAME = "INDEX_DOWNLOAD_MAX_BYTES"


class DownloadTooLargeError(ValueError):
    """Raised when an index bundle exceeds the configured download limit."""


def configured_max_download_bytes() -> int:
    """Return the configured maximum bundle size, defaulting to 5 GiB."""
    raw_value = os.getenv(MAX_DOWNLOAD_BYTES_ENV_NAME, "").strip()
    if not raw_value:
        return DEFAULT_MAX_DOWNLOAD_BYTES
    try:
        value = int(raw_value)
    except ValueError:
        return DEFAULT_MAX_DOWNLOAD_BYTES
    return value if value > 0 else DEFAULT_MAX_DOWNLOAD_BYTES


def _safe_filename_component(value: str, fallback: str) -> str:
    component = re.sub(r"[^A-Za-z0-9._-]+", "-", str(value or "")).strip(".-")
    return component or fallback


def index_archive_filename(metadata: dict[str, Any]) -> str:
    """Return a deterministic, safe filename for an index bundle."""
    prefix = "multi-repo" if metadata.get("multi_repo") else metadata.get("git_slug")
    prefix = _safe_filename_component(str(prefix or "index"), "index")
    run_id = _safe_filename_component(str(metadata.get("run_id") or "run"), "run")
    return f"{prefix}-{run_id}.tar.gz"


def create_download_workspace() -> Path:
    """Create the temporary workspace used for one download request."""
    return Path(tempfile.mkdtemp(prefix="code-understanding-index-"))


def cleanup_download_workspace(path: str | Path) -> None:
    """Remove a completed or failed download workspace."""
    shutil.rmtree(path, ignore_errors=True)


def _directory_size(directory: Path, limit: int | None = None) -> int:
    total = 0
    for root, _, files in os.walk(directory, followlinks=False):
        for filename in files:
            path = Path(root) / filename
            if path.is_symlink():
                continue
            total += path.stat().st_size
            if limit is not None and total > limit:
                return total
    return total


def _artifact_size(client: Any, run_id: str, artifact_path: str, limit: int) -> int:
    """Return the MLflow-reported size of an artifact directory, up to ``limit``."""
    total = 0
    pending = [artifact_path]

    while pending:
        for artifact in client.list_artifacts(run_id, pending.pop()):
            if artifact.is_dir:
                pending.append(artifact.path)
                continue
            if artifact.file_size is None:
                raise DownloadTooLargeError(
                    f"MLflow did not report a size for index artifact: {artifact.path}"
                )

            total += artifact.file_size
            if total > limit:
                raise DownloadTooLargeError(
                    f"Index artifact exceeds the maximum download size of {limit} bytes."
                )
    return total


def _download_index_directory(
    client: Any,
    run_id: str,
    artifact_path: str,
    destination: Path,
) -> Path:
    """Download one validated artifact directory into the request workspace."""
    destination.mkdir(parents=True, exist_ok=True)
    downloaded = Path(
        client.download_artifacts(
            run_id=run_id,
            path=artifact_path,
            dst_path=str(destination),
        )
    )
    if not downloaded.is_dir():
        raise FileNotFoundError(
            f"MLflow artifact directory was not downloaded: {artifact_path}"
        )
    return downloaded


def _write_manifest(path: Path, metadata: dict[str, Any]) -> None:
    manifest = {
        "run_id": metadata["run_id"],
        "git_slug": metadata["git_slug"],
        "multi_repo": bool(metadata["multi_repo"]),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _add_directory_contents(archive: tarfile.TarFile, directory: Path) -> None:
    """Add directory contents at the archive root in stable path order."""
    entries = sorted(
        directory.rglob("*"),
        key=lambda entry: entry.relative_to(directory).as_posix(),
    )
    for entry in entries:
        relative = entry.relative_to(directory).as_posix()
        if relative == "manifest.json":
            continue
        archive.add(entry, arcname=relative, recursive=False)


def create_index_archive(
    client: Any,
    metadata: dict[str, Any],
    workspace: Path,
    max_bytes: int,
) -> tuple[Path, str]:
    """Download and archive an index without buffering it in process memory."""
    artifact_path = str(metadata["artifact_path"])
    run_id = str(metadata["run_id"])
    _artifact_size(client, run_id, artifact_path, max_bytes)
    download_root = workspace / "artifact"
    source_directory = _download_index_directory(
        client,
        run_id,
        artifact_path,
        download_root,
    )
    artifact_size = _directory_size(source_directory, limit=max_bytes)
    if artifact_size > max_bytes:
        raise DownloadTooLargeError(
            f"Index artifact is {artifact_size} bytes; the maximum download size is {max_bytes} bytes."
        )

    filename = index_archive_filename(metadata)
    manifest_path = workspace / "manifest.json"
    archive_path = workspace / filename
    _write_manifest(manifest_path, metadata)
    with tarfile.open(archive_path, mode="w:gz") as archive:
        archive.add(manifest_path, arcname="manifest.json", recursive=False)
        _add_directory_contents(archive, source_directory)

    archive_size = archive_path.stat().st_size
    if archive_size > max_bytes:
        raise DownloadTooLargeError(
            f"Generated index archive is {archive_size} bytes; the maximum download size is {max_bytes} bytes."
        )
    return archive_path, filename
