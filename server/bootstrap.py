from __future__ import annotations

from pathlib import Path

from passlib.context import CryptContext

from server.config import get_settings
from server.database import db_cursor, get_db

_pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return _pwd.hash(password)


def ensure_data_root() -> Path:
    settings = get_settings()
    root = settings.data_root_path
    root.mkdir(parents=True, exist_ok=True)
    return root


def bootstrap_admin() -> None:
    settings = get_settings()
    ensure_data_root()
    get_db()

    with db_cursor() as cur:
        cur.execute("SELECT COUNT(*) AS c FROM users")
        count = cur.fetchone()["c"]
        if count > 0:
            return

        cur.execute(
            """
            INSERT INTO users (username, password_hash, is_admin)
            VALUES (?, ?, 1)
            """,
            (
                settings.bootstrap_admin_username,
                hash_password(settings.bootstrap_admin_password),
            ),
        )
        admin_id = cur.lastrowid

        # Default grant: admin full access to entire data root at "/"
        cur.execute(
            """
            INSERT INTO folder_grants (user_id, logical_path, physical_path, can_read, can_write)
            VALUES (?, '/', ?, 1, 1)
            """,
            (admin_id, str(settings.data_root_path)),
        )
