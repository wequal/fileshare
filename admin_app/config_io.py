"""Read and write config.yaml for the file share server.

Validates by constructing :class:`server.config.Settings` from the data, but
preserves the dict round-trip so unrelated keys are not lost.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any, Dict, Optional

import yaml

from admin_app.paths import install_root
from server.config import Settings

REPO_ROOT = install_root()
CONFIG_PATH = REPO_ROOT / "config.yaml"
EXAMPLE_PATH = REPO_ROOT / "config.example.yaml"


def ensure_config_exists() -> Path:
    """Copy ``config.example.yaml`` to ``config.yaml`` if missing."""
    if not CONFIG_PATH.exists() and EXAMPLE_PATH.exists():
        shutil.copyfile(EXAMPLE_PATH, CONFIG_PATH)
    return CONFIG_PATH


def load_raw() -> Dict[str, Any]:
    ensure_config_exists()
    if not CONFIG_PATH.exists():
        return {}
    with open(CONFIG_PATH, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ValueError("config.yaml must be a mapping at the top level")
    return data


def load_settings() -> Settings:
    """Load and validate settings via the server's :class:`Settings` model."""
    raw = load_raw()
    return Settings(**raw)


def save_settings(values: Dict[str, Any]) -> Settings:
    """Validate ``values`` then write them back to ``config.yaml``.

    Unknown keys present in the existing file are preserved.
    """
    settings = Settings(**values)

    existing = load_raw()
    merged: Dict[str, Any] = dict(existing)
    merged.update(settings.model_dump())

    tmp = CONFIG_PATH.with_suffix(".yaml.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        yaml.safe_dump(
            merged,
            f,
            sort_keys=False,
            default_flow_style=False,
            allow_unicode=True,
        )
    tmp.replace(CONFIG_PATH)
    return settings


def db_path_for(settings: Optional[Settings] = None) -> Path:
    """Return the absolute SQLite path for the given (or loaded) settings."""
    from admin_app.paths import resolved_db_path

    s = settings or load_settings()
    return resolved_db_path(s)
