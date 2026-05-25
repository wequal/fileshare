from __future__ import annotations

from pathlib import Path
from typing import List, Optional

import yaml
from pydantic import BaseModel, Field


class Settings(BaseModel):
    host: str = "0.0.0.0"
    port: int = 8443
    data_root: str = "D:/FileShareData"
    database_path: str = "data/fileshare.db"
    jwt_secret: str = "change-me"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 1440
    bootstrap_admin_username: str = "admin"
    bootstrap_admin_password: str = "changeme"
    allow_public_registration: bool = False
    chunk_size_mb: int = 8
    mobile_chunk_size_mb: int = 1
    max_parallel_parts: int = 6
    upload_session_expire_hours: int = 24
    ip_allowlist: List[str] = Field(default_factory=list)
    cors_origins: List[str] = Field(default_factory=lambda: ["*"])

    @property
    def data_root_path(self) -> Path:
        return Path(self.data_root).resolve()

    @property
    def chunk_size_bytes(self) -> int:
        return self.chunk_size_mb * 1024 * 1024

    @property
    def mobile_chunk_size_bytes(self) -> int:
        return self.mobile_chunk_size_mb * 1024 * 1024

    @property
    def db_path(self) -> Path:
        p = Path(self.database_path)
        if not p.is_absolute():
            p = Path(__file__).resolve().parent.parent / p
        return p.resolve()


_settings: Optional[Settings] = None


def load_settings(config_path: Optional[Path] = None) -> Settings:
    global _settings
    if _settings is not None:
        return _settings

    base = Path(__file__).resolve().parent.parent
    path = config_path or (base / "config.yaml")
    if not path.exists():
        path = base / "config.example.yaml"

    data: dict = {}
    if path.exists():
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}

    _settings = Settings(**data)
    return _settings


def get_settings() -> Settings:
    if _settings is None:
        return load_settings()
    return _settings
