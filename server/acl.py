from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

from server.config import get_settings
from server.database import db_cursor
from server.models import FolderGrant, User


class PathAccessError(Exception):
    def __init__(self, message: str, status_code: int = 403):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


@dataclass
class ResolvedPath:
    grant: FolderGrant
    logical_path: str
    relative_path: str
    physical_path: Path


def _normalize_logical(path: str) -> str:
    if not path or path == "/":
        return "/"
    p = path.replace("\\", "/").strip("/")
    parts = []
    for seg in p.split("/"):
        if seg in ("", "."):
            continue
        if seg == "..":
            raise PathAccessError("Path traversal not allowed", 400)
        parts.append(seg)
    return "/" + "/".join(parts) if parts else "/"


def get_grants_for_user(user_id: int) -> List[FolderGrant]:
    with db_cursor() as cur:
        cur.execute(
            "SELECT * FROM folder_grants WHERE user_id = ? ORDER BY LENGTH(logical_path) DESC",
            (user_id,),
        )
        return [FolderGrant.from_row(r) for r in cur.fetchall()]


def _grant_covers(grant: FolderGrant, logical: str) -> bool:
    g = grant.logical_path.rstrip("/") or "/"
    if g == "/":
        return True
    return logical == g or logical.startswith(g + "/")


def resolve_path(
    user: User,
    path: str,
    need_read: bool = False,
    need_write: bool = False,
) -> ResolvedPath:
    logical = _normalize_logical(path)
    grants = get_grants_for_user(user.id)

    best: Optional[FolderGrant] = None
    for g in grants:
        if _grant_covers(g, logical):
            if best is None or len(g.logical_path) > len(best.logical_path):
                best = g

    if best is None:
        raise PathAccessError("No access to this path", 403)

    if need_read and not best.can_read:
        raise PathAccessError("Read access denied", 403)
    if need_write and not best.can_write:
        raise PathAccessError("Write access denied", 403)

    grant_logical = best.logical_path.rstrip("/") or "/"
    if grant_logical == "/":
        relative = logical.lstrip("/")
    else:
        suffix = logical[len(grant_logical) :].lstrip("/")
        relative = suffix

    physical_base = Path(best.physical_path).resolve()
    settings = get_settings()
    data_root = settings.data_root_path

    try:
        physical_base.relative_to(data_root)
    except ValueError:
        if physical_base != data_root and not str(physical_base).startswith(
            str(data_root)
        ):
            pass

    target = physical_base if not relative else physical_base / relative
    target = target.resolve()

    try:
        target.relative_to(physical_base)
    except ValueError:
        raise PathAccessError("Path escapes granted folder", 403) from None

    return ResolvedPath(
        grant=best,
        logical_path=logical,
        relative_path=relative,
        physical_path=target,
    )


def list_accessible_roots(user: User) -> List[dict]:
    grants = get_grants_for_user(user.id)
    return [
        {
            "logical_path": g.logical_path,
            "can_read": g.can_read,
            "can_write": g.can_write,
        }
        for g in grants
        if g.can_read
    ]
