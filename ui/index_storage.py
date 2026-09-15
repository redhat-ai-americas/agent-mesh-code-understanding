"""Shared workspace and size-limit helpers for index bundle requests."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import tempfile


DEFAULT_MAX_INDEX_BYTES = 5 * 1024**3
INDEX_MAX_BYTES_ENV_NAME = "INDEX_DOWNLOAD_MAX_BYTES"


def configured_max_index_bytes() -> int:
    """Return the configured maximum index bundle size, defaulting to 5 GiB."""
    raw_value = os.getenv(INDEX_MAX_BYTES_ENV_NAME, "").strip()
    if not raw_value:
        return DEFAULT_MAX_INDEX_BYTES
    try:
        value = int(raw_value)
    except ValueError:
        return DEFAULT_MAX_INDEX_BYTES
    return value if value > 0 else DEFAULT_MAX_INDEX_BYTES


def create_index_workspace() -> Path:
    """Create the temporary workspace used for one index request."""
    return Path(tempfile.mkdtemp(prefix="code-understanding-index-"))


def cleanup_index_workspace(path: str | Path) -> None:
    """Remove a completed or failed index request workspace."""
    shutil.rmtree(path, ignore_errors=True)
