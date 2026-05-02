from __future__ import annotations

from pathlib import Path

import pytest

from openitems import paths


def test_default_db_path_under_home():
    out = paths.default_db_path()
    assert out == Path.home() / "openitems" / "openitems.db"


def test_env_var_overrides_default(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    target = tmp_path / "forced.db"
    monkeypatch.setenv("OPENITEMS_DB", str(target))
    monkeypatch.setattr(paths, "config_path", lambda: tmp_path / "absent.toml")
    assert paths.db_path() == target


def test_env_var_expanduser(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setenv("OPENITEMS_DB", "~/explicit-tilde.db")
    monkeypatch.setattr(paths, "config_path", lambda: tmp_path / "absent.toml")
    assert paths.db_path() == Path.home() / "explicit-tilde.db"


def test_config_db_path_overrides_default(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    monkeypatch.delenv("OPENITEMS_DB", raising=False)
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text('db_path = "/tmp/from-config.db"\n')
    monkeypatch.setattr(paths, "config_path", lambda: cfg_file)
    assert paths.db_path() == Path("/tmp/from-config.db")


def test_env_var_beats_config(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text('db_path = "/tmp/from-config.db"\n')
    monkeypatch.setattr(paths, "config_path", lambda: cfg_file)
    monkeypatch.setenv("OPENITEMS_DB", "/tmp/from-env.db")
    assert paths.db_path() == Path("/tmp/from-env.db")


def test_default_when_no_overrides(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    monkeypatch.delenv("OPENITEMS_DB", raising=False)
    monkeypatch.setattr(paths, "config_path", lambda: tmp_path / "missing.toml")
    assert paths.db_path() == paths.default_db_path()


def test_malformed_config_falls_through(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    monkeypatch.delenv("OPENITEMS_DB", raising=False)
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text("not = valid = toml\n")
    monkeypatch.setattr(paths, "config_path", lambda: cfg_file)
    # Malformed config should not raise; falls through to default.
    assert paths.db_path() == paths.default_db_path()
