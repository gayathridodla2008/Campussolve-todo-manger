"""Executive summary metrics and threshold warnings."""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, timedelta

from .models import PRIORITIES, Task

HIGH_PRIORITY_LIMIT = 10        # more pending High/Critical tasks than this is a limit breach
FAR_FUTURE_DAYS = 730           # a due date further out than this looks like a typo
STALE_DAYS = 90                 # pending this long with no due date is flagged
LEVEL_ORDER = {"critical": 0, "warning": 1, "info": 2}


@dataclass
class Alert:
    level: str                  # critical | warning | info
    kind: str                   # overdue | due_soon | anomaly | limit
    message: str
    task_id: int | None = None


def _short(title: str, width: int = 44) -> str:
    return title if len(title) <= width else title[: width - 1] + "…"


def _plural(n: int, word: str) -> str:
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


def summarize(tasks: list[Task], today: date | None = None) -> dict:
    today = today or date.today()
    total = len(tasks)
    done = [t for t in tasks if t.completed]
    pending = [t for t in tasks if not t.completed]
    overdue = [t for t in pending if t.is_overdue(today)]
    due_today = [t for t in pending if t.due == today]
    week_end = today + timedelta(days=7)
    due_soon = [t for t in pending if t.due and today < t.due <= week_end]
    rate = round(len(done) / total * 100, 1) if total else 0.0

    # average days from creation to completion
    spans = []
    for t in done:
        if t.created_dt and t.completed_dt and t.completed_dt >= t.created_dt:
            spans.append((t.completed_dt - t.created_dt).total_seconds() / 86400)
    avg_days = round(sum(spans) / len(spans), 1) if spans else None

    # per category / per priority
    cat_rows = defaultdict(lambda: {"total": 0, "completed": 0, "pending": 0, "overdue": 0})
    pri_rows = {p: {"total": 0, "completed": 0, "pending": 0, "overdue": 0} for p in PRIORITIES}
    for t in tasks:
        for row in (cat_rows[t.category], pri_rows[t.priority]):
            row["total"] += 1
            row["completed" if t.completed else "pending"] += 1
            if t.is_overdue(today):
                row["overdue"] += 1
    by_category = [
        {"category": name, **row, "rate": round(row["completed"] / row["total"] * 100, 1)}
        for name, row in cat_rows.items()
    ]
    by_category.sort(key=lambda r: (-r["total"], r["category"].casefold()))
    by_priority = [{"priority": p, **pri_rows[p]} for p in PRIORITIES]

    # 7-day trend (today and the six days before it)
    created_per_day = Counter(t.created_dt.date() for t in tasks if t.created_dt)
    done_per_day = Counter(t.completed_dt.date() for t in done if t.completed_dt)
    trend = []
    for offset in range(6, -1, -1):
        day = today - timedelta(days=offset)
        trend.append({"date": day.isoformat(), "label": day.strftime("%a %d"),
                      "created": created_per_day.get(day, 0), "completed": done_per_day.get(day, 0)})
    this_week = sum(r["completed"] for r in trend)
    prev_week = sum(done_per_day.get(today - timedelta(days=d), 0) for d in range(7, 14))

    # status indicator
    if total == 0:
        status, message = "No data", "Add a task to get started."
    elif not overdue:
        status, message = "On track", "Nothing is overdue."
    else:
        ratio = len(overdue) / len(pending)
        urgent = any(t.priority in ("High", "Critical") for t in overdue)
        if ratio <= 0.25 and not urgent:
            status, message = "Needs attention", f"{_plural(len(overdue), 'task')} overdue."
        else:
            status, message = "Falling behind", f"{_plural(len(overdue), 'task')} overdue, including urgent work." if urgent \
                else f"{_plural(len(overdue), 'task')} overdue."

    # insights
    insights: list[str] = []
    if total == 0:
        insights.append("No tasks yet. Add one to start tracking progress.")
    else:
        insights.append(f"{len(done)} of {total} tasks are complete ({rate:.0f}%).")
        if overdue:
            worst = Counter(t.category for t in overdue).most_common(1)[0][0]
            insights.append(f"{_plural(len(overdue), 'pending task')} overdue; {worst} is the most affected category.")
        else:
            insights.append("Nothing is overdue.")
        insights.append(f"{len(due_today)} due today and {len(due_soon)} due in the next 7 days.")
        if this_week > prev_week:
            insights.append(f"Completion pace is up: {this_week} finished this week versus {prev_week} the week before.")
        elif this_week < prev_week:
            insights.append(f"Completion pace is down: {this_week} finished this week versus {prev_week} the week before.")
        elif this_week:
            insights.append(f"Completion pace is steady at {this_week} per week.")
        busiest = max(by_category, key=lambda r: r["pending"], default=None)
        if busiest and busiest["pending"]:
            insights.append(f"{busiest['category']} has the most pending work ({busiest['pending']}).")
        if avg_days is not None:
            insights.append(f"Tasks take {avg_days} day(s) on average to complete.")

    return {
        "total": total, "completed": len(done), "pending": len(pending),
        "completion_rate": rate, "overdue_count": len(overdue),
        "due_today_count": len(due_today), "due_soon_count": len(due_soon),
        "avg_completion_days": avg_days,
        "avg_completed_per_day": round(this_week / 7, 2),
        "by_category": by_category, "by_priority": by_priority, "trend": trend,
        "status": status, "status_message": message, "insights": insights,
        "as_of": today.isoformat(),
    }


def build_alerts(tasks: list[Task], today: date | None = None) -> list[Alert]:
    """Threshold warning indicators: overdue work, imminent deadlines, anomalies, limit breaches."""
    today = today or date.today()
    alerts: list[Alert] = []
    pending = [t for t in tasks if not t.completed]

    for t in pending:
        days = t.days_until_due(today)
        name = _short(t.title)
        urgent = t.priority in ("High", "Critical")
        if days is not None and days < 0:
            late = -days
            level = "critical" if urgent or late > 7 else "warning"
            alerts.append(Alert(level, "overdue", f"'{name}' is {_plural(late, 'day')} overdue (due {t.due_date}).", t.id))
        elif days == 0:
            alerts.append(Alert("warning" if urgent else "info", "due_soon", f"'{name}' is due today.", t.id))
        elif days == 1:
            alerts.append(Alert("info", "due_soon", f"'{name}' is due tomorrow.", t.id))
        if days is not None and days > FAR_FUTURE_DAYS:
            alerts.append(Alert("warning", "anomaly", f"'{name}' is due {t.due_date}, more than {FAR_FUTURE_DAYS // 365} years away. Is the date right?", t.id))
        if t.due_date is None:
            if t.priority == "Critical":
                alerts.append(Alert("warning", "anomaly", f"'{name}' is Critical but has no due date.", t.id))
            elif t.created_dt and (today - t.created_dt.date()).days > STALE_DAYS:
                age = (today - t.created_dt.date()).days
                alerts.append(Alert("info", "anomaly", f"'{name}' has been open {age} days with no due date.", t.id))

    for t in tasks:
        if t.completed and t.created_dt and t.completed_dt and t.completed_dt < t.created_dt:
            alerts.append(Alert("warning", "anomaly", f"'{_short(t.title)}' shows a completion time before its creation time.", t.id))

    groups = defaultdict(list)
    for t in pending:
        groups[t.title.casefold()].append(t)
    for group in groups.values():
        if len(group) > 1:
            alerts.append(Alert("warning", "anomaly", f"{len(group)} pending tasks share the title '{_short(group[0].title)}' (IDs {', '.join(str(g.id) for g in group)}).", group[0].id))

    high = sum(1 for t in pending if t.priority in ("High", "Critical"))
    if high > HIGH_PRIORITY_LIMIT:
        alerts.append(Alert("critical", "limit", f"Limit breach: {high} High/Critical tasks are pending (limit {HIGH_PRIORITY_LIMIT}). Consider re-prioritising."))

    alerts.sort(key=lambda a: (LEVEL_ORDER[a.level], a.task_id or 0))
    return alerts
