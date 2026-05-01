from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from openitems.db import engine as engine_mod
from openitems.db.models import Base


@pytest.fixture
def session(tmp_path: Path) -> Iterator[Session]:
    db = tmp_path / "test.db"
    eng = engine_mod.reset_for_tests(db)
    Base.metadata.create_all(eng)
    SessionLocal = engine_mod.get_sessionmaker()
    s = SessionLocal()
    try:
        yield s
        s.commit()
    finally:
        s.close()
