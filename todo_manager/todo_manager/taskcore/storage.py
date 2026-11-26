"""JSON persistence with schema checks, corruption recovery and atomic writes."""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

from .models import Task

SCHEMA_VERSION = 1


class StorageError(Exception):
    """Raised when the data file cannot be written."""


class TaskStore:
    def __init__(self, path):
        self.path = Path(path)
        self.warnings: list[str] = []

    # ------------------------------------------------------------------ load
    def load(self) -> list[Task]:
        """Read all tasks. Never raises for a missing, empty or corrupted file:
        it recovers with a clean template and records what happened in self.warnings."""
        self.warnings = []
        if not self.path.exists():
            self._write_template()
            return []
        try:
            text = self.path.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeDecodeError) as err:
            return self._recover(f"Could not read {self.path.name} ({err})")
        if not text.strip():
            self._write_template()
            self.warnings.append(f"{self.path.name} was empty, so a fresh task list was created.")
            return []
        try:
            raw = json.loads(text)
        except json.JSONDecodeError as err:
            return self._recover(f"{self.path.name} is not valid JSON (line {err.lineno}, column {err.colno})")

        if isinstance(raw, dict):
            records = raw.get("tasks")
        else:
            records = raw                                    # legacy: a bare list of tasks
        if not isinstance(records, list):
            return self._recover(f"{self.path.name} does not contain a task list")

        tasks: list[Task] = []
        seen_ids: set[int] = set()
        skipped = 0
        for index, record in enumerate(records, start=1):
            try:
                task = Task.from_dict(record)
                if task.id in seen_ids:
                    raise ValueError(f"duplicate id {task.id}")
            except ValueError as err:
                skipped += 1
                self.warnings.append(f"Skipped record {index}: {err}.")
                continue
            seen_ids.add(task.id)
            tasks.append(task)
        if skipped:
            backup = self._backup("skipped")
            self.warnings.append(f"{skipped} invalid record(s) were skipped. The original file is kept as {backup.name}.")
        return tasks

    # ------------------------------------------------------------------ save
    def save(self, tasks: list[Task]) -> None:
        payload = {"schema_version": SCHEMA_VERSION, "tasks": [t.to_dict() for t in tasks]}
        self._atomic_write(json.dumps(payload, indent=2, ensure_ascii=False))

    # --------------------------------------------------------------- helpers
    def _atomic_write(self, text: str) -> None:
        tmp = self.path.with_name(self.path.name + ".tmp")
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp.write_text(text, encoding="utf-8")
            os.replace(tmp, self.path)                       # atomic on the same volume
        except OSError as err:
            raise StorageError(f"Could not save to {self.path}: {err}") from err

    def _write_template(self) -> None:
        try:
            self.save([])
        except StorageError as err:
            self.warnings.append(str(err))

    def _backup(self, reason: str) -> Path:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup = self.path.with_name(f"{self.path.name}.{reason}-{stamp}")
        try:
            backup.write_bytes(self.path.read_bytes())
        except OSError:
            pass
        return backup

    def _recover(self, problem: str) -> list[Task]:
        backup = self._backup("corrupt")
        self.warnings.append(f"{problem}. The damaged file was kept as {backup.name} and a fresh list was started.")
        self._write_template()
        return []
