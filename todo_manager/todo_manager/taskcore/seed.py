"""Sample datasets: 40 realistic tasks (normal, boundary and edge cases) and a
legacy CSV with deliberately broken rows for demonstrating the importer.

Dates are generated relative to "today" so the demo always has overdue, due-today
and upcoming work. Re-run `python -m taskcore.seed` any time to refresh the files."""
from __future__ import annotations

import csv
import io
import json
from datetime import date, datetime, timedelta
from pathlib import Path

from .exporter import render_csv
from .models import Task, format_timestamp
from .storage import SCHEMA_VERSION

LONG_TITLE = "Write the full documentation for the CampusSolve To-Do List Manager covering setup, usage, testing and demo"[:100]

# (title, category, priority, due offset in days or None, status, created N days ago, days taken to complete, notes)
_SPECS = [
    # ---- completed ---------------------------------------------------------
    ("Submit DBMS assignment 3", "Assignments", "High", -12, "Completed", 20, 7, "Normalisation exercises 1 to 5"),
    ("Read chapter 5 – Operating Systems", "Academics", "Medium", -9, "Completed", 14, 4, ""),
    ("Pay hostel fees", "Finance", "High", -15, "Completed", 25, 9, "Paid through the college portal"),
    ("Register for the campus hackathon", "Clubs", "Medium", -20, "Completed", 30, 2, ""),
    ("Renew library card", "Personal", "Low", -6, "Completed", 12, 3, ""),
    ("Lab record – Experiment 7", "Assignments", "Medium", -4, "Completed", 10, 5, ""),
    ("Dentist appointment", "Health", "Medium", -3, "Completed", 9, 8, ""),
    ("Update résumé", "Personal", "Low", None, "Completed", 18, 6, "Added the hackathon project"),
    ("Café meeting ☕ with project mentor", "Projects", "Medium", -2, "Completed", 7, 5, "Unicode title test"),
    ("Quiz 2 revision", "Exams", "High", -1, "Completed", 6, 5, ""),
    ("Submit lab report", "Assignments", "Medium", -30, "Completed", 40, 10, "Same title appears again below"),
    ("Book train tickets for home", "Personal", "Low", -8, "Completed", 16, 2, ""),
    # ---- pending: overdue --------------------------------------------------
    ("Submit Software Engineering mini-project report", "Projects", "Critical", -3, "Pending", 21, None, "Include UML diagrams"),
    ("Complete Python hackathon prototype", "Projects", "High", -1, "Pending", 12, None, ""),
    ("Prepare slides for ML seminar", "Academics", "High", -5, "Pending", 15, None, "10 slides, 8 minutes"),
    ("Return borrowed textbooks", "Personal", "Low", -45, "Pending", 60, None, "Library fine is growing"),
    ("Submit scholarship renewal form", "Finance", "Critical", -10, "Pending", 30, None, "Needs the principal's signature"),
    ("Lab record – Experiment 8", "Assignments", "Medium", -2, "Pending", 8, None, ""),
    ("Fix typo in club newsletter", "Clubs", "Low", -95, "Pending", 100, None, "Stale task"),
    # ---- pending: due today / tomorrow ------------------------------------
    ("Data Structures quiz 3", "Exams", "High", 0, "Pending", 5, None, "Chapters 6 to 8: trees and graphs"),
    ("Submit internship application", "Projects", "Critical", 0, "Pending", 9, None, ""),
    ("Group meeting – CampusSolve demo plan", "Projects", "Medium", 1, "Pending", 3, None, ""),
    ("Pick up printed poster", "Clubs", "Low", 1, "Pending", 2, None, ""),
    # ---- pending: upcoming -------------------------------------------------
    ("Study for Computer Networks mid-sem", "Exams", "High", 4, "Pending", 10, None, "Focus on routing and TCP"),
    ("Write blog post on the hackathon", "Clubs", "Low", 6, "Pending", 4, None, ""),
    ("Gym membership renewal", "Health", "Low", 7, "Pending", 3, None, ""),
    ("Pay semester exam fee", "Finance", "High", 9, "Pending", 6, None, ""),
    ("Prepare DBMS viva questions", "Exams", "Medium", 12, "Pending", 4, None, ""),
    ("Plan weekend trip with friends", "Personal", "Low", 14, "Pending", 2, None, ""),
    ("Apply for travel concession card", "Personal", "Medium", 18, "Pending", 1, None, ""),
    ("Finalize project poster design", "Projects", "Medium", 21, "Pending", 5, None, ""),
    ("Complete online course module 4", "Academics", "Medium", 25, "Pending", 7, None, ""),
    ("Annual health check-up", "Health", "Medium", 40, "Pending", 3, None, ""),
    # ---- pending: boundary and edge cases ---------------------------------
    ("Lab", "Academics", "Low", 10, "Pending", 2, None, "Shortest allowed title (3 characters)"),
    (LONG_TITLE, "Projects", "Medium", 20, "Pending", 3, None, "Longest allowed title (100 characters)"),
    ("Buy graph paper & markers", "Personal", "Low", 3, "Pending", 1, None, "Special character in the title"),
    ("Plan final-year capstone roadmap", "Projects", "Medium", 800, "Pending", 1, None, "Due date is far in the future"),
    ("Renew passport", "Personal", "Critical", None, "Pending", 2, None, "Critical with no due date"),
    ("Organise college fest volunteers", "Clubs", "High", 15, "Pending", 3, None, ""),
    ("Call mentor about thesis topic", "Academics", "High", None, "Pending", 100, None, "Open for a long time with no date"),
    ("Submit lab report", "Assignments", "Medium", 8, "Pending", 1, None, "Recurring: pending again after the completed one"),
]


def build_seed_tasks(today: date | None = None, now: datetime | None = None) -> list[Task]:
    today = today or date.today()
    now = (now or datetime.now()).replace(microsecond=0)
    tasks = []
    for number, (title, cat, pri, offset, status, created_ago, took, notes) in enumerate(_SPECS, start=1):
        created = datetime.combine(today - timedelta(days=created_ago), datetime.min.time())
        created += timedelta(hours=8 + (number * 3) % 10, minutes=(number * 7) % 60)
        created = min(created, now - timedelta(minutes=5))
        completed = None
        if status == "Completed":
            completed = min(created + timedelta(days=took), now - timedelta(minutes=1))
            completed = max(completed, created + timedelta(minutes=30))
        due = (today + timedelta(days=offset)).isoformat() if offset is not None else None
        tasks.append(Task(
            id=number, title=title, category=cat, priority=pri, due_date=due, status=status,
            notes=notes, created_at=format_timestamp(created),
            completed_at=format_timestamp(completed) if completed else None,
        ))
    return tasks


def build_legacy_csv(today: date | None = None) -> str:
    """A legacy-style CSV (different headers, DD/MM/YYYY dates) with 6 deliberately bad rows."""
    today = today or date.today()

    def d(offset):
        return (today + timedelta(days=offset)).strftime("%d/%m/%Y")

    rows = [
        ["Task", "Category", "Priority", "Deadline", "Status", "Notes"],
        ["Revise probability notes", "Exams", "High", d(5), "Pending", "Unit 3 and 4"],
        ["Clean up GitHub repository", "Projects", "Low", d(11), "Pending", ""],
        ["Collect hall ticket", "Academics", "Critical", d(2), "Pending", ""],
        ["Return lab keys", "Personal", "Low", d(-1), "Done", "Already returned"],
        ["Order project stationery", "Projects", "Medium", d(6), "Pending", ""],
        ["Mock interview with placement cell", "Academics", "High", d(13), "Pending", ""],
        ["Watch DevOps tutorial", "Academics", "Low", "", "Pending", "No deadline"],
        ["", "Personal", "Medium", d(4), "Pending", "ERROR: blank title"],
        ["Submit form 16", "Finance", "Medium", "31/02/" + str(today.year + 1), "Pending", "ERROR: impossible date"],
        ["Call the electrician", "Personal", "Urgent!!", d(3), "Pending", "ERROR: unknown priority"],
        ["x" * 120, "Personal", "Low", d(9), "Pending", "ERROR: title longer than 100 characters"],
        ["Finish reading assigned paper", "Academics", "Medium", d(7), "Maybe", "ERROR: unknown status"],
        ["Data Structures quiz 3", "Exams", "High", d(0), "Pending", "ERROR: duplicate of a pending task in the seed data"],
        ["Prepare farewell speech", "Clubs", "Medium", d(30), "Pending", ""],
        ["Back up laptop files", "Personal", "Low", d(16), "Pending", ""],
    ]
    buffer = io.StringIO()
    csv.writer(buffer, lineterminator="\n").writerows(rows)
    return buffer.getvalue()


def write_seed_files(directory, today: date | None = None) -> list[Path]:
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    tasks = build_seed_tasks(today)
    json_path = directory / "seed_tasks.json"
    json_path.write_text(json.dumps({"schema_version": SCHEMA_VERSION, "tasks": [t.to_dict() for t in tasks]},
                                    indent=2, ensure_ascii=False), encoding="utf-8")
    csv_path = directory / "seed_tasks.csv"
    csv_path.write_text(render_csv(tasks), encoding="utf-8", newline="")
    legacy_path = directory / "legacy_import_sample.csv"
    legacy_path.write_text(build_legacy_csv(today), encoding="utf-8", newline="")
    return [json_path, csv_path, legacy_path]


if __name__ == "__main__":
    out = Path(__file__).resolve().parent.parent / "data"
    for p in write_seed_files(out):
        print("wrote", p)
