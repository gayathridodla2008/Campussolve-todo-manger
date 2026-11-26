"""End-to-end test of the terminal app, following the hackathon demo script."""
import contextlib, io, sys, tempfile, unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import cli
from taskcore.manager import TaskManager
from taskcore.storage import TaskStore


def run_session(data_file, export_dir, answers):
    feed = iter(answers)
    out = io.StringIO()
    with mock.patch("builtins.input", lambda prompt="": next(feed)), \
         mock.patch.object(cli, "EXPORT_DIR", Path(export_dir)), \
         contextlib.redirect_stdout(out):
        code = cli.main(["--data", str(data_file)])
    return code, out.getvalue(), feed


class CliJourneyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.data = Path(self.tmp.name) / "tasks.json"
        self.exports = Path(self.tmp.name) / "exports"

    def tearDown(self):
        self.tmp.cleanup()

    def test_full_demo_journey_and_persistence(self):
        answers = [
            # add a task: validation rejects a short title and a bad date, then accepts good values
            "1", "ab", "Write unit tests", "", "", "32/13/2026", "25/11/2026", "",
            # adding the same title again is flagged; decline to add it anyway
            "1", "write unit tests", "", "", "", "", "n",
            # load the sample data (confirm replacing the current tasks)
            "10", "y",
            # view all pending tasks, go to the next page, then quit the list
            "2", "p", "due", "n", "q",
            # complete: reject text and an unknown id, then complete task 20
            "3", "abc", "9999", "20",
            # search by keyword
            "4", "quiz", "", "a",
            # analytics, warnings, export everything
            "6", "7", "8", "5",
            # reopen task 20 through the manage menu (quit the list first)
            "5", "q", "20", "r",
            # exit
            "0",
        ]
        code, out, remaining = run_session(self.data, self.exports, answers)
        self.assertEqual(code, 0)
        self.assertEqual(list(remaining), [])                         # every scripted answer was consumed

        for fragment in ("Title is too short", "not a valid date", "Added task 1", "already exists",
                         "Loaded 41 sample tasks", "Page 1 of", "Enter the numeric task ID",
                         "No matching task with ID 9999", "Completed task 20", "Summary report",
                         "Falling behind", "days overdue", "Reopened task 20"):
            self.assertIn(fragment, out)
        self.assertEqual(len(list(self.exports.glob("todo_*"))) >= 3, True)

        # restart: state must be preserved on disk
        again = TaskManager(TaskStore(self.data))
        self.assertEqual(len(again.tasks), 41)
        self.assertEqual(again.get(20).status, "Pending")

    def test_first_run_with_corrupted_file_does_not_crash(self):
        self.data.write_text("{{{ broken", encoding="utf-8")
        code, out, _ = run_session(self.data, self.exports, ["0"])
        self.assertEqual(code, 0)
        self.assertIn("not valid JSON", out)
        self.assertTrue(list(Path(self.tmp.name).glob("tasks.json.corrupt-*")))

    def test_import_flow_shows_row_errors(self):
        legacy = Path(__file__).resolve().parent.parent / "data" / "legacy_import_sample.csv"
        answers = ["10", "9", str(legacy), "0"]
        feed = iter(answers)
        out = io.StringIO()
        with mock.patch("builtins.input", lambda prompt="": next(feed)), \
             mock.patch.object(cli, "EXPORT_DIR", self.exports), contextlib.redirect_stdout(out):
            cli.main(["--data", str(self.data)])
        text = out.getvalue()
        self.assertIn("Imported 9 task(s), skipped 6", text)
        self.assertIn("row 9: Title is required", text)
        self.assertTrue(list(self.exports.glob("import_errors_*.log")))

    def test_ctrl_d_exits_cleanly(self):
        def raise_eof(prompt=""):
            raise EOFError
        out = io.StringIO()
        with mock.patch("builtins.input", raise_eof), contextlib.redirect_stdout(out):
            self.assertEqual(cli.main(["--data", str(self.data)]), 0)
        self.assertIn("Goodbye", out.getvalue())

    def test_cancel_returns_to_menu(self):
        code, out, _ = run_session(self.data, self.exports, ["1", "/cancel", "0"])
        self.assertIn("Cancelled", out)


if __name__ == "__main__":
    unittest.main()
