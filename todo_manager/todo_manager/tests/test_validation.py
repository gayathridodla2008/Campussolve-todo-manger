import sys, unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from taskcore import validation as v


class TitleTests(unittest.TestCase):
    def test_boundaries(self):
        self.assertEqual(v.validate_title("Lab"), "Lab")
        self.assertEqual(len(v.validate_title("a" * 100)), 100)
        with self.assertRaises(v.ValidationError):
            v.validate_title("ab")
        with self.assertRaises(v.ValidationError):
            v.validate_title("a" * 101)

    def test_blank_and_symbols_only(self):
        for bad in ("", "   ", None, "!!!", "\t\n"):
            with self.assertRaises(v.ValidationError):
                v.validate_title(bad)

    def test_sanitises_whitespace_and_control_characters(self):
        self.assertEqual(v.validate_title("  Read \x00 chapter\t5 \n now  "), "Read chapter 5 now")

    def test_unicode_is_kept(self):
        self.assertEqual(v.validate_title("Café ☕ meeting"), "Café ☕ meeting")

    def test_singular_wording(self):
        with self.assertRaises(v.ValidationError) as ctx:
            v.validate_title("a")
        self.assertIn("1 character)", str(ctx.exception))


class DateTests(unittest.TestCase):
    def test_accepts_common_formats(self):
        expected = date(2026, 12, 31)
        for text in ("2026-12-31", "31-12-2026", "31/12/2026", "2026/12/31", " 2026-12-31 "):
            self.assertEqual(v.validate_due_date(text), expected, text)

    def test_blank_is_none_unless_required(self):
        self.assertIsNone(v.validate_due_date(""))
        with self.assertRaises(v.ValidationError):
            v.validate_due_date("", required=True)

    def test_rejects_impossible_and_out_of_range(self):
        for bad in ("31/02/2026", "tomorrow", "2026-13-01", "1999-01-01", "2101-01-01"):
            with self.assertRaises(v.ValidationError, msg=bad):
                v.validate_due_date(bad)

    def test_accepts_date_objects(self):
        self.assertEqual(v.validate_due_date(date(2026, 5, 1)), date(2026, 5, 1))


class OtherFieldTests(unittest.TestCase):
    def test_priority_names_initials_and_numbers(self):
        self.assertEqual(v.validate_priority("high"), "High")
        self.assertEqual(v.validate_priority("C"), "Critical")
        self.assertEqual(v.validate_priority("2"), "Medium")
        with self.assertRaises(v.ValidationError):
            v.validate_priority("urgent!!")

    def test_category_reuses_existing_spelling(self):
        self.assertEqual(v.validate_category("exams", ["Exams", "Clubs"]), "Exams")
        self.assertEqual(v.validate_category("Side Projects", ["Exams"]), "Side Projects")

    def test_category_rules(self):
        for bad in ("", "x", "a" * 31, "bad<script>", "semi;colon"):
            with self.assertRaises(v.ValidationError, msg=bad):
                v.validate_category(bad)
        self.assertEqual(v.validate_category("R&D / Labs"), "R&D / Labs")

    def test_task_id(self):
        self.assertEqual(v.validate_task_id("#12"), 12)
        for bad in ("", "abc", "-3", "0", "1.5", "²"):
            with self.assertRaises(v.ValidationError, msg=bad):
                v.validate_task_id(bad)
        with self.assertRaises(v.ValidationError):
            v.validate_task_id("5", valid_ids=[1, 2])

    def test_notes_limit(self):
        self.assertEqual(len(v.validate_notes("n" * 500)), 500)
        with self.assertRaises(v.ValidationError):
            v.validate_notes("n" * 501)

    def test_status_and_yes_no(self):
        self.assertEqual(v.validate_status("done"), "Completed")
        self.assertEqual(v.validate_status("open"), "Pending")
        with self.assertRaises(v.ValidationError):
            v.validate_status("maybe")
        self.assertTrue(v.validate_yes_no("Y"))
        self.assertFalse(v.validate_yes_no("no"))
        with self.assertRaises(v.ValidationError):
            v.validate_yes_no("perhaps")


if __name__ == "__main__":
    unittest.main()
