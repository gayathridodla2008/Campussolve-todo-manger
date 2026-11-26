import sys, tempfile, unittest
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from taskcore import validation as v
from taskcore.manager import DuplicateTaskError, TaskManager, TaskNotFoundError
from taskcore.storage import TaskStore

TODAY = date(2026, 11, 22)
NOW = datetime(2026, 11, 22, 10, 0, 0)


class ManagerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "tasks.json"
        self.m = self._manager()

    def _manager(self):
        return TaskManager(TaskStore(self.path), today_fn=lambda: TODAY, now_fn=lambda: NOW)

    def tearDown(self):
        self.tmp.cleanup()

    def test_add_validates_and_persists(self):
        task = self.m.add("  Write   tests ", "exams", "h", "25/11/2026", "cover edge cases")
        self.assertEqual((task.id, task.title, task.category, task.priority, task.due_date),
                         (1, "Write tests", "Exams", "High", "2026-11-25"))
        self.assertEqual(self._manager().get(1).title, "Write tests")       # survives a restart

    def test_invalid_input_never_changes_state(self):
        for bad in ({"title": "ab"}, {"title": "Fine", "priority": "nope"},
                    {"title": "Fine", "due_date": "31/02/2026"}, {"title": "Fine", "category": ""}):
            with self.assertRaises(v.ValidationError):
                self.m.add(**bad)
        self.assertEqual(self.m.tasks, [])

    def test_duplicate_pending_title_is_blocked_unless_allowed(self):
        self.m.add("Submit report")
        with self.assertRaises(DuplicateTaskError):
            self.m.add("submit  REPORT")
        self.assertEqual(self.m.add("Submit report", allow_duplicate=True).id, 2)

    def test_same_title_allowed_after_completion(self):
        first = self.m.add("Submit lab report")
        self.m.complete(first.id)
        self.assertEqual(self.m.add("Submit lab report").id, 2)

    def test_complete_reopen_and_errors(self):
        task = self.m.add("Finish essay")
        self.m.complete(task.id)
        self.assertEqual(task.completed_at, "2026-11-22T10:00:00")
        with self.assertRaises(v.ValidationError):
            self.m.complete(task.id)
        self.m.reopen(task.id)
        self.assertIsNone(task.completed_at)
        with self.assertRaises(v.ValidationError):
            self.m.reopen(task.id)
        with self.assertRaises(TaskNotFoundError):
            self.m.complete(99)

    def test_update_and_clear_due_date(self):
        task = self.m.add("Plan trip", due_date="2026-12-01")
        self.m.update(task.id, title="Plan the trip", priority="Low", due_date=None)
        self.assertEqual((task.title, task.priority, task.due_date), ("Plan the trip", "Low", None))
        with self.assertRaises(v.ValidationError):
            self.m.update(task.id, priority="bogus", title="Should not apply")
        self.assertEqual(task.title, "Plan the trip")                       # failed update changed nothing

    def test_delete(self):
        task = self.m.add("Temporary task")
        self.m.delete(task.id)
        self.assertEqual(self._manager().tasks, [])

    def test_ids_stay_unique(self):
        a = self.m.add("First task")
        b = self.m.add("Second task")
        self.m.delete(a.id)
        c = self.m.add("Third task")
        self.assertEqual(len({t.id for t in self.m.tasks}), len(self.m.tasks))
        self.assertGreater(c.id, b.id)

    def test_search_by_keyword_category_status_priority(self):
        self.m.add("Revise DBMS notes", "Exams", "High", "2026-11-20", "normalisation")
        self.m.add("Buy groceries", "Personal", "Low", "2026-11-23")
        done = self.m.add("Old exam paper", "Exams", "Medium")
        self.m.complete(done.id)
        titles = lambda rows: [t.title for t in rows]
        self.assertEqual(titles(self.m.search("dbms")), ["Revise DBMS notes"])
        self.assertEqual(titles(self.m.search("NORMALISATION")), ["Revise DBMS notes"])   # notes + case-insensitive
        self.assertEqual(len(self.m.search(category="exams")), 2)
        self.assertEqual(titles(self.m.search(category="Exams", status="Pending")), ["Revise DBMS notes"])
        self.assertEqual(titles(self.m.search(priority="low")), ["Buy groceries"])
        self.assertEqual(titles(self.m.search("exam notes")), ["Revise DBMS notes"])       # category text is searched too
        self.assertEqual(titles(self.m.search("groceries notes")), [])                     # every term must match
        self.assertEqual(titles(self.m.search(overdue_only=True)), ["Revise DBMS notes"])

    def test_sorting(self):
        self.m.add("No date", "Personal", "Low")
        self.m.add("Later", "Personal", "Low", "2026-12-01")
        self.m.add("Sooner", "Personal", "Critical", "2026-11-25")
        self.assertEqual([t.title for t in self.m.search(sort_by="due")], ["Sooner", "Later", "No date"])
        self.assertEqual(self.m.search(sort_by="priority")[0].title, "Sooner")
        with self.assertRaises(v.ValidationError):
            self.m.search(sort_by="colour")


if __name__ == "__main__":
    unittest.main()
