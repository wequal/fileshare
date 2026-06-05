from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from server.auth import hash_password, require_admin
from server.config import get_settings
from server.database import db_cursor
from server.models import User

router = APIRouter(prefix="/admin", tags=["admin"])


class CreateUserRequest(BaseModel):
    username: str = Field(min_length=2, max_length=64)
    password: str = Field(min_length=6, max_length=128)
    is_admin: bool = False


class GrantRequest(BaseModel):
    username: str
    logical_path: str
    physical_path: str
    can_read: bool = True
    can_write: bool = False


class UserInfo(BaseModel):
    id: int
    username: str
    is_admin: bool


class GrantInfo(BaseModel):
    id: int
    username: str
    logical_path: str
    physical_path: str
    can_read: bool
    can_write: bool


@router.get("/users", response_model=List[UserInfo])
async def list_users(_: User = Depends(require_admin)):
    with db_cursor() as cur:
        cur.execute("SELECT id, username, is_admin FROM users ORDER BY username")
        return [
            UserInfo(id=r["id"], username=r["username"], is_admin=bool(r["is_admin"]))
            for r in cur.fetchall()
        ]


@router.post("/users", response_model=UserInfo)
async def create_user(body: CreateUserRequest, _: User = Depends(require_admin)):
    with db_cursor() as cur:
        cur.execute("SELECT id FROM users WHERE username = ? COLLATE NOCASE", (body.username,))
        if cur.fetchone():
            raise HTTPException(400, "Username already exists")
        cur.execute(
            """
            INSERT INTO users (username, password_hash, is_admin)
            VALUES (?, ?, ?)
            """,
            (body.username, hash_password(body.password), int(body.is_admin)),
        )
        uid = cur.lastrowid
    return UserInfo(id=uid, username=body.username, is_admin=body.is_admin)


@router.put("/grants")
async def set_grant(body: GrantRequest, _: User = Depends(require_admin)):
    settings = get_settings()
    physical = Path(body.physical_path).resolve()
    data_root = settings.data_root_path.resolve()

    try:
        physical.relative_to(data_root)
    except ValueError:
        if physical != data_root:
            raise HTTPException(
                400,
                f"physical_path must be under data_root ({data_root})",
            )

    logical = body.logical_path if body.logical_path.startswith("/") else "/" + body.logical_path

    with db_cursor() as cur:
        cur.execute(
            "SELECT id FROM users WHERE username = ? COLLATE NOCASE", (body.username,)
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, "User not found")
        user_id = row["id"]

        cur.execute(
            """
            INSERT INTO folder_grants (user_id, logical_path, physical_path, can_read, can_write)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(user_id, logical_path) DO UPDATE SET
                physical_path = excluded.physical_path,
                can_read = excluded.can_read,
                can_write = excluded.can_write
            """,
            (
                user_id,
                logical,
                str(physical),
                int(body.can_read),
                int(body.can_write),
            ),
        )

    return {"ok": True, "username": body.username, "logical_path": logical}


@router.get("/grants", response_model=List[GrantInfo])
async def list_grants(_: User = Depends(require_admin)):
    with db_cursor() as cur:
        cur.execute(
            """
            SELECT g.id, u.username, g.logical_path, g.physical_path, g.can_read, g.can_write
            FROM folder_grants g
            JOIN users u ON u.id = g.user_id
            ORDER BY u.username, g.logical_path
            """
        )
        return [
            GrantInfo(
                id=r["id"],
                username=r["username"],
                logical_path=r["logical_path"],
                physical_path=r["physical_path"],
                can_read=bool(r["can_read"]),
                can_write=bool(r["can_write"]),
            )
            for r in cur.fetchall()
        ]


@router.delete("/grants/{grant_id}")
async def delete_grant(grant_id: int, _: User = Depends(require_admin)):
    with db_cursor() as cur:
        cur.execute("DELETE FROM folder_grants WHERE id = ?", (grant_id,))
        if cur.rowcount == 0:
            raise HTTPException(404, "Grant not found")
    return {"ok": True}
