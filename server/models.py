from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional


@dataclass
class User:
    id: int
    username: str
    password_hash: str
    is_admin: bool

    @classmethod
    def from_row(cls, row) -> "User":
        return cls(
            id=row["id"],
            username=row["username"],
            password_hash=row["password_hash"],
            is_admin=bool(row["is_admin"]),
        )


@dataclass
class FolderGrant:
    id: int
    user_id: int
    logical_path: str
    physical_path: str
    can_read: bool
    can_write: bool

    @classmethod
    def from_row(cls, row) -> "FolderGrant":
        return cls(
            id=row["id"],
            user_id=row["user_id"],
            logical_path=row["logical_path"],
            physical_path=row["physical_path"],
            can_read=bool(row["can_read"]),
            can_write=bool(row["can_write"]),
        )


@dataclass
class UploadSession:
    upload_id: str
    user_id: int
    logical_path: str
    relative_path: str
    filename: str
    total_size: int
    chunk_size: int
    total_parts: int
    parts_received: List[int]
    status: str

    @classmethod
    def from_row(cls, row) -> "UploadSession":
        import json

        parts = json.loads(row["parts_received"])
        return cls(
            upload_id=row["upload_id"],
            user_id=row["user_id"],
            logical_path=row["logical_path"],
            relative_path=row["relative_path"],
            filename=row["filename"],
            total_size=row["total_size"],
            chunk_size=row["chunk_size"],
            total_parts=row["total_parts"],
            parts_received=parts,
            status=row["status"],
        )
