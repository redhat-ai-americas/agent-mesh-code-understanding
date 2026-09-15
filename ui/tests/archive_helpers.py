from __future__ import annotations

import io
import json
from pathlib import Path
import tarfile
from typing import Any


INDEX_MANIFEST = {
    "run_id": "old-run",
    "git_slug": "acme-widget-main",
    "multi_repo": False,
    "created_at": "2026-01-01T00:00:00+00:00",
}


def make_index_bundle(
    path: Path,
    manifest: dict[str, Any] | None = None,
    members: list[tuple[str, bytes]] | None = None,
) -> Path:
    """Create the smallest valid index bundle used by upload tests."""
    entries = [
        (
            "manifest.json",
            json.dumps(INDEX_MANIFEST if manifest is None else manifest).encode("utf-8"),
        ),
        *(members if members is not None else [("index.bin", b"data")]),
    ]
    with tarfile.open(path, "w:gz") as archive:
        for name, content in entries:
            info = tarfile.TarInfo(name)
            info.size = len(content)
            archive.addfile(info, io.BytesIO(content))
    return path
