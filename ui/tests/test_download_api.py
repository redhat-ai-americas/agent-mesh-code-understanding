from __future__ import annotations

import io
import json
from pathlib import Path
import tarfile
from types import SimpleNamespace

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("kubernetes")
from fastapi.testclient import TestClient

import main


class FakeClient:
    def __init__(self, payload: bytes = b"graph data", experiment_id: str = "7"):
        self.payload = payload
        self.experiment_id = experiment_id
        self.run = SimpleNamespace(
            info=SimpleNamespace(
                run_id="run-1",
                experiment_id=experiment_id,
                start_time=1_700_000_000_000,
            ),
            data=SimpleNamespace(
                tags={
                    "category": "indexing",
                    "git_slug": "acme-widget-main",
                    "multi_repo": "false",
                }
            ),
        )

    def get_experiment_by_name(self, name):
        return SimpleNamespace(experiment_id="7")

    def get_run(self, run_id):
        if run_id != "run-1":
            raise RuntimeError("missing run")
        return self.run

    def download_artifacts(self, *, run_id, path, dst_path):
        artifact = Path(dst_path) / Path(path).name
        artifact.mkdir(parents=True)
        (artifact / "index.bin").write_bytes(self.payload)
        return str(artifact)

    def list_artifacts(self, run_id, path):
        return [
            SimpleNamespace(
                path=f"{path}/index.bin",
                is_dir=False,
                file_size=len(self.payload),
            )
        ]


def configure_fake_mlflow(monkeypatch, client):
    monkeypatch.setenv("ASSET_LOADER", "mlflow")
    monkeypatch.setenv("MLFLOW_WORKSPACE", "workspace")
    monkeypatch.setattr(main.indexes, "create_mlflow_client", lambda: client)


@pytest.fixture
def workspaces(monkeypatch, tmp_path):
    created = []

    def create_workspace():
        workspace = tmp_path / f"workspace-{len(created)}"
        workspace.mkdir()
        created.append(workspace)
        return workspace

    monkeypatch.setattr(main.downloads, "create_download_workspace", create_workspace)
    return created


def test_download_api_headers_and_cleanup(monkeypatch, workspaces):
    fake = FakeClient()
    configure_fake_mlflow(monkeypatch, fake)
    response = TestClient(main.app).get("/api/indexes/run-1/download")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/gzip"
    assert response.headers["content-disposition"] == 'attachment; filename="acme-widget-main-run-1.tar.gz"'
    with tarfile.open(fileobj=io.BytesIO(response.content), mode="r:gz") as archive:
        manifest = json.load(archive.extractfile("manifest.json"))
    assert manifest["git_slug"] == "acme-widget-main"
    assert not workspaces[0].exists()


def test_download_api_returns_413_and_cleans_up(monkeypatch, workspaces):
    configure_fake_mlflow(monkeypatch, FakeClient(payload=b"0123456789"))
    monkeypatch.setenv("INDEX_DOWNLOAD_MAX_BYTES", "5")
    response = TestClient(main.app).get("/api/indexes/run-1/download")

    assert response.status_code == 413
    assert not workspaces[0].exists()
