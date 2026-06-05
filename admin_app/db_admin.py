"""Direct SQLite admin operations.

Mirrors the behavior of :mod:`server.admin_routes` so the desktop app can
manage users and grants while the server is offline.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Generator, List, Optional

from passlib.context import CryptContext

from admin_app.paths import resolved_data_root, resolved_db_path
from server.config import Settings
from server.database import _SCHEMA  # type: ignore[attr-defined]

_pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return _pwd.hash(password)


@dataclass
class UserRow:
    id: int
    username: str
    is_admin: bool


@dataclass
class GrantRow:
    id: int
    user_id: int
    username: str
    logical_path: str
    physical_path: str
    can_read: bool
    can_write: bool


class AdminDb:
    """Lightweight admin-side wrapper around the same SQLite file."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.db_path: Path = resolved_db_path(settings)
        self.data_root: Path = resolved_data_root(settings)

    # ---- low level -----------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def ensure_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(_SCHEMA)
            conn.commit()

    @contextmanager
    def cursor(self) -> Generator[sqlite3.Cursor, None, None]:
        conn = self._connect()
        try:
            cur = conn.cursor()
            yield cur
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # ---- users ---------------------------------------------------------

    def list_users(self) -> List[UserRow]:
        self.ensure_schema()
        with self.cursor() as cur:
            cur.execute(
                "SELECT id, username, is_admin FROM users ORDER BY username"
            )
            return [
                UserRow(
                    id=r["id"],
                    username=r["username"],
                    is_admin=bool(r["is_admin"]),
                )
                for r in cur.fetchall()
            ]

    def find_user(self, username: str) -> Optional[UserRow]:
        with self.cursor() as cur:
            cur.execute(
                "SELECT id, username, is_admin FROM users "
                "WHERE username = ? COLLATE NOCASE",
                (username,),
            )
            r = cur.fetchone()
            if not r:
                return None
            return UserRow(
                id=r["id"], username=r["username"], is_admin=bool(r["is_admin"])
            )

    def create_user(
        self, username: str, password: str, is_admin: bool = False
    ) -> UserRow:
        username = username.strip()
        if len(username) < 2 or len(username) > 64:
            raise ValueError("Username must be 2-64 characters")
        if len(password) < 6 or len(password) > 128:
            raise ValueError("Password must be 6-128 characters")
        self.ensure_schema()
        with self.cursor() as cur:
            cur.execute(
                "SELECT id FROM users WHERE username = ? COLLATE NOCASE",
                (username,),
            )
            if cur.fetchone():
                raise ValueError(f"Username '{username}' already exists")
            cur.execute(
                """
                INSERT INTO users (username, password_hash, is_admin)
                VALUES (?, ?, ?)
                """,
                (username, hash_password(password), int(is_admin)),
            )
            uid = cur.lastrowid
        return UserRow(id=uid, username=username, is_admin=is_admin)

    def set_password(self, user_id: int, password: str) -> None:
        if len(password) < 6 or len(password) > 128:
            raise ValueError("Password must be 6-128 characters")
        with self.cursor() as cur:
            cur.execute(
                "UPDATE users SET password_hash = ? WHERE id = ?",
                (hash_password(password), user_id),
            )
            if cur.rowcount == 0:
                raise ValueError("User not found")

    def set_admin(self, user_id: int, is_admin: bool) -> None:
        with self.cursor() as cur:
            cur.execute(
                "UPDATE users SET is_admin = ? WHERE id = ?",
                (int(is_admin), user_id),
            )
            if cur.rowcount == 0:
                raise ValueError("User not found")

    def delete_user(self, user_id: int) -> None:
        with self.cursor() as cur:
            cur.execute("DELETE FROM users WHERE id = ?", (user_id,))
            if cur.rowcount == 0:
                raise ValueError("User not found")

    # ---- grants --------------------------------------------------------

    def list_grants(self) -> List[GrantRow]:
        self.ensure_schema()
        with self.cursor() as cur:
            cur.execute(
                """
                SELECT g.id, g.user_id, u.username, g.logical_path,
                       g.physical_path, g.can_read, g.can_write
                FROM folder_grants g
                JOIN users u ON u.id = g.user_id
                ORDER BY u.username, g.logical_path
                """
            )
            return [
                GrantRow(
                    id=r["id"],
                    user_id=r["user_id"],
                    username=r["username"],
                    logical_path=r["logical_path"],
                    physical_path=r["physical_path"],
                    can_read=bool(r["can_read"]),
                    can_write=bool(r["can_write"]),
                )
                for r in cur.fetchall()
            ]

    @staticmethod
    def normalize_logical(path: str) -> str:
        path = path.strip()
        if not path:
            raise ValueError("Logical path cannot be empty")
        if not path.startswith("/"):
            path = "/" + path
        # Strip trailing slash except for root
        if len(path) > 1 and path.endswith("/"):
            path = path.rstrip("/")
        return path

    def validate_physical(self, physical: str) -> Path:
        if not physical.strip():
            raise ValueError("Physical path cannot be empty")
        p = Path(physical).resolve()
        data_root = self.data_root
        try:
            p.relative_to(data_root)
        except ValueError:
            if p != data_root:
                raise ValueError(
                    f"Physical path must live under data_root ({data_root})"
                ) from None
        return p

    def upsert_grant(
        self,
        username: str,
        logical_path: str,
        physical_path: str,
        can_read: bool = True,
        can_write: bool = False,
        create_dir: bool = True,
    ) -> GrantRow:
        logical = self.normalize_logical(logical_path)
        physical = self.validate_physical(physical_path)
        if create_dir:
            physical.mkdir(parents=True, exist_ok=True)

        self.ensure_schema()
        user = self.find_user(username)
        if not user:
            raise ValueError(f"User '{username}' not found")

        with self.cursor() as cur:
            cur.execute(
                """
                INSERT INTO folder_grants
                    (user_id, logical_path, physical_path, can_read, can_write)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(user_id, logical_path) DO UPDATE SET
                    physical_path = excluded.physical_path,
                    can_read = excluded.can_read,
                    can_write = excluded.can_write
                """,
                (
                    user.id,
                    logical,
                    str(physical),
                    int(can_read),
                    int(can_write),
                ),
            )
            cur.execute(
                """
                SELECT g.id, g.user_id, u.username, g.logical_path,
                       g.physical_path, g.can_read, g.can_write
                FROM folder_grants g
                JOIN users u ON u.id = g.user_id
                WHERE g.user_id = ? AND g.logical_path = ?
                """,
                (user.id, logical),
            )
            r = cur.fetchone()
        return GrantRow(
            id=r["id"],
            user_id=r["user_id"],
            username=r["username"],
            logical_path=r["logical_path"],
            physical_path=r["physical_path"],
            can_read=bool(r["can_read"]),
            can_write=bool(r["can_write"]),
        )

    def delete_grant(self, grant_id: int) -> None:
        with self.cursor() as cur:
            cur.execute("DELETE FROM folder_grants WHERE id = ?", (grant_id,))
            if cur.rowcount == 0:
                raise ValueError("Grant not found")
