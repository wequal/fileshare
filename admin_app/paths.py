"""Resolve real on-disk paths for the install.

When running normally (``python -m admin_app`` via the venv), paths are
relative to the repo root. When running as a PyInstaller ``.exe``, ``__file__``
points into a temporary extraction folder and ``sys.executable`` is the exe
itself, so we must locate the real install folder another way: search upward
from the exe location for the directory that contains ``server/main.py``.
"""

from __future__ import annotations

import functools
import sys
from pathlib import Path

from server.config import Settings


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


@functools.lru_cache(maxsize=1)
def install_root() -> Path:
    """Return the real install directory (containing server/, config.yaml)."""
    if is_frozen():
        start = Path(sys.executable).resolve().parent
        for candidate in [start, *start.parents]:
            if (candidate / "server" / "main.py").is_file():
                return candidate
        # Fall back to the exe's own folder if nothing matched.
        return start
    return Path(__file__).resolve().parent.parent


def venv_python() -> Path:
    return install_root() / "venv" / "Scripts" / "python.exe"


def resolved_db_path(settings: Settings) -> Path:
    """Absolute SQLite path, resolving relative paths against the install root."""
    p = Path(settings.database_path)
    if not p.is_absolute():
        p = install_root() / p
    return p.resolve()


def resolved_data_root(settings: Settings) -> Path:
    """Absolute data root, resolving relative paths against the install root."""
    p = Path(settings.data_root)
    if not p.is_absolute():
        p = install_root() / p
    return p.resolve()
