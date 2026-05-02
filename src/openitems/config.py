from __future__ import annotations

import tomllib
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import tomli_w

from openitems import paths


@dataclass
class ExportPrefs:
    columns: list[str] = field(
        default_factory=lambda: [
            "#",
            "Task",
            "Tags",
            "Priority",
            "Assigned To",
            "Start",
            "Due",
            "Description",
            "Checklist",
        ]
    )
    open_after_save: bool = True
    last_path: str | None = None


@dataclass
class Config:
    active_engagement: str | None = None
    export_prefs: dict[str, ExportPrefs] = field(default_factory=dict)
    db_path: str | None = None
    last_planned_at: str | None = None  # ISO date — last time user toggled focus

    @classmethod
    def load(cls, path: Path | None = None) -> Config:
        path = path or paths.config_path()
        if not path.exists():
            return cls()
        data = tomllib.loads(path.read_text())
        prefs_raw: dict[str, Any] = data.get("export_prefs") or {}
        prefs = {slug: ExportPrefs(**v) for slug, v in prefs_raw.items()}
        return cls(
            active_engagement=data.get("active_engagement"),
            export_prefs=prefs,
            db_path=data.get("db_path"),
            last_planned_at=data.get("last_planned_at"),
        )

    def save(self, path: Path | None = None) -> None:
        path = path or paths.config_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        payload: dict[str, Any] = {}
        if self.active_engagement is not None:
            payload["active_engagement"] = self.active_engagement
        if self.db_path is not None:
            payload["db_path"] = self.db_path
        if self.last_planned_at is not None:
            payload["last_planned_at"] = self.last_planned_at
        if self.export_prefs:
            payload["export_prefs"] = {
                slug: asdict(prefs) for slug, prefs in self.export_prefs.items()
            }
        path.write_text(tomli_w.dumps(payload))

    def prefs_for(self, slug: str) -> ExportPrefs:
        return self.export_prefs.get(slug, ExportPrefs())
