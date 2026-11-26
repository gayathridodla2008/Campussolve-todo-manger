"""CampusSolve To-Do List Manager: modern Streamlit interface.

Run:  streamlit run app.py
It shares the same engine (taskcore) and the same data file as the terminal app.
"""
from __future__ import annotations

import html
import io
import math
import os
import zlib
from datetime import date
from pathlib import Path

import pandas as pd
import streamlit as st

from taskcore import analytics, exporter, importer, seed
from taskcore import validation as v
from taskcore.manager import DuplicateTaskError, TaskManager
from taskcore.models import PRIORITIES, Task
from taskcore.storage import StorageError, TaskStore

st.set_page_config(page_title="CampusSolve To-Do Manager", page_icon="✅", layout="wide",
                   initial_sidebar_state="expanded")

BASE_DIR = Path(__file__).resolve().parent
DATA_FILE = Path(os.environ.get("TODO_DATA_FILE", BASE_DIR / "data" / "tasks.json"))
EXPORT_DIR = BASE_DIR / "exports"
PAGE_SIZE = 8
NAV_PAGES = ["Dashboard", "Tasks", "Add task", "Reports", "Import"]
NEW_CATEGORY = "New category…"
PRIORITY_BAR = {"Low": "#6B7A8F", "Medium": "#0E7C7B", "High": "#E9A23B", "Critical": "#D64933"}
PRIORITY_TEXT = {"Low": "#55657A", "Medium": "#0B6665", "High": "#B7791F", "Critical": "#C0392B"}
LEVEL_COLOR = {"critical": "#D64933", "warning": "#E9A23B", "info": "#6B7A8F"}
STATUS_CLASS = {"On track": "ok", "Needs attention": "warn", "Falling behind": "bad", "No data": "idle"}
SORT_LABELS = {"due": "Due date", "priority": "Priority", "created": "Recently added", "title": "Title A to Z"}

CSS = """
@import url('https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:wght@500;700&family=Public+Sans:wght@400;500;600&display=swap');
.stApp, .stApp p, .stApp label, .stApp input, .stApp textarea, .stApp button, .stApp li {
  font-family: 'Public Sans', system-ui, -apple-system, 'Segoe UI', sans-serif; }
.stApp h1, .stApp h2, .stApp h3, .brand, [data-testid="stMetricValue"] {
  font-family: 'Bricolage Grotesque', 'Public Sans', system-ui, sans-serif; letter-spacing: -0.015em; }
.block-container { padding-top: 2.4rem; max-width: 1180px; }
.stApp h1 { font-size: 2.05rem; line-height: 1.15; margin: 0 0 .25rem 0; padding: 0; }
.stApp h2, .stApp h3 { margin-top: 1.4rem; }
.brand { font-size: 1.5rem; font-weight: 700; line-height: 1.1; }
.brand-sub { opacity: .7; font-size: .86rem; margin-bottom: 1.1rem; }
.hero { display: flex; align-items: flex-end; justify-content: space-between; gap: 1rem; margin-bottom: 1.1rem; }
.meta { opacity: .72; font-size: .88rem; }
.pill { display: inline-block; padding: 4px 14px; border-radius: 999px; font-weight: 600; font-size: .85rem; white-space: nowrap; }
.pill.ok { background: rgba(14,124,123,.16); color: #0E7C7B; }
.pill.warn { background: rgba(233,162,59,.20); color: #A8690B; }
.pill.bad { background: rgba(214,73,51,.16); color: #C0392B; }
.pill.idle { background: rgba(127,127,127,.18); }
[data-testid="stMetric"] { background: rgba(127,127,127,.08); border: 1px solid rgba(127,127,127,.22);
  border-radius: 12px; padding: 14px 16px; }
.task { border-left: 5px solid transparent; padding: .1rem 0 .15rem .85rem; }
.task-title { font-family: 'Bricolage Grotesque', 'Public Sans', sans-serif; font-weight: 600; font-size: 1.08rem; }
.task-title.done { text-decoration: line-through; opacity: .6; }
.task .meta { margin-top: .25rem; }
.task .notes { margin-top: .3rem; font-size: .88rem; opacity: .8; }
.chip { display: inline-block; padding: 1px 10px; margin-right: 6px; border-radius: 999px; font-size: .78rem;
  background: rgba(127,127,127,.18); }
.late { color: #D64933; font-weight: 600; }
.note { border-left: 4px solid transparent; padding: .45rem .8rem; margin: .35rem 0; border-radius: 0 8px 8px 0;
  background: rgba(127,127,127,.08); font-size: .92rem; }
.bar-row { display: grid; grid-template-columns: 74px 1fr 30px; gap: 10px; align-items: center; margin: .35rem 0; font-size: .9rem; }
.bar { height: 10px; border-radius: 6px; background: rgba(127,127,127,.2); overflow: hidden; }
.bar > i { display: block; height: 100%; border-radius: 6px; }
.hint { color: #D64933; font-size: .85rem; margin: -.35rem 0 .6rem 0; }
.hint.soft { color: #B7791F; }
"""


# ----------------------------------------------------------------------- state
def get_manager() -> TaskManager:
    """One manager per browser session. It re-reads the file on every run so edits
    made in the terminal app show up here."""
    manager = st.session_state.get("manager")
    if manager is None:
        manager = TaskManager(TaskStore(DATA_FILE))
        st.session_state["manager"] = manager
    else:
        manager.reload()
    return manager


def flash(kind: str, message: str) -> None:
    st.session_state["_flash"] = (kind, message)


def show_flash() -> None:
    item = st.session_state.pop("_flash", None)
    if item:
        kind, message = item
        st.toast(message, icon="✅" if kind == "success" else "⚠️")


def run_action(action, success):
    """Run a manager action from a button callback; report the outcome as a toast."""
    try:
        result = action()
    except (v.ValidationError, StorageError) as err:
        flash("error", str(err))
        return None
    flash("success", success(result) if callable(success) else success)
    return result


# ------------------------------------------------------------------- callbacks
def _mgr() -> TaskManager:
    return st.session_state["manager"]


def cb_goto(page: str) -> None:
    st.session_state["nav"] = page


def cb_complete(task_id: int) -> None:
    run_action(lambda: _mgr().complete(task_id), lambda t: f"Completed “{t.title}”")


def cb_reopen(task_id: int) -> None:
    run_action(lambda: _mgr().reopen(task_id), lambda t: f"Reopened “{t.title}”")


def cb_ask_delete(task_id: int) -> None:
    st.session_state["pending_delete"] = task_id


def cb_cancel_delete() -> None:
    st.session_state["pending_delete"] = None


def cb_confirm_delete(task_id: int) -> None:
    run_action(lambda: _mgr().delete(task_id), lambda t: f"Deleted “{t.title}”")
    st.session_state["pending_delete"] = None


def picker_date(day: date | None) -> date | None:
    """The date picker rejects dates outside its range, so hide out-of-range values."""
    return day if day and v.MIN_YEAR <= day.year <= v.MAX_YEAR else None


def edit_sig(task: Task) -> str:
    """Changes whenever the task changes, so the edit form never shows stale values."""
    raw = "|".join(str(x) for x in (task.title, task.category, task.priority, task.due_date, task.notes))
    return f"{task.id}_{zlib.crc32(raw.encode('utf-8')):x}"


def cb_save_edit(task_id: int, sig: str) -> None:
    ss = st.session_state
    run_action(
        lambda: _mgr().update(task_id, title=ss[f"e_title_{sig}"], category=ss[f"e_cat_{sig}"],
                              priority=ss[f"e_pri_{sig}"], due_date=ss[f"e_due_{sig}"], notes=ss[f"e_notes_{sig}"]),
        lambda t: f"Saved changes to “{t.title}”",
    )


def cb_add() -> None:
    ss = st.session_state
    category = ss["add_cat_new"] if ss["add_cat_choice"] == NEW_CATEGORY else ss["add_cat_choice"]
    task = run_action(
        lambda: _mgr().add(ss["add_title"], category, ss["add_priority"], ss["add_due"], ss["add_notes"],
                           allow_duplicate=ss.get("add_allow_dup", False)),
        lambda t: f"Added “{t.title}”",
    )
    if task:
        ss["add_title"], ss["add_notes"], ss["add_due"], ss["add_allow_dup"] = "", "", None, False
        if "add_cat_new" in ss:
            ss["add_cat_new"] = ""


def cb_load_sample() -> None:
    manager = _mgr()
    sample = seed.build_seed_tasks(manager.today())
    run_action(lambda: manager.replace_all(sample), f"Loaded {len(sample)} sample tasks")


# ------------------------------------------------------------------ rendering
def due_text(task: Task, today: date) -> str:
    if task.completed:
        return f"Completed {task.completed_at[:10]}" if task.completed_at else "Completed"
    days = task.days_until_due(today)
    if days is None:
        return "No due date"
    if days < 0:
        return f"<span class='late'>Overdue by {-days} day{'s' if days != -1 else ''}</span> (due {task.due_date})"
    if days == 0:
        return "<b>Due today</b>"
    if days == 1:
        return "Due tomorrow"
    return f"Due {task.due_date} (in {days} days)"


def task_html(task: Task, today: date) -> str:
    notes = f"<div class='notes'>{html.escape(task.notes[:160])}</div>" if task.notes else ""
    pri = (f"<span class='chip' style='background:{PRIORITY_BAR[task.priority]}2b;"
           f"color:{PRIORITY_TEXT[task.priority]};font-weight:600'>{task.priority}</span>")
    cls = "task-title done" if task.completed else "task-title"
    return (f"<div class='task' style='border-left-color:{PRIORITY_BAR[task.priority]}'>"
            f"<div class='{cls}'>{html.escape(task.title)}</div>"
            f"<div class='meta'>{pri}<span class='chip'>{html.escape(task.category)}</span>{due_text(task, today)}</div>"
            f"{notes}</div>")


def alert_html(alert) -> str:
    return f"<div class='note' style='border-left-color:{LEVEL_COLOR[alert.level]}'>{html.escape(alert.message)}</div>"


def bar_rows(rows: list[tuple[str, int, str]]) -> str:
    top = max((count for _, count, _ in rows), default=0) or 1
    return "".join(
        f"<div class='bar-row'><span>{html.escape(label)}</span>"
        f"<div class='bar'><i style='width:{count / top * 100:.0f}%;background:{color}'></i></div><b>{count}</b></div>"
        for label, count, color in rows)


def page_title(title: str, subtitle: str = "") -> None:
    sub = f"<div class='meta'>{subtitle}</div>" if subtitle else ""
    st.markdown(f"<div style='margin-bottom:1rem'><h1>{title}</h1>{sub}</div>", unsafe_allow_html=True)


def empty_state(manager: TaskManager) -> None:
    st.info("No tasks yet. Add your first task, or load the sample data to explore every feature.")
    left, right, _ = st.columns([1, 1, 3])
    left.button("Add a task", type="primary", on_click=cb_goto, args=("Add task",))
    right.button("Load sample data", on_click=cb_load_sample)


def render_task(task: Task, today: date, manager: TaskManager) -> None:
    sig = edit_sig(task)
    with st.container(border=True):
        st.markdown(task_html(task, today), unsafe_allow_html=True)
        if st.session_state.get("pending_delete") == task.id:
            st.markdown("**Delete this task permanently?**")
            yes, no, _ = st.columns([1, 1, 5])
            yes.button("Yes, delete", key=f"yes_{task.id}", type="primary", on_click=cb_confirm_delete, args=(task.id,))
            no.button("Keep it", key=f"no_{task.id}", on_click=cb_cancel_delete)
            return
        first, second, third, _ = st.columns([1.3, 1, 1, 4])
        if task.completed:
            first.button("Reopen", key=f"reopen_{task.id}", on_click=cb_reopen, args=(task.id,))
        else:
            first.button("Mark done", key=f"done_{task.id}", type="primary", on_click=cb_complete, args=(task.id,))
        with second.popover("Edit"):
            st.text_input("Title", value=task.title, key=f"e_title_{sig}")
            st.selectbox("Category", manager.categories(), key=f"e_cat_{sig}",
                         index=manager.categories().index(task.category))
            st.selectbox("Priority", list(PRIORITIES), index=PRIORITIES.index(task.priority), key=f"e_pri_{sig}")
            st.date_input("Due date", value=picker_date(task.due), key=f"e_due_{sig}", format="DD/MM/YYYY",
                          min_value=date(v.MIN_YEAR, 1, 1), max_value=date(v.MAX_YEAR, 12, 31))
            st.text_area("Notes", value=task.notes, key=f"e_notes_{sig}", height=90)
            st.button("Save changes", key=f"save_{sig}", type="primary", on_click=cb_save_edit, args=(task.id, sig))
        third.button("Delete", key=f"del_{task.id}", on_click=cb_ask_delete, args=(task.id,))


# ------------------------------------------------------------------------ pages
def page_dashboard(manager: TaskManager, today: date) -> None:
    s = analytics.summarize(manager.tasks, today)
    alerts = analytics.build_alerts(manager.tasks, today)
    st.markdown(
        f"<div class='hero'><div><h1>Where things stand</h1>"
        f"<div class='meta'>{today:%A}, {today.day} {today:%B %Y}</div></div>"
        f"<span class='pill {STATUS_CLASS[s['status']]}'>{s['status']}</span></div>", unsafe_allow_html=True)
    if not s["total"]:
        empty_state(manager)
        return

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total tasks", s["total"])
    c2.metric("Completed", s["completed"], f"{s['completion_rate']:.0f}%", delta_color="off")
    c3.metric("Pending", s["pending"])
    c4.metric("Overdue", s["overdue_count"],
              f"{s['due_today_count']} due today" if s["due_today_count"] else None, delta_color="off")
    st.progress(min(max(s["completion_rate"] / 100, 0.0), 1.0), text=f"{s['completion_rate']:.0f}% of all tasks are complete")

    left, right = st.columns([3, 2], gap="large")
    with left:
        st.subheader("Needs attention")
        if alerts:
            st.markdown("".join(alert_html(a) for a in alerts[:6]), unsafe_allow_html=True)
            if len(alerts) > 6:
                st.caption(f"{len(alerts) - 6} more on the Reports page.")
        else:
            st.success("Nothing needs attention right now.")
    with right:
        st.subheader("Coming up this week")
        soon = sorted((t for t in manager.tasks if not t.completed and t.due and 0 <= (t.due - today).days <= 7),
                      key=lambda t: (t.due, -PRIORITIES.index(t.priority)))
        if soon:
            for t in soon[:6]:
                st.markdown(
                    f"<div class='note' style='border-left-color:{PRIORITY_BAR[t.priority]}'><b>{html.escape(t.title)}</b><br>"
                    f"<span class='meta'>{due_text(t, today)}, {html.escape(t.category)}</span></div>", unsafe_allow_html=True)
        else:
            st.caption("Nothing is due in the next 7 days.")

    chart_left, chart_right = st.columns(2, gap="large")
    with chart_left:
        st.subheader("Workload by category")
        cats = pd.DataFrame(s["by_category"]).set_index("category")[["completed", "pending"]]
        cats.columns = ["Completed", "Pending"]
        st.bar_chart(cats, color=["#0E7C7B", "#E9A23B"])
    with chart_right:
        st.subheader("Last 7 days")
        trend = pd.DataFrame({"Created": [r["created"] for r in s["trend"]],
                              "Completed": [r["completed"] for r in s["trend"]]},
                             index=pd.to_datetime([r["date"] for r in s["trend"]]))
        st.line_chart(trend, color=["#6B7A8F", "#0E7C7B"])

    bottom_left, bottom_right = st.columns(2, gap="large")
    with bottom_left:
        st.subheader("Pending by priority")
        rows = [(r["priority"], r["pending"], PRIORITY_BAR[r["priority"]]) for r in reversed(s["by_priority"])]
        st.markdown(bar_rows(rows), unsafe_allow_html=True)
    with bottom_right:
        st.subheader("Key trends")
        st.markdown("\n".join(f"- {line}" for line in s["insights"]))


def page_tasks(manager: TaskManager, today: date) -> None:
    page_title("Tasks", "Search, filter and update your tasks.")
    if not manager.tasks:
        empty_state(manager)
        return
    f_search, f_cat, f_status, f_pri, f_sort = st.columns([3, 2, 2, 2, 2])
    keyword = f_search.text_input("Search", placeholder="Title, notes or category", key="f_keyword")
    category = f_cat.selectbox("Category", ["All"] + manager.categories(include_defaults=False), key="f_category")
    status = f_status.selectbox("Status", ["Pending", "Completed", "All"], key="f_status")
    priority = f_pri.selectbox("Priority", ["All"] + list(PRIORITIES), key="f_priority")
    sort_by = f_sort.selectbox("Sort by", list(SORT_LABELS), format_func=SORT_LABELS.get, key="f_sort")
    overdue_only = st.checkbox("Overdue only", key="f_overdue")

    try:
        results = manager.search(keyword, None if category == "All" else category, status, priority,
                                 overdue_only=overdue_only, sort_by=sort_by, descending=(sort_by == "created"))
    except v.ValidationError as err:
        st.error(str(err))
        return
    if not results:
        st.info("No tasks match these filters. Clear the search text or set Status to All.")
        return

    pages = max(1, math.ceil(len(results) / PAGE_SIZE))
    if st.session_state.get("f_page", 1) > pages:           # filters shrank the list: stay in range
        st.session_state["f_page"] = pages
    page = 1
    if pages > 1:
        page = int(st.number_input("Page", min_value=1, max_value=pages, step=1, key="f_page"))
    start = (page - 1) * PAGE_SIZE
    st.caption(f"Showing {start + 1} to {min(start + PAGE_SIZE, len(results))} of {len(results)} tasks")
    for task in results[start:start + PAGE_SIZE]:
        render_task(task, today, manager)


def page_add(manager: TaskManager, today: date) -> None:
    page_title("Add a task", "Fields are checked as you type.")
    form, preview = st.columns([3, 2], gap="large")
    ss = st.session_state
    with form:
        title = st.text_input("Title", key="add_title", placeholder="What needs doing?")
        categories = manager.categories()
        choice = st.selectbox("Category", categories + [NEW_CATEGORY], key="add_cat_choice",
                              index=categories.index("Personal") if "Personal" in categories else 0)
        new_category = ""
        if choice == NEW_CATEGORY:
            new_category = st.text_input("New category name", key="add_cat_new")
        st.radio("Priority", list(PRIORITIES), index=1, horizontal=True, key="add_priority")
        st.date_input("Due date (optional)", value=None, key="add_due", format="DD/MM/YYYY",
                      min_value=date(v.MIN_YEAR, 1, 1), max_value=date(v.MAX_YEAR, 12, 31))
        st.text_area("Notes (optional)", key="add_notes", height=100)

        problems, soft = [], []
        clean_title = None
        if title:
            try:
                clean_title = v.validate_title(title)
            except v.ValidationError as err:
                problems.append(f"Title: {err}")
        else:
            problems.append("")
        try:
            clean_category = v.validate_category(new_category if choice == NEW_CATEGORY else choice, manager.categories())
        except v.ValidationError as err:
            clean_category = None
            problems.append(f"Category: {err}")
        try:
            clean_notes = v.validate_notes(ss.get("add_notes", ""))
        except v.ValidationError as err:
            clean_notes = ""
            problems.append(f"Notes: {err}")
        due = ss.get("add_due")
        if due and due < today:
            soft.append("That date is in the past, so the task will start out overdue.")
        duplicate = manager.find_pending_duplicate(title) if clean_title else None
        if duplicate:
            soft.append(f"A pending task with this title already exists (ID {duplicate.id}).")
            st.checkbox("Add it anyway", key="add_allow_dup")
        for message in [p for p in problems if p]:
            st.markdown(f"<div class='hint'>{html.escape(message)}</div>", unsafe_allow_html=True)
        for message in soft:
            st.markdown(f"<div class='hint soft'>{html.escape(message)}</div>", unsafe_allow_html=True)
        blocked = bool(problems) or (duplicate is not None and not ss.get("add_allow_dup", False))
        st.button("Add task", type="primary", disabled=blocked, on_click=cb_add)

    with preview:
        st.subheader("Preview")
        if clean_title and clean_category:
            sample = Task(id=0, title=clean_title, category=clean_category, priority=ss.get("add_priority", "Medium"),
                          due_date=due.isoformat() if due else None, notes=clean_notes)
            with st.container(border=True):
                st.markdown(task_html(sample, today), unsafe_allow_html=True)
        else:
            st.caption("Your task will appear here once the title is valid.")


def page_reports(manager: TaskManager, today: date) -> None:
    page_title("Reports", "Totals, trends and warnings, ready to export.")
    s = analytics.summarize(manager.tasks, today)
    alerts = analytics.build_alerts(manager.tasks, today)
    if not s["total"]:
        empty_state(manager)
        return
    st.markdown(f"<span class='pill {STATUS_CLASS[s['status']]}'>{s['status']}</span> &nbsp; {html.escape(s['status_message'])}",
                unsafe_allow_html=True)
    st.markdown("\n".join(f"- {line}" for line in s["insights"]))

    st.subheader("By category")
    cat_df = pd.DataFrame(s["by_category"]).rename(columns={
        "category": "Category", "total": "Total", "completed": "Done", "pending": "Pending", "overdue": "Overdue", "rate": "Completion"})
    st.dataframe(cat_df, hide_index=True, column_config={
        "Completion": st.column_config.ProgressColumn("Completion", min_value=0, max_value=100, format="%.0f%%")})
    st.subheader("By priority")
    pri_df = pd.DataFrame(s["by_priority"]).rename(columns={
        "priority": "Priority", "total": "Total", "completed": "Done", "pending": "Pending", "overdue": "Overdue"})
    st.dataframe(pri_df, hide_index=True)

    st.subheader(f"Warnings ({len(alerts)})")
    if alerts:
        st.markdown("".join(alert_html(a) for a in alerts), unsafe_allow_html=True)
    else:
        st.success("No warnings. Everything looks healthy.")

    st.subheader("Export")
    stamp = f"{today:%Y%m%d}"
    d1, d2, d3 = st.columns(3)
    d1.download_button("Download Markdown report", exporter.render_markdown(manager.tasks, today),
                       file_name=f"todo_report_{stamp}.md", mime="text/markdown")
    d2.download_button("Download audit log (.txt)", exporter.render_audit_log(manager.tasks, today),
                       file_name=f"todo_audit_{stamp}.txt", mime="text/plain")
    d3.download_button("Download tasks (.csv)", exporter.render_csv(manager.tasks),
                       file_name=f"todo_tasks_{stamp}.csv", mime="text/csv")
    if st.button("Save a chart image to the exports folder"):
        try:
            path = exporter.write_chart(manager.tasks, EXPORT_DIR, today)
            st.image(str(path), caption=f"Saved to {path}")
        except RuntimeError as err:
            st.warning(str(err))


def page_import(manager: TaskManager, today: date) -> None:
    page_title("Import", "Bring in tasks from a CSV file, or load sample data.")
    st.subheader("Import from CSV")
    st.caption("The file needs a title column. Optional columns: category, priority, due_date, status, notes. "
               "Dates can be YYYY-MM-DD or DD/MM/YYYY.")
    upload = st.file_uploader("CSV file", type=["csv"])
    if upload is not None:
        raw = upload.getvalue()
        if len(raw) > importer.MAX_BYTES:
            st.error(f"That file is larger than {importer.MAX_BYTES // (1024 * 1024)} MB.")
        else:
            text = importer.decode_bytes(raw)
            try:
                st.dataframe(pd.read_csv(io.StringIO(text), dtype=str).head(10), hide_index=True)
                st.caption("Preview of the first 10 rows.")
            except (pd.errors.ParserError, pd.errors.EmptyDataError, ValueError):
                st.caption("No preview available. The importer will still check every row.")
            if st.button("Import tasks", type="primary"):
                try:
                    st.session_state["import_result"] = importer.import_csv_text(
                        text, manager, log_dir=EXPORT_DIR, source=upload.name)
                except StorageError as err:
                    st.error(str(err))

    result = st.session_state.get("import_result")
    if result is not None:
        if not result.ok:
            st.error(result.fatal)
        else:
            m1, m2 = st.columns(2)
            m1.metric("Imported", result.imported)
            m2.metric("Skipped", result.skipped)
            if result.ignored_columns:
                st.caption("Ignored columns: " + ", ".join(result.ignored_columns))
            if result.errors:
                st.markdown("**Rows that were skipped**")
                st.dataframe(pd.DataFrame(result.errors, columns=["Row", "Problem"]), hide_index=True)
                log = "\n".join(f"Row {n}: {msg}" for n, msg in result.errors) + "\n"
                st.download_button("Download error log", log, file_name="import_errors.log", mime="text/plain")
        st.button("Clear result", on_click=lambda: st.session_state.pop("import_result", None))

    st.subheader("Sample data")
    st.caption("41 realistic tasks with overdue, due-today, boundary and unusual cases, dated relative to today.")
    confirmed = True
    if manager.tasks:
        confirmed = st.checkbox(f"Replace my {len(manager.tasks)} current tasks with the sample data", key="confirm_sample")
    st.button("Load sample data", disabled=not confirmed, on_click=cb_load_sample)
    st.download_button("Download a CSV with deliberate errors to try the importer",
                       seed.build_legacy_csv(today), file_name="legacy_import_sample.csv", mime="text/csv")


PAGES = {"Dashboard": page_dashboard, "Tasks": page_tasks, "Add task": page_add,
         "Reports": page_reports, "Import": page_import}


def sidebar(manager: TaskManager, today: date) -> None:
    with st.sidebar:
        st.markdown("<div class='brand'>CampusSolve</div><div class='brand-sub'>To-Do List Manager</div>", unsafe_allow_html=True)
        st.radio("Go to", NAV_PAGES, key="nav", label_visibility="collapsed")
        s = analytics.summarize(manager.tasks, today)
        if s["total"]:
            st.markdown("---")
            st.caption(f"{s['pending']} pending, {s['overdue_count']} overdue, {s['due_today_count']} due today")
        st.caption(f"Saved automatically to {DATA_FILE.name}")
        for warning in manager.load_warnings:
            st.warning(warning)


def main() -> None:
    st.markdown(f"<style>{CSS}</style>", unsafe_allow_html=True)
    st.session_state.setdefault("nav", "Dashboard")
    manager = get_manager()
    today = manager.today()
    sidebar(manager, today)
    show_flash()
    PAGES[st.session_state["nav"]](manager, today)


main()
