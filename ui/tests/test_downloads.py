from __future__ import annotations

import json
from pathlib import Path
import tarfile
from types import SimpleNamespace

import pytest

import downloads


class FakeArtifactClient:
    def __init__(self, payload: bytes = b"graph data"):
        self.payload = payload
        self.calls = []

    def download_artifacts(self, *, run_id, path, dst_path):
        self.calls.append({"run_id": run_id, "path": path, "dst_path": dst_path})
        artifact = Path(dst_path) / Path(path).name
        (artifact / "lancedb").mkdir(parents=True)
        (artifact / "lancedb" / "part-0001.bin").write_bytes(self.payload)
        return str(artifact)

    def list_artifacts(self, run_id, path):
        if path.endswith("/lancedb"):
            return [
                SimpleNamespace(
                    path=f"{path}/part-0001.bin",
                    is_dir=False,
                    file_size=len(self.payload),
                )
            ]
        return [SimpleNamespace(path=f"{path}/lancedb", is_dir=True, file_size=None)]


def metadata(multi_repo: bool = False):
    return {
        "run_id": "run-1",
        "git_slug": "acme-widget-main" if not multi_repo else "",
        "multi_repo": multi_repo,
        "artifact_path": (
            "results/datasets/repos/acme-widget-main"
            if not multi_repo
            else "results/datasets/repos/multi-repo"
        ),
    }


def test_archive_contains_manifest_and_index_files(tmp_path):
    client = FakeArtifactClient()
    archive_path, filename = downloads.create_index_archive(
        client, metadata(), tmp_path / "workspace", 1024 * 1024
    )

    assert filename == "acme-widget-main-run-1.tar.gz"
    assert client.calls[0]["path"] == "results/datasets/repos/acme-widget-main"
    with tarfile.open(archive_path, "r:gz") as archive:
        names = archive.getnames()
        assert "manifest.json" in names
        assert "lancedb/part-0001.bin" in names
        manifest = json.load(archive.extractfile("manifest.json"))

    assert manifest["run_id"] == "run-1"
    assert manifest["git_slug"] == "acme-widget-main"
    assert manifest["multi_repo"] is False
    assert manifest["created_at"]


def test_multi_repo_archive_filename():
    assert downloads.index_archive_filename(metadata(multi_repo=True)) == "multi-repo-run-1.tar.gz"


def test_size_limit_is_enforced(tmp_path):
    client = FakeArtifactClient(payload=b"0123456789")
    with pytest.raises(downloads.DownloadTooLargeError):
        downloads.create_index_archive(client, metadata(), tmp_path / "workspace", 5)
    assert client.calls == []
