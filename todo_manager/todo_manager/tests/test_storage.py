import json, sys, tempfile, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from taskcore.models import Task
from taskcore.storage import TaskStore


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "data" / "tasks.json"

    def tearDown(self):
        self.tmp.cleanup()

    def test_missing_file_creates_clean_template(self):
        store = TaskStore(self.path)
        self.assertEqual(store.load(), [])
        self.assertTrue(self.path.exists())
        self.assertEqual(json.loads(self.path.read_text())["tasks"], [])

    def test_round_trip_keeps_unicode(self):
        store = TaskStore(self.path)
        task = Task(id=1, title="Café ☕ meeting", category="Projects", priority="High",
                    due_date="2026-12-01", notes="résumé", created_at="2026-11-01T09:00:00")
        store.save([task])
        loaded = TaskStore(self.path).load()
        self.assertEqual(loaded, [task])

    def test_corrupted_json_is_backed_up_and_reset(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_text("{ this is not json", encoding="utf-8")
        store = TaskStore(self.path)
        self.assertEqual(store.load(), [])
        self.assertTrue(any("not valid JSON" in w for w in store.warnings))
        self.assertTrue(list(self.path.parent.glob("tasks.json.corrupt-*")))
        self.assertEqual(json.loads(self.path.read_text())["tasks"], [])

    def test_empty_file_is_handled(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_text("  \n", encoding="utf-8")
        store = TaskStore(self.path)
        self.assertEqual(store.load(), [])
        self.assertTrue(any("empty" in w for w in store.warnings))

    def test_wrong_top_level_shape(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_text('{"tasks": "nope"}', encoding="utf-8")
        store = TaskStore(self.path)
        self.assertEqual(store.load(), [])
        self.assertTrue(store.warnings)

    def test_invalid_records_are_skipped_not_fatal(self):
        self.path.parent.mkdir(parents=True)
        records = [
            {"id": 1, "title": "Good one", "priority": "High"},
            {"id": 2, "title": "", "priority": "High"},
            {"id": 3, "title": "Bad priority", "priority": "Whatever"},
            {"id": 4, "title": "Bad date", "due_date": "31/12/2026"},
            {"id": 1, "title": "Duplicate id"},
            "not an object",
        ]
        self.path.write_text(json.dumps({"tasks": records}), encoding="utf-8")
        store = TaskStore(self.path)
        tasks = store.load()
        self.assertEqual([t.id for t in tasks], [1])
        self.assertEqual(len([w for w in store.warnings if w.startswith("Skipped")]), 5)
        self.assertTrue(list(self.path.parent.glob("tasks.json.skipped-*")))

    def test_legacy_bare_list_is_accepted(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_text(json.dumps([{"id": 7, "title": "Old format task"}]), encoding="utf-8")
        self.assertEqual(TaskStore(self.path).load()[0].id, 7)

    def test_pending_task_drops_stray_completed_at(self):
        task = Task.from_dict({"id": 1, "title": "Stray", "status": "Pending", "completed_at": "2026-01-01T10:00:00"})
        self.assertIsNone(task.completed_at)

    def test_save_leaves_no_temp_file(self):
        store = TaskStore(self.path)
        store.save([Task(id=1, title="One")])
        self.assertFalse(list(self.path.parent.glob("*.tmp")))


if __name__ == "__main__":
    unittest.main()
