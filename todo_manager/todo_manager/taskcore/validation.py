"""Defensive input validation shared by the terminal app, the GUI and the importer.

Every validator takes raw user input, returns a clean value of the right type and
raises ValidationError with a message that tells the user how to fix the problem.
"""
from __future__ import annotations

import re
from datetime import date, datetime
from typing import Iterable

from .models import PRIORITIES

TITLE_MIN, TITLE_MAX = 3, 100
CATEGORY_MIN, CATEGORY_MAX = 2, 30
NOTES_MAX = 500
MIN_YEAR, MAX_YEAR = 2000, 2100

DATE_FORMATS = ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%Y/%m/%d")
TIMESTAMP_FORMATS = ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M")

_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")
_CATEGORY_RE = re.compile(r"^[\w &/\-]+$", re.UNICODE)
_PRIORITY_ALIASES = {
    "l": "Low", "m": "Medium", "h": "High", "c": "Critical",
    "1": "Low", "2": "Medium", "3": "High", "4": "Critical",
    "med": "Medium", "crit": "Critical",
}
_STATUS_ALIASES = {
    "pending": "Pending", "open": "Pending", "todo": "Pending", "p": "Pending",
    "completed": "Completed", "complete": "Completed", "done": "Completed", "c": "Completed",
}


class ValidationError(ValueError):
    """Raised when user input does not satisfy the domain rules."""


def clean_text(value) -> str:
    """Sanitise free text: drop control characters, collapse whitespace, trim."""
    if value is None:
        return ""
    return " ".join(_CONTROL_CHARS.sub(" ", str(value)).split())


def _chars(n: int) -> str:
    return f"{n} character" if n == 1 else f"{n} characters"


def validate_title(value) -> str:
    title = clean_text(value)
    if not title:
        raise ValidationError("Title is required.")
    if len(title) < TITLE_MIN:
        raise ValidationError(f"Title is too short ({_chars(len(title))}). Use at least {TITLE_MIN}.")
    if len(title) > TITLE_MAX:
        raise ValidationError(f"Title is too long ({_chars(len(title))}). Keep it to {TITLE_MAX} or fewer.")
    if not any(ch.isalnum() for ch in title):
        raise ValidationError("Title needs at least one letter or number.")
    return title


def validate_category(value, known: Iterable[str] = ()) -> str:
    category = clean_text(value)
    if not category:
        raise ValidationError("Category is required.")
    if not CATEGORY_MIN <= len(category) <= CATEGORY_MAX:
        raise ValidationError(f"Category must be {CATEGORY_MIN} to {CATEGORY_MAX} characters.")
    if not _CATEGORY_RE.match(category):
        raise ValidationError("Category can only contain letters, numbers, spaces and & / _ -")
    for existing in known:
        if existing.casefold() == category.casefold():
            return existing                      # reuse the existing spelling
    return category


def validate_priority(value) -> str:
    text = clean_text(value).casefold()
    for name in PRIORITIES:
        if text == name.casefold():
            return name
    if text in _PRIORITY_ALIASES:
        return _PRIORITY_ALIASES[text]
    raise ValidationError(f"Priority must be one of: {', '.join(PRIORITIES)} (or 1-4).")


def validate_status(value) -> str:
    text = clean_text(value).casefold()
    if text in _STATUS_ALIASES:
        return _STATUS_ALIASES[text]
    raise ValidationError("Status must be Pending or Completed.")


def validate_due_date(value, *, required: bool = False) -> date | None:
    """Accept a date object or text (YYYY-MM-DD, DD-MM-YYYY, DD/MM/YYYY). Blank gives None."""
    if isinstance(value, datetime):
        parsed = value.date()
    elif isinstance(value, date):
        parsed = value
    else:
        text = clean_text(value)
        if not text:
            if required:
                raise ValidationError("Due date is required.")
            return None
        parsed = None
        for fmt in DATE_FORMATS:
            try:
                parsed = datetime.strptime(text, fmt).date()
                break
            except ValueError:
                continue
        if parsed is None:
            raise ValidationError(
                f"'{text}' is not a valid date. Use YYYY-MM-DD or DD/MM/YYYY, for example 2026-12-31."
            )
    if not MIN_YEAR <= parsed.year <= MAX_YEAR:
        raise ValidationError(f"Year must be between {MIN_YEAR} and {MAX_YEAR}.")
    return parsed


def validate_timestamp(value) -> datetime | None:
    """Parse an optional timestamp (used by import). Blank gives None."""
    if isinstance(value, datetime):
        return value.replace(microsecond=0)
    text = clean_text(value)
    if not text:
        return None
    for fmt in TIMESTAMP_FORMATS:
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    day = validate_due_date(text)
    return datetime(day.year, day.month, day.day, 9, 0, 0)


def validate_notes(value) -> str:
    notes = clean_text(value)
    if len(notes) > NOTES_MAX:
        raise ValidationError(f"Notes are too long ({_chars(len(notes))}). Keep them to {NOTES_MAX} or fewer.")
    return notes


def validate_task_id(value, valid_ids: Iterable[int] | None = None) -> int:
    text = clean_text(value).lstrip("#")
    if not (text.isascii() and text.isdigit()):
        raise ValidationError("Enter the numeric task ID, for example 12.")
    number = int(text)
    if number < 1:
        raise ValidationError("Task IDs start at 1.")
    if valid_ids is not None and number not in set(valid_ids):
        raise ValidationError(f"No matching task with ID {number}.")
    return number


def validate_choice(value, choices: Iterable[str]) -> str:
    text = clean_text(value).casefold()
    options = [c.casefold() for c in choices]
    if text not in options:
        raise ValidationError(f"Please choose one of: {', '.join(choices)}.")
    return text


def validate_yes_no(value) -> bool:
    text = clean_text(value).casefold()
    if text in ("y", "yes"):
        return True
    if text in ("n", "no"):
        return False
    raise ValidationError("Please answer y or n.")
