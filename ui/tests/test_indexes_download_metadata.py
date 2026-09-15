from __future__ import annotations

from types import SimpleNamespace

import pytest

import indexes


def make_run(
    run_id: str = "run-1",
    experiment_id: str = "7",
    *,
    category: str = "indexing",
    git_slug: str = "acme-widget-main",
    multi_repo: str = "false",
    uploaded: str = "false",
    start_time: int = 1_700_000_000_000,
):
    tags = {
        "category": category,
        "git_slug": git_slug,
        "multi_repo": multi_repo,
        "uploaded": uploaded,
    }
    return SimpleNamespace(
        info=SimpleNamespace(
            run_id=run_id,
            experiment_id=experiment_id,
            start_time=start_time,
        ),
        data=SimpleNamespace(tags=tags),
    )


class FakeClient:
    def __init__(self, run=None, experiment_id="7"):
        self.run = run
        self.experiment_id = experiment_id

    def get_experiment_by_name(self, name):
        return SimpleNamespace(experiment_id=self.experiment_id)

    def get_run(self, run_id):
        if self.run is None:
            raise RuntimeError("missing run")
        return self.run


@pytest.mark.parametrize(
    ("slug", "multi_repo", "expected"),
    [
        ("acme-widget-main", False, "results/datasets/repos/acme-widget-main"),
        ("ignored-slug", True, "results/datasets/repos/multi-repo"),
    ],
    ids=["single_repo", "multi_repo"],
)
def test_index_artifact_path(slug, multi_repo, expected):
    assert indexes.index_artifact_path(slug, multi_repo=multi_repo) == expected


def test_successful_run_validation(monkeypatch):
    monkeypatch.setenv("MLFLOW_WORKSPACE", "workspace")
    metadata = indexes.validate_index_run(FakeClient(make_run()), "run-1")

    assert metadata == {
        "run_id": "run-1",
        "git_slug": "acme-widget-main",
        "multi_repo": False,
        "uploaded": False,
        "indexed_at": "2023-11-14T22:13:20+00:00",
        "artifact_path": "results/datasets/repos/acme-widget-main",
    }


@pytest.mark.parametrize(
    "client,run_id",
    [
        (FakeClient(), "missing"),
        (FakeClient(make_run(experiment_id="other")), "run-1"),
        (FakeClient(make_run(category="analysis")), "run-1"),
        (FakeClient(make_run(git_slug="../outside")), "run-1"),
    ],
    ids=["missing_run", "wrong_experiment", "wrong_category", "unsafe_artifact_path"],
)
def test_invalid_runs_are_rejected(client, run_id):
    with pytest.raises(indexes.IndexRunValidationError):
        indexes.validate_index_run(client, run_id)


def test_multi_repository_metadata_uses_fixed_artifact_path(monkeypatch):
    monkeypatch.setenv("MLFLOW_WORKSPACE", "workspace")
    run = make_run(git_slug="", multi_repo="true")
    metadata = indexes.validate_index_run(FakeClient(run), "run-1")

    assert metadata["multi_repo"] is True
    assert metadata["uploaded"] is False
    assert metadata["artifact_path"] == "results/datasets/repos/multi-repo"


def test_uploaded_run_metadata_exposes_upload_tag(monkeypatch):
    monkeypatch.setenv("MLFLOW_WORKSPACE", "workspace")
    metadata = indexes.validate_index_run(
        FakeClient(make_run(uploaded="true")),
        "run-1",
    )

    assert metadata["uploaded"] is True


def test_discovery_keeps_newest_run_for_slug(monkeypatch):
    class DiscoveryClient:
        def get_experiment_by_name(self, name):
            return SimpleNamespace(experiment_id="7")

        def search_runs(self, **kwargs):
            assert kwargs["order_by"] == ["attributes.start_time DESC"]
            return [
                make_run("new", uploaded="true", start_time=1_700_000_001_000),
                make_run("old", start_time=1_700_000_000_000),
            ]

    monkeypatch.setenv("ASSET_LOADER", "mlflow")
    monkeypatch.setenv("MLFLOW_WORKSPACE", "workspace")
    monkeypatch.setattr(indexes, "create_mlflow_client", DiscoveryClient)
    data = indexes.list_indexed_repos()

    assert [item["run_id"] for item in data["indexes"]] == ["new"]
    assert data["indexes"][0]["uploaded"] is True
