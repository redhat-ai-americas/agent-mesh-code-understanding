from __future__ import annotations

import tarfile

import pytest

import uploads
from archive_helpers import make_index_bundle


def test_extracts_index_bundle(tmp_path):
    metadata = uploads.extract_uploaded_index(
        make_index_bundle(tmp_path / "index.tar.gz"),
        tmp_path / "artifact",
        1024,
    )

    assert metadata == {"git_slug": "acme-widget-main", "multi_repo": False}
    assert (tmp_path / "artifact" / "index.bin").read_bytes() == b"data"


@pytest.mark.parametrize(
    ("manifest", "message"),
    [
        ({"git_slug": "acme-widget-main", "multi_repo": "false"}, "multi_repo must be a boolean"),
        ({"git_slug": "../outside", "multi_repo": False}, "safe path component"),
        ({"multi_repo": False}, "git_slug must be a string"),
    ],
)
def test_rejects_invalid_manifest(tmp_path, manifest, message):
    with pytest.raises(uploads.IndexArchiveError, match=message):
        uploads.extract_uploaded_index(
            make_index_bundle(tmp_path / "index.tar.gz", manifest),
            tmp_path / "artifact",
            1024,
        )


@pytest.mark.parametrize("member_name", ["../outside", "/outside"])
def test_rejects_unsafe_member_paths(tmp_path, member_name):
    with pytest.raises(uploads.IndexArchiveError, match="unsafe member path"):
        uploads.extract_uploaded_index(
            make_index_bundle(
                tmp_path / "index.tar.gz",
                members=[(member_name, b"no")],
            ),
            tmp_path / "artifact",
            1024,
        )


def test_rejects_duplicate_member_paths(tmp_path):
    with pytest.raises(uploads.IndexArchiveError, match="duplicate"):
        uploads.extract_uploaded_index(
            make_index_bundle(
                tmp_path / "duplicate.tar.gz",
                members=[("index.bin", b"one"), ("index.bin", b"two")],
            ),
            tmp_path / "artifact",
            1024,
        )


def test_rejects_archive_links(tmp_path):
    archive_path = tmp_path / "link.tar.gz"
    with tarfile.open(archive_path, "w:gz") as archive:
        info = tarfile.TarInfo("index-link")
        info.type = tarfile.SYMTYPE
        info.linkname = "index.bin"
        archive.addfile(info)

    with pytest.raises(uploads.IndexArchiveError, match="only regular"):
        uploads.extract_uploaded_index(archive_path, tmp_path / "artifact", 1024)


def test_rejects_extracted_size_limit(tmp_path):
    with pytest.raises(uploads.IndexArchiveTooLargeError):
        uploads.extract_uploaded_index(
            make_index_bundle(
                tmp_path / "large.tar.gz",
                members=[("index.bin", b"012345")],
            ),
            tmp_path / "artifact",
            5,
        )


def test_rejects_missing_manifest(tmp_path):
    archive_path = tmp_path / "empty.tar.gz"
    with tarfile.open(archive_path, "w:gz"):
        pass

    with pytest.raises(uploads.IndexArchiveError, match="missing manifest"):
        uploads.extract_uploaded_index(archive_path, tmp_path / "artifact", 1024)


def test_rejects_malformed_archive(tmp_path):
    archive_path = tmp_path / "not-a-tar.gz"
    archive_path.write_bytes(b"not a gzip archive")

    with pytest.raises(uploads.IndexArchiveError, match="valid gzip tar"):
        uploads.extract_uploaded_index(archive_path, tmp_path / "artifact", 1024)
