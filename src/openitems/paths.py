from __future__ import annotations

from pathlib import Path

from platformdirs import PlatformDirs

_dirs = PlatformDirs(appname="openitems", appauthor=False, ensure_exists=True)


def data_dir() -> Path:
    return Path(_dirs.user_data_dir)


def config_dir() -> Path:
    return Path(_dirs.user_config_dir)


def db_path() -> Path:
    return data_dir() / "openitems.db"


def config_path() -> Path:
    return config_dir() / "config.toml"


def exports_dir() -> Path:
    p = data_dir() / "exports"
    p.mkdir(parents=True, exist_ok=True)
    return p
