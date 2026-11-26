"""Data model for a to-do item, plus shared constants."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime

PRIORITIES = ("Low", "Medium", "High", "Critical")
PRIORITY_RANK = {name: rank for rank, name in enumerate(PRIORITIES)}
STATUSES = ("Pending", "Completed")
DEFAULT_CATEGORIES = (
    "Academics", "Assignments", "Clubs", "Exams",
    "Finance", "Health", "Personal", "Projects",
)

TS_FORMAT = "%Y-%m-%dT%H:%M:%S"
DATE_FORMAT = "%Y-%m-%d"


def format_timestamp(moment: datetime) -> str:
    return moment.strftime(TS_FORMAT)


def parse_timestamp(value) -> datetime | None:
    """Parse a stored timestamp. Blank values give None; bad values raise ValueError."""
    if value in (None, ""):
        return None
    if not isinstance(value, str):
        raise ValueError(f"timestamp must be text, got {type(value).__name__}")
    try:
        return datetime.strptime(value, TS_FORMAT)
    except ValueError:
        raise ValueError(f"invalid timestamp {value!r}") from None


def parse_iso_date(value) -> date | None:
    if value in (None, ""):
        return None
    if not isinstance(value, str):
        raise ValueError(f"date must be text, got {type(value).__name__}")
    try:
        return datetime.strptime(value, DATE_FORMAT).date()
    except ValueError:
        raise ValueError(f"invalid date {value!r}") from None


@dataclass
class Task:
    id: int
    title: str
    category: str = "Personal"
    priority: str = "Medium"
    due_date: str | None = None          # ISO date, e.g. 2026-12-31
    status: str = "Pending"
    notes: str = ""
    created_at: str = ""                 # ISO timestamp
    completed_at: str | None = None      # ISO timestamp

    # ---- convenience views -------------------------------------------------
    @property
    def completed(self) -> bool:
        return self.status == "Completed"

    @property
    def due(self) -> date | None:
        return parse_iso_date(self.due_date)

    @property
    def created_dt(self) -> datetime | None:
        return parse_timestamp(self.created_at)

    @property
    def completed_dt(self) -> datetime | None:
        return parse_timestamp(self.completed_at)

    def is_overdue(self, today: date) -> bool:
        due = self.due
        return (not self.completed) and due is not None and due < today

    def days_until_due(self, today: date) -> int | None:
        due = self.due
        return None if due is None else (due - today).days

    # ---- (de)serialisation -------------------------------------------------
    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data) -> "Task":
        """Build a Task from a stored record, enforcing the storage schema."""
        if not isinstance(data, dict):
            raise ValueError("record is not an object")
        task_id = data.get("id")
        if isinstance(task_id, bool) or not isinstance(task_id, int) or task_id < 1:
            raise ValueError("'id' must be a positive whole number")
        title = data.get("title")
        if not isinstance(title, str) or not title.strip():
            raise ValueError("'title' is missing or blank")
        category = data.get("category") or "Personal"
        notes = data.get("notes") or ""
        if not isinstance(category, str) or not isinstance(notes, str):
            raise ValueError("'category' and 'notes' must be text")
        priority = data.get("priority", "Medium")
        if priority not in PRIORITIES:
            raise ValueError(f"'priority' must be one of {', '.join(PRIORITIES)}")
        status = data.get("status", "Pending")
        if status not in STATUSES:
            raise ValueError(f"'status' must be one of {', '.join(STATUSES)}")
        due_date = data.get("due_date") or None
        parse_iso_date(due_date)
        created_at = data.get("created_at") or ""
        parse_timestamp(created_at)
        completed_at = data.get("completed_at") or None
        parse_timestamp(completed_at)
        if status == "Pending":
            completed_at = None
        return cls(
            id=task_id, title=title.strip(), category=category.strip() or "Personal",
            priority=priority, due_date=due_date, status=status, notes=notes,
            created_at=created_at, completed_at=completed_at,
        )
