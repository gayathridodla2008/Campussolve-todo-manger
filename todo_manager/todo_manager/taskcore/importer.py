"""Bulk CSV import with automatic format validation and a row-by-row error log."""
from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from . import validation as v
from .manager import DuplicateTaskError, TaskManager

MAX_ROWS = 5000
MAX_BYTES = 5 * 1024 * 1024
_ALIASES = {
    "task": "title", "name": "title", "todo": "title",
    "due": "due_date", "deadline": "due_date", "due date": "due_date",
    "description": "notes", "note": "notes", "comments": "notes",
    "type": "category", "group": "category",
}
_KNOWN = {"title", "category", "priority", "due_date", "status", "notes", "created_at", "completed_at"}


@dataclass
class ImportResult:
    imported: int = 0
    skipped: int = 0
    errors: list = field(default_factory=list)          # [(row_number, message)]
    ignored_columns: list = field(default_factory=list)
    fatal: str | None = None
    log_path: Path | None = None

    @property
    def ok(self) -> bool:
        return self.fatal is None


def decode_bytes(data: bytes) -> str:
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1")


def _unformula(text: str) -> str:
    """Undo the apostrophe our own CSV export adds in front of =, +, - and @."""
    return text[1:] if len(text) > 1 and text[0] == "'" and text[1] in "=+-@" else text


def import_csv_text(text: str, manager: TaskManager, *, log_dir=None, source: str = "upload") -> ImportResult:
    result = ImportResult()
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        result.fatal = "The file is empty or has no header row."
        return result
    mapping = {}
    for original in reader.fieldnames:
        key = (original or "").strip().casefold().replace("_", " ")
        key = _ALIASES.get(key, key).replace(" ", "_")
        if key in _KNOWN and key not in mapping.values():
            mapping[original] = key
        elif original and original.strip():
            result.ignored_columns.append(original.strip())
    if "title" not in mapping.values():
        result.fatal = "No title column found. The header row needs a 'title' column (or 'task' / 'name')."
        return result

    for row_number, raw in enumerate(reader, start=2):          # row 1 is the header
        if result.imported + result.skipped >= MAX_ROWS:
            result.errors.append((row_number, f"Stopped: only the first {MAX_ROWS} rows are imported."))
            break
        row = {mapping[k]: (val or "") for k, val in raw.items() if k in mapping and not isinstance(val, list)}
        if not any(str(val).strip() for val in row.values()):
            continue                                            # blank line
        problems = []

        def check(label, func, *args):
            try:
                return func(*args)
            except v.ValidationError as err:
                problems.append(str(err))
                return None

        title = check("title", v.validate_title, _unformula(row.get("title", "")))
        category = _unformula(row.get("category", "")).strip() or "Personal"
        category = check("category", v.validate_category, category, manager.categories())
        priority = check("priority", v.validate_priority, row.get("priority", "").strip() or "Medium")
        due = check("due", v.validate_due_date, row.get("due_date", ""))
        status = check("status", v.validate_status, row.get("status", "").strip() or "Pending")
        notes = check("notes", v.validate_notes, _unformula(row.get("notes", "")))
        created = check("created", v.validate_timestamp, row.get("created_at", ""))
        completed = check("completed", v.validate_timestamp, row.get("completed_at", ""))
        if problems:
            result.skipped += 1
            result.errors.append((row_number, "; ".join(problems)))
            continue
        try:
            manager.add(title, category, priority, due, notes, status=status, created_at=created,
                        completed_at=completed, save=False)
            result.imported += 1
        except DuplicateTaskError as err:
            result.skipped += 1
            result.errors.append((row_number, f"Duplicate: {err}"))
        except v.ValidationError as err:
            result.skipped += 1
            result.errors.append((row_number, str(err)))

    if result.imported:
        manager.save()
    if result.errors and log_dir is not None:
        log_dir = Path(log_dir)
        log_dir.mkdir(parents=True, exist_ok=True)
        path = log_dir / f"import_errors_{datetime.now():%Y%m%d-%H%M%S}.log"
        lines = [f"Import log for {source}", f"Imported {result.imported}, skipped {result.skipped}", ""]
        lines += [f"Row {n}: {msg}" for n, msg in result.errors]
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        result.log_path = path
    return result


def import_csv_file(path, manager: TaskManager, *, log_dir=None) -> ImportResult:
    path = Path(str(path).strip().strip('"').strip("'")).expanduser()
    if not path.is_file():
        return ImportResult(fatal=f"File not found: {path}")
    if path.stat().st_size > MAX_BYTES:
        return ImportResult(fatal=f"File is larger than {MAX_BYTES // (1024 * 1024)} MB.")
    try:
        text = decode_bytes(path.read_bytes())
    except OSError as err:
        return ImportResult(fatal=f"Could not read the file: {err}")
    return import_csv_text(text, manager, log_dir=log_dir, source=path.name)
