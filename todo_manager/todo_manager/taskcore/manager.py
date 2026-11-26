"""Core business logic: add, complete, search and save tasks."""
from __future__ import annotations

from datetime import date, datetime
from typing import Callable

from . import validation as v
from .models import DEFAULT_CATEGORIES, PRIORITY_RANK, Task, format_timestamp
from .storage import TaskStore

_UNSET = object()
SORT_OPTIONS = ("due", "priority", "created", "title", "id")


class DuplicateTaskError(v.ValidationError):
    def __init__(self, existing_id: int):
        super().__init__(f"A pending task with this title already exists (ID {existing_id}).")
        self.existing_id = existing_id


class TaskNotFoundError(v.ValidationError):
    pass


class TaskManager:
    def __init__(self, store: TaskStore, today_fn: Callable[[], date] = date.today,
                 now_fn: Callable[[], datetime] = lambda: datetime.now().replace(microsecond=0)):
        self.store = store
        self.today_fn = today_fn
        self.now_fn = now_fn
        self.tasks: list[Task] = []
        self.load_warnings: list[str] = []
        self.reload()

    # ------------------------------------------------------------ persistence
    def reload(self) -> None:
        self.tasks = self.store.load()
        self.load_warnings = list(self.store.warnings)

    def save(self) -> None:
        self.store.save(self.tasks)

    def replace_all(self, tasks: list[Task]) -> None:
        self.tasks = list(tasks)
        self.save()

    # ----------------------------------------------------------------- lookup
    def today(self) -> date:
        return self.today_fn()

    def get(self, task_id: int) -> Task:
        for task in self.tasks:
            if task.id == task_id:
                return task
        raise TaskNotFoundError(f"No task with ID {task_id}.")

    def categories(self, include_defaults: bool = True) -> list[str]:
        names = {t.category for t in self.tasks}
        if include_defaults:
            names.update(DEFAULT_CATEGORIES)
        return sorted(names, key=str.casefold)

    def _next_id(self) -> int:
        return max((t.id for t in self.tasks), default=0) + 1

    def find_pending_duplicate(self, title: str) -> Task | None:
        """Return a pending task whose title matches (case-insensitive), if any."""
        return self._pending_duplicate(v.clean_text(title))

    def _pending_duplicate(self, title: str, ignore_id: int | None = None) -> Task | None:
        key = title.casefold()
        for task in self.tasks:
            if not task.completed and task.id != ignore_id and task.title.casefold() == key:
                return task
        return None

    # -------------------------------------------------------------- mutations
    def add(self, title, category="Personal", priority="Medium", due_date=None, notes="", *,
            status="Pending", created_at=None, completed_at=None,
            allow_duplicate: bool = False, save: bool = True) -> Task:
        title = v.validate_title(title)
        category = v.validate_category(category, self.categories())
        priority = v.validate_priority(priority)
        due = v.validate_due_date(due_date)
        notes = v.validate_notes(notes)
        status = v.validate_status(status)
        created = v.validate_timestamp(created_at) or self.now_fn()
        completed = None
        if status == "Completed":
            completed = v.validate_timestamp(completed_at) or self.now_fn()
            if completed < created:
                raise v.ValidationError("Completion time cannot be earlier than creation time.")
        elif not allow_duplicate:
            existing = self._pending_duplicate(title)
            if existing:
                raise DuplicateTaskError(existing.id)
        task = Task(
            id=self._next_id(), title=title, category=category, priority=priority,
            due_date=due.isoformat() if due else None, status=status, notes=notes,
            created_at=format_timestamp(created),
            completed_at=format_timestamp(completed) if completed else None,
        )
        self.tasks.append(task)
        if save:
            self.save()
        return task

    def complete(self, task_id: int, *, save: bool = True) -> Task:
        task = self.get(task_id)
        if task.completed:
            raise v.ValidationError(f"Task {task_id} is already completed.")
        task.status = "Completed"
        task.completed_at = format_timestamp(self.now_fn())
        if save:
            self.save()
        return task

    def reopen(self, task_id: int, *, save: bool = True) -> Task:
        task = self.get(task_id)
        if not task.completed:
            raise v.ValidationError(f"Task {task_id} is already pending.")
        existing = self._pending_duplicate(task.title, ignore_id=task.id)
        if existing:
            raise DuplicateTaskError(existing.id)
        task.status = "Pending"
        task.completed_at = None
        if save:
            self.save()
        return task

    def delete(self, task_id: int, *, save: bool = True) -> Task:
        task = self.get(task_id)
        self.tasks.remove(task)
        if save:
            self.save()
        return task

    def update(self, task_id: int, *, title=None, category=None, priority=None,
               due_date=_UNSET, notes=None, save: bool = True) -> Task:
        """Change fields of a task. Pass due_date=None to clear the due date."""
        task = self.get(task_id)
        changes = {}
        if title is not None:
            changes["title"] = v.validate_title(title)
            if not task.completed:
                existing = self._pending_duplicate(changes["title"], ignore_id=task.id)
                if existing:
                    raise DuplicateTaskError(existing.id)
        if category is not None:
            changes["category"] = v.validate_category(category, self.categories())
        if priority is not None:
            changes["priority"] = v.validate_priority(priority)
        if due_date is not _UNSET:
            due = v.validate_due_date(due_date)
            changes["due_date"] = due.isoformat() if due else None
        if notes is not None:
            changes["notes"] = v.validate_notes(notes)
        for field, value in changes.items():      # validated first, applied together
            setattr(task, field, value)
        if save:
            self.save()
        return task

    # ------------------------------------------------------------------ query
    def search(self, keyword: str | None = None, category: str | None = None,
               status: str | None = None, priority: str | None = None,
               overdue_only: bool = False, sort_by: str = "due",
               descending: bool = False) -> list[Task]:
        """Keyword and category based filtering. Every keyword term must match
        the title, notes or category (case-insensitive)."""
        if sort_by not in SORT_OPTIONS:
            raise v.ValidationError(f"Sort by one of: {', '.join(SORT_OPTIONS)}.")
        terms = v.clean_text(keyword).casefold().split()
        category_key = v.clean_text(category).casefold() if category else ""
        status_value = v.validate_status(status) if status and status.casefold() != "all" else None
        priority_value = v.validate_priority(priority) if priority and priority.casefold() != "all" else None
        today = self.today()

        results = []
        for task in self.tasks:
            if status_value and task.status != status_value:
                continue
            if priority_value and task.priority != priority_value:
                continue
            if category_key and task.category.casefold() != category_key:
                continue
            if overdue_only and not task.is_overdue(today):
                continue
            if terms:
                haystack = f"{task.title} {task.notes} {task.category}".casefold()
                if not all(term in haystack for term in terms):
                    continue
            results.append(task)

        keys = {
            "due": lambda t: (t.due is None, t.due or date.max, -PRIORITY_RANK[t.priority], t.id),
            "priority": lambda t: (-PRIORITY_RANK[t.priority], t.due is None, t.due or date.max, t.id),
            "created": lambda t: (t.created_at, t.id),
            "title": lambda t: (t.title.casefold(), t.id),
            "id": lambda t: t.id,
        }
        results.sort(key=keys[sort_by], reverse=descending)
        return results
