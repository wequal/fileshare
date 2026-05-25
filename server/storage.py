from __future__ import annotations

import mimetypes
import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import aiofiles
from fastapi import UploadFile

from server.acl import PathAccessError, ResolvedPath, resolve_path
from server.models import User

IMAGE_EXT = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".heic", ".heif", ".bmp"}
VIDEO_EXT = {".mov", ".mp4", ".m4v", ".avi", ".mkv"}


def _entry_info(path: Path, logical_base: str, relative: str) -> Dict[str, Any]:
    stat = path.stat()
    name = path.name
    rel = f"{relative}/{name}".strip("/") if relative else name
    logical = f"{logical_base.rstrip('/')}/{rel}".replace("//", "/")
    if not logical.startswith("/"):
        logical = "/" + logical

    ext = path.suffix.lower()
    entry_type = "file"
    if path.is_dir():
        entry_type = "directory"
    elif ext in IMAGE_EXT:
        entry_type = "image"
    elif ext in VIDEO_EXT:
        entry_type = "video"

    mime, _ = mimetypes.guess_type(name)
    return {
        "name": name,
        "path": logical,
        "type": entry_type,
        "size": stat.st_size if path.is_file() else None,
        "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
        "mime_type": mime,
    }


def list_directory(user: User, path: str) -> Dict[str, Any]:
    resolved = resolve_path(user, path, need_read=True)
    target = resolved.physical_path

    if not target.exists():
        raise PathAccessError("Path not found", 404)
    if not target.is_dir():
        raise PathAccessError("Not a directory", 400)

    entries: List[Dict[str, Any]] = []
    try:
        items = sorted(target.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
    except OSError as e:
        raise PathAccessError(str(e), 500) from e

    for item in items:
        entries.append(
            _entry_info(item, resolved.grant.logical_path, resolved.relative_path)
        )

    return {
        "path": resolved.logical_path,
        "entries": entries,
        "can_write": resolved.grant.can_write,
    }


def unique_dest_path(directory: Path, filename: str) -> Path:
    """Pick a non-colliding path (iPhone often reuses names like image.jpg)."""
    base = directory.resolve()
    dest = (base / filename).resolve()
    try:
        dest.relative_to(base)
    except ValueError:
        raise PathAccessError("Invalid filename", 400) from None
    if not dest.exists():
        return dest
    stem = Path(filename).stem
    suffix = Path(filename).suffix
    for n in range(1, 10_000):
        candidate = (base / f"{stem} ({n}){suffix}").resolve()
        if not candidate.exists():
            return candidate
    raise PathAccessError("Too many files with the same name", 400)


def get_download_path(user: User, path: str) -> ResolvedPath:
    resolved = resolve_path(user, path, need_read=True)
    if not resolved.physical_path.is_file():
        raise PathAccessError("File not found", 404)
    return resolved


async def save_upload(
    user: User,
    path: str,
    file: UploadFile,
) -> Dict[str, Any]:
    """Simple single-request upload to logical directory path."""
    dir_resolved = resolve_path(user, path, need_write=True)
    if not dir_resolved.physical_path.exists():
        dir_resolved.physical_path.mkdir(parents=True, exist_ok=True)
    if not dir_resolved.physical_path.is_dir():
        raise PathAccessError("Target is not a directory", 400)

    filename = Path(file.filename or "upload").name
    if ".." in filename or filename in (".", ""):
        raise PathAccessError("Invalid filename", 400)

    dest = unique_dest_path(dir_resolved.physical_path, filename)

    async with aiofiles.open(dest, "wb") as out:
        while True:
            chunk = await file.read(1024 * 1024)
            if not chunk:
                break
            await out.write(chunk)

    size = dest.stat().st_size
    if size == 0:
        dest.unlink(missing_ok=True)
        raise PathAccessError("Uploaded file is empty (0 bytes)", 400)

    filename = dest.name
    rel = f"{dir_resolved.relative_path}/{filename}".strip("/")
    logical = f"{dir_resolved.grant.logical_path.rstrip('/')}/{rel}".replace("//", "/")
    if not logical.startswith("/"):
        logical = "/" + logical

    return {
        "path": logical,
        "size": size,
        "name": filename,
    }


def delete_path(user: User, path: str) -> None:
    resolved = resolve_path(user, path, need_write=True)
    target = resolved.physical_path
    if not target.exists():
        raise PathAccessError("Path not found", 404)
    if target.is_dir():
        shutil.rmtree(target)
    else:
        target.unlink()


def mkdir(user: User, path: str) -> Dict[str, Any]:
    resolved = resolve_path(user, path, need_write=True)
    target = resolved.physical_path
    target.mkdir(parents=True, exist_ok=True)
    return {"path": resolved.logical_path, "created": True}
