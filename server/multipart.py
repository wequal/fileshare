from __future__ import annotations

import json
import math
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import aiofiles

from server.acl import PathAccessError, resolve_path
from server.storage import unique_dest_path
from server.config import get_settings
from server.database import db_cursor
from server.models import UploadSession, User

_UPLOADS_TMP = ".uploads"


def _tmp_dir() -> Path:
    settings = get_settings()
    d = settings.data_root_path / _UPLOADS_TMP
    d.mkdir(parents=True, exist_ok=True)
    return d


def _session_dir(upload_id: str) -> Path:
    return _tmp_dir() / upload_id


def _is_mobile_user_agent(user_agent: str) -> bool:
    ua = user_agent.lower()
    return any(token in ua for token in ("iphone", "ipad", "ipod", "android", "mobile"))


def initiate_upload(
    user: User,
    logical_dir: str,
    relative_filename: str,
    total_size: int,
    *,
    mobile: bool = False,
) -> Dict[str, Any]:
    settings = get_settings()
    dir_resolved = resolve_path(user, logical_dir, need_write=True)

    filename = Path(relative_filename).name
    if not filename or ".." in relative_filename or ".." in filename:
        raise PathAccessError("Invalid filename", 400)

    rel = f"{dir_resolved.relative_path}/{filename}".strip("/")
    chunk_size = (
        settings.mobile_chunk_size_bytes if mobile else settings.chunk_size_bytes
    )
    # total_parts=0 means size unknown (iOS Safari may report video size as 0)
    total_parts = (
        0 if total_size <= 0 else max(1, math.ceil(total_size / chunk_size))
    )

    upload_id = str(uuid.uuid4())
    expires = datetime.now(timezone.utc) + timedelta(
        hours=settings.upload_session_expire_hours
    )

    with db_cursor() as cur:
        cur.execute(
            """
            INSERT INTO upload_sessions
            (upload_id, user_id, logical_path, relative_path, filename, total_size,
             chunk_size, total_parts, parts_received, status, expires_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, '[]', 'active', ?)
            """,
            (
                upload_id,
                user.id,
                dir_resolved.grant.logical_path,
                rel,
                filename,
                total_size,
                chunk_size,
                total_parts,
                expires.isoformat(),
            ),
        )

    session_dir = _session_dir(upload_id)
    session_dir.mkdir(parents=True, exist_ok=True)

    return {
        "upload_id": upload_id,
        "chunk_size": chunk_size,
        "total_parts": total_parts,
        "unknown_size": total_parts == 0,
        "expires_at": expires.isoformat(),
    }


def get_session(upload_id: str, user_id: int) -> UploadSession:
    with db_cursor() as cur:
        cur.execute(
            "SELECT * FROM upload_sessions WHERE upload_id = ? AND user_id = ?",
            (upload_id, user_id),
        )
        row = cur.fetchone()
    if not row:
        raise PathAccessError("Upload session not found", 404)
    session = UploadSession.from_row(row)
    if session.status != "active":
        raise PathAccessError("Upload session is not active", 400)
    return session


def get_session_status(upload_id: str, user: User) -> Dict[str, Any]:
    session = get_session(upload_id, user.id)
    return {
        "upload_id": session.upload_id,
        "filename": session.filename,
        "total_size": session.total_size,
        "chunk_size": session.chunk_size,
        "total_parts": session.total_parts,
        "parts_received": sorted(session.parts_received),
        "status": session.status,
    }


async def save_part(
    user: User,
    upload_id: str,
    part_number: int,
    data: bytes,
) -> Dict[str, Any]:
    session = get_session(upload_id, user.id)
    if part_number < 1:
        raise PathAccessError("Invalid part number", 400)

    if session.total_parts == 0:
        # Unknown total size: accept sequential chunks up to chunk_size.
        if not data:
            raise PathAccessError("Empty part", 400)
        if len(data) > session.chunk_size:
            raise PathAccessError(
                f"Part too large: max {session.chunk_size} bytes", 400
            )
    else:
        if part_number > session.total_parts:
            raise PathAccessError("Invalid part number", 400)

        expected_len = session.chunk_size
        if part_number == session.total_parts:
            remainder = session.total_size % session.chunk_size
            if remainder > 0:
                expected_len = remainder
            elif session.total_size == 0:
                expected_len = 0

        if len(data) != expected_len and not (
            part_number == session.total_parts and len(data) <= session.chunk_size
        ):
            if session.total_size > 0 and len(data) != expected_len:
                raise PathAccessError(
                    f"Part size mismatch: expected {expected_len}, got {len(data)}",
                    400,
                )

    part_path = _session_dir(upload_id) / f"part_{part_number:05d}"
    async with aiofiles.open(part_path, "wb") as f:
        await f.write(data)

    parts = list(set(session.parts_received + [part_number]))
    with db_cursor() as cur:
        cur.execute(
            """
            UPDATE upload_sessions SET parts_received = ? WHERE upload_id = ?
            """,
            (json.dumps(sorted(parts)), upload_id),
        )

    return {
        "part_number": part_number,
        "parts_received": sorted(parts),
        "complete": session.total_parts > 0 and len(parts) == session.total_parts,
    }


async def complete_upload(
    user: User, upload_id: str, final_parts: Optional[int] = None
) -> Dict[str, Any]:
    session = get_session(upload_id, user.id)
    parts = sorted(session.parts_received)

    if session.total_parts == 0:
        if not final_parts or final_parts < 1:
            raise PathAccessError("final_parts required for unknown-size upload", 400)
        expected = list(range(1, final_parts + 1))
        if parts != expected:
            raise PathAccessError(
                f"Missing parts: have {len(parts)}, need {final_parts}",
                400,
            )
        total_parts = final_parts
    else:
        total_parts = session.total_parts
        if len(parts) != total_parts:
            raise PathAccessError(
                f"Missing parts: have {len(parts)}, need {total_parts}",
                400,
            )

    dir_logical = session.logical_path
    parent_rel = str(Path(session.relative_path).parent)
    if parent_rel == ".":
        upload_dir = dir_logical
    else:
        upload_dir = f"{dir_logical.rstrip('/')}/{parent_rel}"

    dir_resolved = resolve_path(user, upload_dir, need_write=True)
    dest_dir = dir_resolved.physical_path
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = unique_dest_path(dest_dir, session.filename)

    session_dir = _session_dir(upload_id)
    async with aiofiles.open(dest, "wb") as out:
        for n in range(1, total_parts + 1):
            part_path = session_dir / f"part_{n:05d}"
            async with aiofiles.open(part_path, "rb") as inp:
                while True:
                    chunk = await inp.read(1024 * 1024)
                    if not chunk:
                        break
                    await out.write(chunk)

    size = dest.stat().st_size
    shutil_cleanup(session_dir)

    with db_cursor() as cur:
        cur.execute(
            "UPDATE upload_sessions SET status = 'completed' WHERE upload_id = ?",
            (upload_id,),
        )

    parent_rel = Path(session.relative_path).parent
    if str(parent_rel) == ".":
        rel = dest.name
    else:
        rel = f"{parent_rel}/{dest.name}"
    logical = f"{dir_resolved.grant.logical_path.rstrip('/')}/{rel}".replace("//", "/")
    if not logical.startswith("/"):
        logical = "/" + logical

    return {"path": logical, "size": size, "name": dest.name}


def shutil_cleanup(path: Path) -> None:
    import shutil

    if path.exists():
        shutil.rmtree(path, ignore_errors=True)
