from __future__ import annotations

import os
import tomllib
from pathlib import Path

from platformdirs import PlatformDirs

_dirs = PlatformDirs(appname="openitems", appauthor=False, ensure_exists=True)

# Default DB location is ~/openitems/openitems.db — visible in Finder, easy
# to point a SQLite browser at, and avoids the iCloud-Documents-sync footgun
# that would corrupt SQLite under concurrent access. Override via the
# OPENITEMS_DB env var or `db_path` in config.toml — see db_path() below.
_DEFAULT_DB_DIR_NAME = "openitems"


def data_dir() -> Path:
    """Platform user-data directory (used for exports).

    The DB itself no longer lives here — see ``db_path``.
    """
    return Path(_dirs.user_data_dir)


def config_dir() -> Path:
    return Path(_dirs.user_config_dir)


def config_path() -> Path:
    return config_dir() / "config.toml"


def default_db_path() -> Path:
    """Default DB location: ``~/openitems/openitems.db``."""
    return Path.home() / _DEFAULT_DB_DIR_NAME / "openitems.db"


def _config_db_override() -> Path | None:
    """Read ``db_path`` from config.toml without importing config (avoids cycle)."""
    cfg = config_path()
    if not cfg.exists():
        return None
    try:
        data = tomllib.loads(cfg.read_text())
    except (OSError, tomllib.TOMLDecodeError):
        return None
    raw = data.get("db_path")
    if not raw or not isinstance(raw, str):
        return None
    return Path(raw).expanduser()


def db_path() -> Path:
    """Resolve the SQLite DB location.

    Resolution order:
      1. ``OPENITEMS_DB`` environment variable (full path)
      2. ``db_path`` field in ``config.toml``
      3. Default: ``~/openitems/openitems.db``

    The parent directory is created automatically by the engine on first use.
    """
    env = os.environ.get("OPENITEMS_DB")
    if env:
        return Path(env).expanduser()
    cfg_override = _config_db_override()
    if cfg_override is not None:
        return cfg_override
    return default_db_path()


def exports_dir() -> Path:
    p = data_dir() / "exports"
    p.mkdir(parents=True, exist_ok=True)
    return p
