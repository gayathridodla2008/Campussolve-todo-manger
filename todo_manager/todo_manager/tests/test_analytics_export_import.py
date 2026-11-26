import csv, io, sys, tempfile, unittest
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from taskcore import analytics, exporter, importer, seed
from taskcore.manager import TaskManager
from taskcore.models import Task
from taskcore.storage import TaskStore

TODAY = date(2026, 11, 22)
NOW = datetime(2026, 11, 22, 10, 0, 0)


def make_manager(tmpdir, tasks=None):
    m = TaskManager(TaskStore(Path(tmpdir) / "tasks.json"), today_fn=lambda: TODAY, now_fn=lambda: NOW)
    if tasks is not None:
        m.replace_all(tasks)
    return m


class AnalyticsTests(unittest.TestCase):
    def test_empty_data(self):
        s = analytics.summarize([], TODAY)
        self.assertEqual((s["total"], s["completion_rate"], s["status"]), (0, 0.0, "No data"))
        self.assertIsNone(s["avg_completion_days"])
        self.assertEqual(analytics.build_alerts([], TODAY), [])

    def test_metrics_on_seed_data(self):
        tasks = seed.build_seed_tasks(TODAY, NOW)
        s = analytics.summarize(tasks, TODAY)
        self.assertEqual(s["total"], len(tasks))
        self.assertEqual(s["completed"] + s["pending"], s["total"])
        self.assertEqual(s["overdue_count"], 7)
        self.assertEqual(s["due_today_count"], 2)
        self.assertEqual(s["status"], "Falling behind")
        self.assertEqual(sum(r["total"] for r in s["by_category"]), s["total"])
        self.assertEqual(len(s["trend"]), 7)
        self.assertGreater(s["avg_completion_days"], 0)

    def test_status_levels(self):
        pending = lambda i, due, pri="Low": Task(id=i, title=f"Task {i}", due_date=due, priority=pri, created_at="2026-11-01T09:00:00")
        on_track = [pending(1, "2026-12-01")]
        self.assertEqual(analytics.summarize(on_track, TODAY)["status"], "On track")
        minor = [pending(i, "2026-12-01") for i in range(1, 6)] + [pending(9, "2026-11-20")]
        self.assertEqual(analytics.summarize(minor, TODAY)["status"], "Needs attention")
        urgent = [pending(1, "2026-11-20", "High"), pending(2, "2026-12-01")]
        self.assertEqual(analytics.summarize(urgent, TODAY)["status"], "Falling behind")

    def test_average_completion_time(self):
        t = Task(id=1, title="Done task", status="Completed", created_at="2026-11-10T09:00:00", completed_at="2026-11-14T09:00:00")
        self.assertEqual(analytics.summarize([t], TODAY)["avg_completion_days"], 4.0)

    def test_alert_rules(self):
        tasks = [
            Task(id=1, title="Late and urgent", priority="High", due_date="2026-11-20", created_at="2026-11-01T09:00:00"),
            Task(id=2, title="Due today", due_date="2026-11-22", created_at="2026-11-01T09:00:00"),
            Task(id=3, title="Far away", due_date="2031-01-01", created_at="2026-11-01T09:00:00"),
            Task(id=4, title="Critical undated", priority="Critical", created_at="2026-11-01T09:00:00"),
            Task(id=5, title="Twin", created_at="2026-11-01T09:00:00"),
            Task(id=6, title="twin", created_at="2026-11-01T09:00:00"),
            Task(id=7, title="Time traveller", status="Completed", created_at="2026-11-10T09:00:00", completed_at="2026-11-09T09:00:00"),
        ]
        messages = " | ".join(a.message for a in analytics.build_alerts(tasks, TODAY))
        for fragment in ("2 days overdue", "due today", "years away", "no due date", "share the title", "before its creation"):
            self.assertIn(fragment, messages)

    def test_limit_breach(self):
        tasks = [Task(id=i, title=f"Urgent {i}", priority="High", created_at="2026-11-01T09:00:00") for i in range(1, 12)]
        alerts = analytics.build_alerts(tasks, TODAY)
        self.assertTrue(any(a.kind == "limit" and a.level == "critical" for a in alerts))


class ExportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.tasks = seed.build_seed_tasks(TODAY, NOW)

    def tearDown(self):
        self.tmp.cleanup()

    def test_all_formats_are_written(self):
        for kind, suffix in (("markdown", ".md"), ("text", ".txt"), ("csv", ".csv")):
            path = exporter.write_export(kind, self.tasks, self.tmp.name, TODAY, NOW)
            self.assertEqual(path.suffix, suffix)
            self.assertGreater(path.stat().st_size, 200)
        with self.assertRaises(ValueError):
            exporter.write_export("pdf", self.tasks, self.tmp.name)

    def test_markdown_contents_and_pipe_escaping(self):
        tasks = [Task(id=1, title="A | B", created_at="2026-11-01T09:00:00")]
        md = exporter.render_markdown(tasks, TODAY, NOW)
        self.assertIn("# To-Do List Manager: Summary Report", md)
        self.assertIn("A \\| B", md)
        self.assertIn("## Warnings", md)

    def test_csv_round_trip_and_formula_protection(self):
        tasks = [Task(id=1, title="=1+1 budget check", notes="@home", created_at="2026-11-01T09:00:00")]
        rows = list(csv.DictReader(io.StringIO(exporter.render_csv(tasks))))
        self.assertEqual(rows[0]["title"], "'=1+1 budget check")
        self.assertEqual(rows[0]["notes"], "'@home")
        m = make_manager(self.tmp.name)
        result = importer.import_csv_text(exporter.render_csv(tasks), m)
        self.assertEqual(result.imported, 1)
        self.assertEqual(m.tasks[0].title, "=1+1 budget check")             # apostrophe removed on re-import

    def test_chart_is_optional(self):
        try:
            import matplotlib  # noqa: F401
        except ImportError:
            with self.assertRaises(RuntimeError):
                exporter.write_chart(self.tasks, self.tmp.name, TODAY, NOW)
        else:
            self.assertTrue(exporter.write_chart(self.tasks, self.tmp.name, TODAY, NOW).exists())


class ImportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.m = make_manager(self.tmp.name, seed.build_seed_tasks(TODAY, NOW))

    def tearDown(self):
        self.tmp.cleanup()

    def test_legacy_sample_reports_each_bad_row(self):
        before = len(self.m.tasks)
        result = importer.import_csv_text(seed.build_legacy_csv(TODAY), self.m, log_dir=self.tmp.name)
        self.assertTrue(result.ok)
        self.assertEqual((result.imported, result.skipped), (9, 6))
        self.assertEqual(len(self.m.tasks), before + 9)
        bad_rows = {row for row, _ in result.errors}
        self.assertEqual(bad_rows, {9, 10, 11, 12, 13, 14})              # spreadsheet row numbers
        messages = " | ".join(msg for _, msg in result.errors)
        for fragment in ("Title is required", "not a valid date", "Priority must be", "too long", "Status must be", "Duplicate"):
            self.assertIn(fragment, messages)
        self.assertTrue(result.log_path.exists())
        self.assertIn("Row ", result.log_path.read_text())
        self.assertEqual(TaskManager(TaskStore(self.m.store.path)).tasks[-1].title, self.m.tasks[-1].title)   # saved once

    def test_done_status_is_imported_as_completed(self):
        result = importer.import_csv_text("task,status\nReturn lab keys,Done\n", self.m)
        self.assertEqual(result.imported, 1)
        self.assertEqual(self.m.tasks[-1].status, "Completed")

    def test_missing_title_column_is_fatal(self):
        result = importer.import_csv_text("name_of_thing,priority\nx,high\n", self.m)
        self.assertFalse(result.ok)
        self.assertIn("title", result.fatal)

    def test_empty_file_and_unknown_columns(self):
        self.assertFalse(importer.import_csv_text("", self.m).ok)
        result = importer.import_csv_text("title,colour\nPaint the fence,blue\n\n,\n", self.m)
        self.assertEqual((result.imported, result.skipped), (1, 0))
        self.assertEqual(result.ignored_columns, ["colour"])

    def test_missing_file(self):
        self.assertIn("not found", importer.import_csv_file(Path(self.tmp.name) / "nope.csv", self.m).fatal)

    def test_non_utf8_file(self):
        path = Path(self.tmp.name) / "latin.csv"
        path.write_bytes("title\nCaf\xe9 plan\n".encode("cp1252"))
        self.assertEqual(importer.import_csv_file(path, self.m).imported, 1)
        self.assertEqual(self.m.tasks[-1].title, "Café plan")


class SeedTests(unittest.TestCase):
    def test_seed_is_valid_and_varied(self):
        tasks = seed.build_seed_tasks(TODAY, NOW)
        self.assertTrue(30 <= len(tasks) <= 50)
        self.assertEqual(len({t.id for t in tasks}), len(tasks))
        for t in tasks:                                                     # every record passes the storage schema
            Task.from_dict(t.to_dict())
        titles = [len(t.title) for t in tasks]
        self.assertIn(3, titles)
        self.assertIn(100, titles)
        self.assertTrue(any(t.due_date is None for t in tasks))
        self.assertTrue(any(not t.completed and t.is_overdue(TODAY) for t in tasks))
        for t in tasks:
            if t.completed:
                self.assertGreaterEqual(t.completed_dt, t.created_dt)
                self.assertLessEqual(t.completed_dt, NOW)


if __name__ == "__main__":
    unittest.main()
