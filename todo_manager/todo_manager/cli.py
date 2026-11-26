#!/usr/bin/env python3
"""CampusSolve To-Do List Manager: menu-driven terminal interface.

Run:  python cli.py            (data is stored in data/tasks.json)
      python cli.py --data my_tasks.json
Type /cancel at any prompt to go back to the menu.
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import date
from pathlib import Path

from taskcore import analytics, exporter, importer, seed
from taskcore import validation as v
from taskcore.manager import DuplicateTaskError, SORT_OPTIONS, TaskManager
from taskcore.models import PRIORITIES, Task
from taskcore.storage import StorageError, TaskStore

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_DATA = Path(os.environ.get("TODO_DATA_FILE", BASE_DIR / "data" / "tasks.json"))
EXPORT_DIR = BASE_DIR / "exports"
PAGE_SIZE = 10

if os.name == "nt":                      # enable ANSI colours in the Windows console
    os.system("")

_CODES = {"bold": "1", "dim": "2", "red": "31", "green": "32", "yellow": "33", "blue": "34",
          "magenta": "35", "cyan": "36"}


class Cancel(Exception):
    """Raised when the user types /cancel."""


# --------------------------------------------------------------------- styling
def color_on() -> bool:
    return sys.stdout.isatty() and "NO_COLOR" not in os.environ


def unicode_ok() -> bool:
    return "utf" in (getattr(sys.stdout, "encoding", "") or "").lower()


def style(text: str, *names: str) -> str:
    if not color_on() or not names:
        return text
    return "\033[" + ";".join(_CODES[n] for n in names) + "m" + text + "\033[0m"


def sym(kind: str) -> str:
    table = {"ok": ("✓", "OK"), "err": ("✗", "x"), "warn": ("▲", "!"), "bar": ("█", "#"), "ell": ("…", "~"), "dot": ("•", "-")}
    return table[kind][0 if unicode_ok() else 1]


def fit(text: str, width: int) -> str:
    return text if len(text) <= width else text[: width - 1] + sym("ell")


def banner() -> None:
    w = 54
    if unicode_ok():
        tl, tr, bl, br, h, vt = "╭", "╮", "╰", "╯", "─", "│"
    else:
        tl = tr = bl = br = "+"
        h, vt = "-", "|"
    lines = [("CampusSolve", ("bold", "cyan")), ("To-Do List Manager", ("bold",)),
             ("Add, complete, search and review your tasks", ("dim",))]
    print(style(tl + h * w + tr, "cyan"))
    for text, names in lines:
        pad = w - len(text)
        print(style(vt, "cyan") + " " * (pad // 2) + style(text, *names) + " " * (pad - pad // 2) + style(vt, "cyan"))
    print(style(bl + h * w + br, "cyan"))


def heading(text: str) -> None:
    print("\n" + style(text, "bold", "cyan"))
    print(style("-" * len(text), "dim"))


def ok(msg: str) -> None:
    print(style(f"  {sym('ok')} {msg}", "green"))


def fail(msg: str) -> None:
    print(style(f"  {sym('err')} {msg}", "red"))


def note(msg: str) -> None:
    print(style(f"  {msg}", "dim"))


# --------------------------------------------------------------------- prompts
def ask(prompt: str, validator=None, *, default=None, optional: bool = False):
    """Prompt until the validator accepts the input. Blank uses the default (or None if optional)."""
    if default not in (None, ""):
        suffix = f" [{default}]"
    elif optional:
        suffix = " (optional, Enter to skip)"
    else:
        suffix = ""
    while True:
        text = input(f"  {prompt}{suffix}: ").strip()
        if text.lower() == "/cancel":
            raise Cancel
        if not text:
            if default is not None and default != "":
                text = str(default)
            elif optional or default == "":
                return None
        try:
            return validator(text) if validator else text
        except v.ValidationError as err:
            fail(str(err))


def confirm(prompt: str, default: bool = False) -> bool:
    answer = ask(f"{prompt} (y/n)", v.validate_yes_no, default="y" if default else "n")
    return answer


# ---------------------------------------------------------------------- tables
COLUMNS = [("ID", 4, ">"), ("Title", 36, "<"), ("Category", 12, "<"), ("Priority", 8, "<"), ("Due", 10, "<"), ("Status", 9, "<")]
_PRIORITY_STYLE = {"Low": ("dim",), "Medium": (), "High": ("yellow",), "Critical": ("red", "bold")}


def render_table(tasks: list[Task], today: date) -> list[str]:
    def cell(text, width, align):
        text = fit(str(text), width)
        return f"{text:>{width}}" if align == ">" else f"{text:<{width}}"

    header = "  ".join(cell(n, w, a) for n, w, a in COLUMNS)
    lines = [style(header, "bold"), style("  ".join("-" * w for _, w, _ in COLUMNS), "dim")]
    for t in tasks:
        due = t.due_date or "-"
        due_text = cell(due, 10, "<")
        if t.is_overdue(today):
            due_text = style(due_text, "red")
        elif t.due == today and not t.completed:
            due_text = style(due_text, "yellow")
        status = cell(t.status, 9, "<")
        if t.completed:
            status = style(status, "green")
        lines.append("  ".join([
            cell(t.id, 4, ">"), cell(t.title, 36, "<"), cell(t.category, 12, "<"),
            style(cell(t.priority, 8, "<"), *_PRIORITY_STYLE[t.priority]), due_text, status,
        ]))
    return lines


def show_paged(tasks: list[Task], today: date) -> None:
    if not tasks:
        note("No tasks match.")
        return
    pages = (len(tasks) + PAGE_SIZE - 1) // PAGE_SIZE
    page = 0
    while True:
        print()
        print("\n".join("  " + line for line in render_table(tasks[page * PAGE_SIZE:(page + 1) * PAGE_SIZE], today)))
        note(f"Page {page + 1} of {pages}, {len(tasks)} task(s)")
        if pages == 1:
            return
        move = ask("[n]ext, [p]revious or [q]uit the list", lambda s: v.validate_choice(s, ["n", "p", "q"]), default="q")
        if move == "q":
            return
        if move == "n":
            if page + 1 < pages:
                page += 1
            else:
                note("You are on the last page.")
        elif page > 0:
            page -= 1
        else:
            note("You are on the first page.")


def bar(value: float, maximum: float, width: int = 20) -> str:
    filled = 0 if maximum <= 0 else round(width * value / maximum)
    return sym("bar") * filled


# --------------------------------------------------------------------- actions
def pick_category(manager: TaskManager, default: str | None = None) -> str:
    note("Categories: " + ", ".join(manager.categories()) + "  (type a new one to create it)")
    return ask("Category", lambda s: v.validate_category(s, manager.categories()), default=default or "Personal")


def add_task(manager: TaskManager) -> None:
    heading("Add a task")
    note("Type /cancel at any prompt to go back.")
    title = ask("Title", v.validate_title)
    category = pick_category(manager)
    priority = ask("Priority (Low, Medium, High, Critical)", v.validate_priority, default="Medium")
    due = ask("Due date (YYYY-MM-DD or DD/MM/YYYY)", v.validate_due_date, optional=True)
    notes = ask("Notes", v.validate_notes, optional=True) or ""
    try:
        task = manager.add(title, category, priority, due, notes)
    except DuplicateTaskError as err:
        fail(str(err))
        if not confirm("Add it anyway?"):
            return
        task = manager.add(title, category, priority, due, notes, allow_duplicate=True)
    ok(f"Added task {task.id}: {task.title}")
    if task.is_overdue(manager.today()):
        print(style(f"  {sym('warn')} That due date is already in the past, so the task is overdue.", "yellow"))


def view_tasks(manager: TaskManager) -> None:
    heading("View tasks")
    status = ask("Show [a]ll, [p]ending or [c]ompleted", lambda s: v.validate_choice(s, ["a", "p", "c"]), default="p")
    status_value = {"a": None, "p": "Pending", "c": "Completed"}[status]
    sort_by = ask(f"Sort by ({', '.join(SORT_OPTIONS)})", lambda s: v.validate_choice(s, SORT_OPTIONS), default="due")
    show_paged(manager.search(status=status_value, sort_by=sort_by), manager.today())


def complete_task(manager: TaskManager) -> None:
    heading("Complete a task")
    pending = manager.search(status="Pending")
    if not pending:
        note("Nothing is pending. Well done!")
        return
    note("Next up:")
    print("\n".join("  " + line for line in render_table(pending[:PAGE_SIZE], manager.today())))
    task_id = ask("ID of the task to complete", lambda s: v.validate_task_id(s, [t.id for t in pending]))
    task = manager.complete(task_id)
    ok(f"Completed task {task.id}: {task.title}")


def search_tasks(manager: TaskManager) -> None:
    heading("Search tasks")
    keyword = ask("Keyword (title, notes or category)", v.clean_text, optional=True)
    note("Categories: " + ", ".join(manager.categories()))
    category = ask("Category filter", v.clean_text, optional=True)
    status = ask("Status ([a]ll, [p]ending, [c]ompleted)", lambda s: v.validate_choice(s, ["a", "p", "c"]), default="a")
    results = manager.search(keyword, category, {"a": None, "p": "Pending", "c": "Completed"}[status])
    note(f"{len(results)} result(s)")
    show_paged(results, manager.today())


def manage_task(manager: TaskManager) -> None:
    heading("Edit, reopen or delete a task")
    show_paged(manager.search(sort_by="id"), manager.today())
    task_id = ask("Task ID", lambda s: v.validate_task_id(s, [t.id for t in manager.tasks]))
    task = manager.get(task_id)
    action = ask("[e]dit, [r]eopen or [d]elete", lambda s: v.validate_choice(s, ["e", "r", "d"]))
    if action == "d":
        if confirm(f"Delete '{task.title}'?"):
            manager.delete(task_id)
            ok(f"Deleted task {task_id}.")
        return
    if action == "r":
        manager.reopen(task_id)
        ok(f"Reopened task {task_id}.")
        return
    note("Press Enter to keep the current value. Type 'none' to clear the due date.")
    title = ask("Title", v.validate_title, default=task.title)
    category = pick_category(manager, task.category)
    priority = ask("Priority", v.validate_priority, default=task.priority)
    due = ask("Due date", lambda s: None if s.casefold() in ("none", "-") else v.validate_due_date(s),
              default=task.due_date or "", optional=True)
    notes = ask("Notes", v.validate_notes, default=task.notes or "")
    manager.update(task_id, title=title, category=category, priority=priority, due_date=due, notes=notes or "")
    ok(f"Updated task {task_id}.")


def summary_report(manager: TaskManager) -> None:
    heading("Summary report")
    s = analytics.summarize(manager.tasks, manager.today())
    if not s["total"]:
        note("No tasks yet. Add one or load the sample data.")
        return
    tone = {"On track": "green", "Needs attention": "yellow", "Falling behind": "red"}.get(s["status"], "dim")
    print(f"  Status: {style(s['status'], 'bold', tone)}  {s['status_message']}")
    avg = "n/a" if s["avg_completion_days"] is None else f"{s['avg_completion_days']} days"
    print(f"\n  Total {s['total']}   Completed {s['completed']} ({s['completion_rate']}%)   "
          f"Pending {s['pending']}   Overdue {s['overdue_count']}")
    print(f"  Due today {s['due_today_count']}   Due in 7 days {s['due_soon_count']}   "
          f"Avg time to complete {avg}   Avg completed/day (7d) {s['avg_completed_per_day']}")
    print("\n  " + style("By category (completed / total)", "bold"))
    top = max((r["total"] for r in s["by_category"]), default=1)
    for r in s["by_category"]:
        print(f"  {fit(r['category'], 12):<12} {r['completed']:>2}/{r['total']:<2} {r['rate']:>5}%  "
              f"{style(bar(r['total'], top), 'cyan')}")
    print("\n  " + style("Pending by priority", "bold"))
    top = max((r["pending"] for r in s["by_priority"]), default=1)
    for r in s["by_priority"]:
        print(f"  {r['priority']:<9} {r['pending']:>2}  {style(bar(r['pending'], top), *_PRIORITY_STYLE[r['priority']])}")
    print("\n  " + style("Last 7 days (created / completed)", "bold"))
    top = max((max(r["created"], r["completed"]) for r in s["trend"]), default=1)
    for r in s["trend"]:
        print(f"  {r['label']:<7} {r['created']:>2} / {r['completed']:<2}  {style(bar(r['completed'], top), 'green')}")
    print("\n  " + style("Key trends", "bold"))
    for line in s["insights"]:
        print(f"  {sym('dot')} {line}")


def show_warnings(manager: TaskManager) -> None:
    heading("Warnings")
    alerts = analytics.build_alerts(manager.tasks, manager.today())
    if not alerts:
        ok("No warnings. Everything looks healthy.")
        return
    tone = {"critical": "red", "warning": "yellow", "info": "blue"}
    for a in alerts:
        print(f"  {style(a.level.upper().ljust(8), 'bold', tone[a.level])} {a.message}")


def export_reports(manager: TaskManager) -> None:
    heading("Export")
    print("  1  Markdown summary\n  2  Plain-text audit log\n  3  CSV of all tasks\n  4  Chart (PNG, needs matplotlib)\n  5  All of the above")
    choice = ask("Choose", lambda s: v.validate_choice(s, ["1", "2", "3", "4", "5"]))
    today = manager.today()
    kinds = {"1": ["markdown"], "2": ["text"], "3": ["csv"], "4": [], "5": ["markdown", "text", "csv"]}[choice]
    for kind in kinds:
        ok(f"Wrote {exporter.write_export(kind, manager.tasks, EXPORT_DIR, today)}")
    if choice in ("4", "5"):
        try:
            ok(f"Wrote {exporter.write_chart(manager.tasks, EXPORT_DIR, today)}")
        except RuntimeError as err:
            fail(str(err))


def import_tasks(manager: TaskManager) -> None:
    heading("Import tasks from CSV")
    note("Needs a 'title' column. Optional: category, priority, due_date, status, notes.")
    note(f"Try: {BASE_DIR / 'data' / 'legacy_import_sample.csv'}")
    path = ask("Path to the CSV file", None)
    result = importer.import_csv_file(path, manager, log_dir=EXPORT_DIR)
    if not result.ok:
        fail(result.fatal)
        return
    ok(f"Imported {result.imported} task(s), skipped {result.skipped}.")
    if result.ignored_columns:
        note("Ignored columns: " + ", ".join(result.ignored_columns))
    for row, message in result.errors[:10]:
        print(style(f"  row {row}: {message}", "yellow"))
    if len(result.errors) > 10:
        note(f"...and {len(result.errors) - 10} more in the log.")
    if result.log_path:
        note(f"Full error log: {result.log_path}")


def load_sample(manager: TaskManager) -> None:
    heading("Load sample data")
    if manager.tasks and not confirm(f"This replaces your {len(manager.tasks)} current task(s). Continue?"):
        return
    manager.replace_all(seed.build_seed_tasks(manager.today()))
    ok(f"Loaded {len(manager.tasks)} sample tasks.")


# ------------------------------------------------------------------ main loop
MENU = [
    ("1", "Add a task", add_task), ("2", "View tasks", view_tasks), ("3", "Complete a task", complete_task),
    ("4", "Search tasks", search_tasks), ("5", "Edit, reopen or delete", manage_task),
    ("6", "Summary report", summary_report), ("7", "Warnings", show_warnings),
    ("8", "Export reports", export_reports), ("9", "Import from CSV", import_tasks),
    ("10", "Load sample data", load_sample), ("0", "Exit", None),
]
ACTIONS = {key: func for key, _, func in MENU}


def print_menu() -> None:
    print()
    for key, label, _ in MENU:
        print(f"  {style(key.rjust(2), 'bold', 'cyan')}  {label}")


def startup_status(manager: TaskManager) -> None:
    for warning in manager.load_warnings:
        print(style(f"  {sym('warn')} {warning}", "yellow"))
    s = analytics.summarize(manager.tasks, manager.today())
    if not s["total"]:
        note("No tasks yet. Choose 1 to add one, or 10 to load sample data.")
        return
    parts = [f"{s['pending']} pending"]
    if s["overdue_count"]:
        parts.append(style(f"{s['overdue_count']} overdue", "red", "bold"))
    if s["due_today_count"]:
        parts.append(style(f"{s['due_today_count']} due today", "yellow"))
    print("  " + "   ".join(parts))


def run(manager: TaskManager) -> None:
    banner()
    startup_status(manager)
    while True:
        print_menu()
        try:
            choice = ask("Choose an option", lambda s: v.validate_choice(s, ACTIONS))
            if choice == "0":
                print(style("\n  Your tasks are saved. See you next time.\n", "cyan"))
                return
            ACTIONS[choice](manager)
        except Cancel:
            note("Cancelled.")
        except (v.ValidationError, StorageError) as err:
            fail(str(err))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="CampusSolve To-Do List Manager (terminal)")
    parser.add_argument("--data", default=str(DEFAULT_DATA), help="path to the JSON data file")
    args = parser.parse_args(argv)
    try:
        run(TaskManager(TaskStore(args.data)))
    except (KeyboardInterrupt, EOFError):
        print("\n  Goodbye. Your tasks are saved.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
