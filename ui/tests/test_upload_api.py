from __future__ import annotations

from types import SimpleNamespace

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("kubernetes")
from fastapi.testclient import TestClient

import main
from archive_helpers import make_index_bundle


class UploadClient:
    def __init__(self, *, fail_upload: bool = False):
        self.fail_upload = fail_upload
        self.run_tags = None
        self.artifact_path = None
        self.terminated = None

    def get_experiment_by_name(self, name):
        return SimpleNamespace(experiment_id="7")

    def create_run(self, experiment_id, tags):
        self.run_tags = tags
        return SimpleNamespace(info=SimpleNamespace(run_id="uploaded-run"))

    def log_artifacts(self, run_id, directory, artifact_path):
        self.artifact_path = artifact_path
        if self.fail_upload:
            raise RuntimeError("storage unavailable")

    def set_terminated(self, run_id, status):
        self.terminated = (run_id, status)


@pytest.fixture
def upload_workspaces(monkeypatch, tmp_path):
    created = []

    def create_workspace():
        workspace = tmp_path / f"workspace-{len(created)}"
        workspace.mkdir()
        created.append(workspace)
        return workspace

    monkeypatch.setattr(main.downloads, "create_download_workspace", create_workspace)
    return created


def configure_fake_mlflow(monkeypatch, client):
    monkeypatch.setenv("ASSET_LOADER", "mlflow")
    monkeypatch.setenv("MLFLOW_WORKSPACE", "workspace")
    monkeypatch.setattr(main.indexes, "create_mlflow_client", lambda: client)


def post_bundle(path):
    with path.open("rb") as source:
        return TestClient(main.app).post(
            "/api/indexes/upload",
            files={"file": (path.name, source, "application/gzip")},
        )


def test_upload_api_logs_index_and_cleans_workspace(monkeypatch, tmp_path, upload_workspaces):
    client = UploadClient()
    configure_fake_mlflow(monkeypatch, client)

    response = post_bundle(make_index_bundle(tmp_path / "index.tar.gz"))

    assert response.status_code == 200
    payload = response.json()
    assert payload["git_slug"] == "acme-widget-main"
    assert payload["multi_repo"] is False
    assert payload["uploaded"] is True
    assert payload["run_id"] == "uploaded-run"
    assert payload["indexed_at"]
    assert set(payload) == {"git_slug", "multi_repo", "uploaded", "run_id", "indexed_at"}
    assert client.run_tags == {
        "category": "indexing",
        "git_slug": "acme-widget-main",
        "multi_repo": "False",
        "uploaded": "true",
    }
    assert client.artifact_path == "results/datasets/repos/acme-widget-main"
    assert client.terminated == ("uploaded-run", "FINISHED")
    assert not upload_workspaces[0].exists()


def test_upload_api_accepts_multi_repo_index(monkeypatch, tmp_path, upload_workspaces):
    client = UploadClient()
    configure_fake_mlflow(monkeypatch, client)
    archive = make_index_bundle(
        tmp_path / "multi.tar.gz",
        {"git_slug": "", "multi_repo": True},
    )

    response = post_bundle(archive)

    assert response.status_code == 200
    assert response.json()["multi_repo"] is True
    assert response.json()["uploaded"] is True
    assert client.run_tags == {
        "category": "indexing",
        "git_slug": "",
        "multi_repo": "True",
        "uploaded": "true",
    }
    assert client.artifact_path == "results/datasets/repos/multi-repo"
    assert not upload_workspaces[0].exists()


def test_upload_api_requires_mlflow(monkeypatch, tmp_path):
    monkeypatch.setenv("ASSET_LOADER", "local")

    response = post_bundle(make_index_bundle(tmp_path / "index.tar.gz"))

    assert response.status_code == 503
    assert "ASSET_LOADER=mlflow" in response.json()["detail"]


def test_upload_api_rejects_non_tar_gz(monkeypatch):
    monkeypatch.setenv("ASSET_LOADER", "mlflow")

    response = TestClient(main.app).post(
        "/api/indexes/upload",
        files={"file": ("index.zip", b"not-a-tar", "application/zip")},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Upload one .tar.gz index bundle."


def test_upload_api_reports_mlflow_failure(monkeypatch, tmp_path, upload_workspaces):
    configure_fake_mlflow(monkeypatch, UploadClient(fail_upload=True))

    response = post_bundle(make_index_bundle(tmp_path / "index.tar.gz"))

    assert response.status_code == 502
    assert "Unable to upload index artifact to MLflow" in response.json()["detail"]
    assert not upload_workspaces[0].exists()


def test_upload_api_enforces_archive_size_limit(monkeypatch, tmp_path, upload_workspaces):
    configure_fake_mlflow(monkeypatch, UploadClient())
    monkeypatch.setenv("INDEX_DOWNLOAD_MAX_BYTES", "1")

    response = post_bundle(make_index_bundle(tmp_path / "index.tar.gz"))

    assert response.status_code == 413
    assert not upload_workspaces[0].exists()
