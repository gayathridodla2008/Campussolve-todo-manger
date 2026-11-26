"""Multi-format export: Markdown summary, plain-text audit log, CSV, optional chart."""
from __future__ import annotations

import csv
import io
from datetime import date, datetime
from pathlib import Path

from .analytics import Alert, build_alerts, summarize
from .models import Task

CSV_COLUMNS = ["id", "title", "category", "priority", "due_date", "status", "notes", "created_at", "completed_at"]
_FORMULA_PREFIXES = ("=", "+", "-", "@")


def _csv_safe(value) -> str:
    """Stop spreadsheet apps from running a cell as a formula (CSV injection)."""
    text = "" if value is None else str(value)
    return "'" + text if text.startswith(_FORMULA_PREFIXES) else text


def render_csv(tasks: list[Task]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(CSV_COLUMNS)
    for t in tasks:
        row = t.to_dict()
        writer.writerow([
            row["id"], _csv_safe(row["title"]), _csv_safe(row["category"]), row["priority"],
            row["due_date"] or "", row["status"], _csv_safe(row["notes"]),
            row["created_at"] or "", row["completed_at"] or "",
        ])
    return buffer.getvalue()


def _md(text) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ")


def render_markdown(tasks: list[Task], today: date | None = None, now: datetime | None = None) -> str:
    today = today or date.today()
    now = now or datetime.now()
    s = summarize(tasks, today)
    alerts = build_alerts(tasks, today)
    avg = "n/a" if s["avg_completion_days"] is None else f"{s['avg_completion_days']} days"
    out = [
        "# To-Do List Manager: Summary Report", "",
        f"_Generated {now:%Y-%m-%d %H:%M}_", "",
        f"**Status: {s['status']}.** {s['status_message']}", "",
        "## Key metrics", "",
        "| Metric | Value |", "|---|---|",
        f"| Total tasks | {s['total']} |",
        f"| Completed | {s['completed']} ({s['completion_rate']}%) |",
        f"| Pending | {s['pending']} |",
        f"| Overdue | {s['overdue_count']} |",
        f"| Due today | {s['due_today_count']} |",
        f"| Due in next 7 days | {s['due_soon_count']} |",
        f"| Average time to complete | {avg} |",
        f"| Average completed per day (last 7 days) | {s['avg_completed_per_day']} |", "",
        "## Key trends", "",
    ]
    out += [f"- {line}" for line in s["insights"]]
    out += ["", "## By category", "", "| Category | Total | Done | Pending | Overdue | Completion |", "|---|---|---|---|---|---|"]
    out += [f"| {_md(r['category'])} | {r['total']} | {r['completed']} | {r['pending']} | {r['overdue']} | {r['rate']}% |" for r in s["by_category"]]
    out += ["", "## By priority", "", "| Priority | Total | Done | Pending | Overdue |", "|---|---|---|---|---|"]
    out += [f"| {r['priority']} | {r['total']} | {r['completed']} | {r['pending']} | {r['overdue']} |" for r in s["by_priority"]]
    out += ["", "## Last 7 days", "", "| Day | Created | Completed |", "|---|---|---|"]
    out += [f"| {r['label']} | {r['created']} | {r['completed']} |" for r in s["trend"]]
    out += ["", "## Warnings", ""]
    out += [f"- **{a.level.upper()}**: {_md(a.message)}" for a in alerts] or ["- No warnings."]
    out += ["", "## All tasks", "", "| ID | Title | Category | Priority | Due | Status |", "|---|---|---|---|---|---|"]
    out += [f"| {t.id} | {_md(t.title)} | {_md(t.category)} | {t.priority} | {t.due_date or '-'} | {t.status} |" for t in tasks]
    return "\n".join(out) + "\n"


def render_audit_log(tasks: list[Task], today: date | None = None, now: datetime | None = None) -> str:
    today = today or date.today()
    now = now or datetime.now()
    s = summarize(tasks, today)
    alerts = build_alerts(tasks, today)
    bar = "=" * 78
    lines = [bar, "TO-DO LIST MANAGER: AUDIT LOG", f"Generated : {now:%Y-%m-%d %H:%M:%S}",
             f"As of     : {today.isoformat()}", bar, "",
             f"Status    : {s['status']} ({s['status_message']})",
             f"Tasks     : {s['total']} total, {s['completed']} completed, {s['pending']} pending",
             f"Overdue   : {s['overdue_count']}",
             f"Completion: {s['completion_rate']}%", "", "WARNINGS", "-" * 78]
    lines += [f"[{a.level.upper():8}] {a.message}" for a in alerts] or ["None."]
    lines += ["", "TASK REGISTER", "-" * 78,
              f"{'ID':>4}  {'Title':<40} {'Category':<12} {'Pri':<8} {'Due':<10} Status"]
    for t in tasks:
        title = t.title if len(t.title) <= 40 else t.title[:39] + "…"
        lines.append(f"{t.id:>4}  {title:<40} {t.category[:12]:<12} {t.priority:<8} {(t.due_date or '-'):<10} {t.status}")
        if t.notes:
            lines.append(f"      notes: {t.notes}")
        lines.append(f"      created {t.created_at or '-'}" + (f", completed {t.completed_at}" if t.completed_at else ""))
    lines += ["", bar, "END OF LOG", bar]
    return "\n".join(lines) + "\n"


def write_export(kind: str, tasks: list[Task], directory, today: date | None = None, now: datetime | None = None) -> Path:
    """Write one export file and return its path. kind: markdown | text | csv."""
    now = now or datetime.now()
    stamp = now.strftime("%Y%m%d-%H%M%S")
    renderers = {
        "markdown": (f"todo_report_{stamp}.md", lambda: render_markdown(tasks, today, now)),
        "text": (f"todo_audit_{stamp}.txt", lambda: render_audit_log(tasks, today, now)),
        "csv": (f"todo_tasks_{stamp}.csv", lambda: render_csv(tasks)),
    }
    if kind not in renderers:
        raise ValueError(f"Unknown export kind '{kind}'. Use one of: {', '.join(renderers)}.")
    name, render = renderers[kind]
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_text(render(), encoding="utf-8", newline="")
    return path


def write_chart(tasks: list[Task], directory, today: date | None = None, now: datetime | None = None) -> Path:
    """Optional Matplotlib chart. Raises RuntimeError when matplotlib is not installed."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError as err:
        raise RuntimeError("Charts need matplotlib. Install it with: pip install matplotlib") from err
    today = today or date.today()
    now = now or datetime.now()
    s = summarize(tasks, today)
    fig, axes = plt.subplots(1, 3, figsize=(15, 4.6))
    cats = [r["category"] for r in s["by_category"]]
    axes[0].bar(cats, [r["completed"] for r in s["by_category"]], color="#0E7C7B", label="Completed")
    axes[0].bar(cats, [r["pending"] for r in s["by_category"]], bottom=[r["completed"] for r in s["by_category"]],
                color="#E9A23B", label="Pending")
    axes[0].set_title("Tasks by category")
    axes[0].tick_params(axis="x", rotation=40)
    axes[0].legend()
    pri = s["by_priority"]
    axes[1].bar([r["priority"] for r in pri], [r["pending"] for r in pri],
                color=["#6B7A8F", "#0E7C7B", "#E9A23B", "#D64933"])
    axes[1].set_title("Pending tasks by priority")
    labels = [r["label"] for r in s["trend"]]
    axes[2].plot(labels, [r["created"] for r in s["trend"]], marker="o", color="#6B7A8F", label="Created")
    axes[2].plot(labels, [r["completed"] for r in s["trend"]], marker="o", color="#0E7C7B", label="Completed")
    axes[2].set_title("Last 7 days")
    axes[2].tick_params(axis="x", rotation=40)
    axes[2].legend()
    fig.suptitle(f"To-Do List Manager: {s['status']} ({s['completion_rate']}% complete)")
    fig.tight_layout()
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"todo_chart_{now:%Y%m%d-%H%M%S}.png"
    fig.savefig(path, dpi=130)
    plt.close(fig)
    return path
