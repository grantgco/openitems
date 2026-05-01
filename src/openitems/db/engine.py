from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from openitems import paths

_engine: Engine | None = None
_SessionLocal: sessionmaker[Session] | None = None


def _enable_foreign_keys(dbapi_conn, _):  # pragma: no cover - sqlite plumbing
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def get_engine(path: Path | None = None) -> Engine:
    global _engine, _SessionLocal
    if _engine is None or path is not None:
        target = path or paths.db_path()
        target.parent.mkdir(parents=True, exist_ok=True)
        _engine = create_engine(f"sqlite:///{target}", future=True)
        event.listen(_engine, "connect", _enable_foreign_keys)
        _SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False, future=True)
    return _engine


def get_sessionmaker() -> sessionmaker[Session]:
    if _SessionLocal is None:
        get_engine()
    assert _SessionLocal is not None
    return _SessionLocal


@contextmanager
def session_scope() -> Iterator[Session]:
    SessionLocal = get_sessionmaker()
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def reset_for_tests(path: Path) -> Engine:
    """Reset the engine to point at a temp DB. Tests only."""
    global _engine, _SessionLocal
    _engine = None
    _SessionLocal = None
    return get_engine(path)
