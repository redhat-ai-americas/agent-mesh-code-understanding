"""Validate and safely unpack uploaded GraphRAG index bundles."""

from __future__ import annotations

import json
import os
from pathlib import Path
import posixpath
import re
import tarfile
from typing import Any, BinaryIO


class IndexArchiveError(ValueError):
    """Raised when an uploaded archive is not a safe index bundle."""


class IndexArchiveTooLargeError(IndexArchiveError):
    """Raised when compressed or extracted upload data exceeds the limit."""


ArchiveSource = Path | str | os.PathLike[str] | BinaryIO


def _open_archive(source: ArchiveSource, max_bytes: int) -> tarfile.TarFile:
    if isinstance(source, (str, bytes, os.PathLike)):
        archive_path = Path(source)
        archive_size = archive_path.stat().st_size
        if archive_size > max_bytes:
            raise IndexArchiveTooLargeError(
                f"Uploaded archive exceeds the maximum size of {max_bytes} bytes."
            )
        return tarfile.open(name=os.fspath(archive_path), mode="r:gz")

    try:
        source.seek(0, 2)
        archive_size = source.tell()
        source.seek(0)
    except (AttributeError, OSError, TypeError):
        source.seek(0)
    else:
        if archive_size > max_bytes:
            raise IndexArchiveTooLargeError(
                f"Uploaded archive exceeds the maximum size of {max_bytes} bytes."
            )
    return tarfile.open(fileobj=source, mode="r:gz")


def _member_path(member_name: str) -> str:
    """Return a normalized member path, rejecting unsafe extraction targets."""
    if (
        not member_name
        or "\\" in member_name
        or member_name.startswith("/")
        or re.match(r"^[A-Za-z]:", member_name)
    ):
        raise IndexArchiveError("Archive contains an unsafe member path")
    normalized = posixpath.normpath(member_name).removesuffix("/")
    parts = normalized.split("/")
    if normalized in {"", ".", ".."} or normalized.startswith("../") or any(
        part in {"", ".", ".."} for part in parts
    ):
        raise IndexArchiveError("Archive contains an unsafe member path")
    return normalized


def validate_bundle_manifest(value: Any) -> dict[str, Any]:
    """Validate the slug and multi-repository state required for an upload."""
    if not isinstance(value, dict):
        raise IndexArchiveError("manifest.json must contain a JSON object")
    if not isinstance(value.get("multi_repo"), bool):
        raise IndexArchiveError("manifest.json multi_repo must be a boolean")

    multi_repo = value["multi_repo"]
    slug = value.get("git_slug")
    if not isinstance(slug, str):
        raise IndexArchiveError("manifest.json git_slug must be a string")
    if multi_repo:
        return {"git_slug": slug, "multi_repo": True}

    if (
        not slug
        or slug != slug.strip()
        or len(slug) > 255
        or any(ord(char) < 32 or char.isspace() for char in slug)
        or "/" in slug
        or "\\" in slug
        or slug in {".", ".."}
    ):
        raise IndexArchiveError("manifest.json git_slug is not a safe path component")
    return {"git_slug": slug, "multi_repo": False}


def extract_uploaded_index(
    archive_source: ArchiveSource,
    destination: Path,
    max_bytes: int,
) -> dict[str, Any]:
    """Inspect then safely extract a bundle, bounded by regular-file content."""
    try:
        with _open_archive(archive_source, max_bytes) as archive:
            members = archive.getmembers()
            seen: set[str] = set()
            manifest_member: tarfile.TarInfo | None = None
            declared_size = 0
            for member in members:
                normalized = _member_path(member.name)
                if normalized in seen:
                    raise IndexArchiveError("Archive contains duplicate member paths")
                seen.add(normalized)
                if not (member.isfile() or member.isdir()):
                    raise IndexArchiveError("Archive may contain only regular files and directories")
                if member.isfile():
                    declared_size += member.size
                    if declared_size > max_bytes:
                        raise IndexArchiveTooLargeError(
                            f"Extracted archive content exceeds the maximum size of {max_bytes} bytes."
                        )
                if normalized == "manifest.json":
                    if not member.isfile():
                        raise IndexArchiveError("manifest.json must be a regular file")
                    manifest_member = member
            if manifest_member is None:
                raise IndexArchiveError("Archive is missing manifest.json")
            source = archive.extractfile(manifest_member)
            if source is None:
                raise IndexArchiveError("Archive manifest cannot be read")
            try:
                manifest_bytes = source.read()
            finally:
                source.close()
            try:
                manifest = json.loads(manifest_bytes.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise IndexArchiveError("manifest.json is not valid UTF-8 JSON") from exc
            metadata = validate_bundle_manifest(manifest)

            destination.mkdir(parents=True, exist_ok=False)
            extracted_size = 0
            for member in members:
                relative = _member_path(member.name)
                if relative == "manifest.json":
                    continue
                output = destination / relative
                if member.isdir():
                    output.mkdir(parents=True, exist_ok=True)
                    continue
                output.parent.mkdir(parents=True, exist_ok=True)
                source = archive.extractfile(member)
                if source is None:
                    raise IndexArchiveError(f"Archive member cannot be read: {relative}")
                try:
                    with output.open("xb") as target:
                        while chunk := source.read(1024 * 1024):
                            extracted_size += len(chunk)
                            if extracted_size > max_bytes:
                                raise IndexArchiveTooLargeError(
                                    f"Extracted archive content exceeds the maximum size of {max_bytes} bytes."
                                )
                            target.write(chunk)
                finally:
                    source.close()
            return metadata
    except IndexArchiveError:
        raise
    except (tarfile.TarError, OSError, EOFError) as exc:
        raise IndexArchiveError("Uploaded file is not a valid gzip tar archive") from exc
