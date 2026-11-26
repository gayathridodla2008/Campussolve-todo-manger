# CampusSolve To-Do List Manager

Project #101 from the CampusSolve hackathon brief: a Python application to **add, complete, search and save tasks to a JSON file**, with strict input validation, local persistence, summary reporting and a modern GUI.

You get two interfaces on top of one shared engine:

| Interface | Command | Needs |
|---|---|---|
| Terminal app (the brief's required interface) | `python cli.py` | Python 3.10+, nothing else |
| Streamlit GUI (the brief's optional "modern GUI") | `streamlit run app.py` | `pip install -r requirements.txt` |

Both read and write the same file, `data/tasks.json`, so you can switch between them freely.

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt    # only needed for the GUI (and optional PNG charts)

python cli.py                      # terminal app
streamlit run app.py               # GUI, opens in your browser
python -m unittest discover -s tests -t .    # run the tests
```

On first launch there are no tasks. In the terminal choose **10 Load sample data**; in the GUI use the **Load sample data** button. Set `TODO_DATA_FILE=/path/to/file.json` (or `python cli.py --data FILE`) to use a different data file.

## Features and where they live

**Must-have**

| Requirement | Where |
|---|---|
| Interactive terminal interface | `cli.py`: menu loop, ANSI colour, paginated fixed-width tables, `/cancel` at any prompt |
| Defensive input validation | `taskcore/validation.py`: one set of validators used by the terminal, the GUI and the importer |
| Core logic: add, complete, search, save | `taskcore/manager.py` (also edit, reopen, delete, sort) |
| Local data persistence | `taskcore/storage.py`: atomic JSON writes, schema checks, corruption recovery |
| Keyword and category search | `TaskManager.search()`; terminal menu 4; GUI **Tasks** page |
| Executive summary | `taskcore/analytics.py`: totals, completion rate, averages, per-category and per-priority tables, 7-day trend, status indicator, written insights |

**Stretch**

| Feature | Where |
|---|---|
| Markdown, plain-text audit log and CSV export | `taskcore/exporter.py`; terminal menu 8; GUI **Reports** page |
| Threshold warning indicators | `analytics.build_alerts()`: overdue, due today/tomorrow, far-future dates, Critical with no date, duplicates, impossible timestamps, and a limit breach above 10 pending High/Critical tasks |
| GUI | `app.py` (Streamlit) |
| Bulk CSV import with row-by-row error log | `taskcore/importer.py`; terminal menu 9; GUI **Import** page |
| Matplotlib chart (brief, step 7) | `exporter.write_chart()`, optional: skipped with a clear message if matplotlib is not installed |

## Validation rules

| Field | Rule |
|---|---|
| Title | 3 to 100 characters, at least one letter or digit; control characters removed and whitespace collapsed |
| Category | 2 to 30 characters: letters, numbers, spaces and `& / _ -`; matches existing categories case-insensitively |
| Priority | Low, Medium, High, Critical (also `l/m/h/c` or `1`-`4`) |
| Due date | optional; `YYYY-MM-DD`, `DD/MM/YYYY` or `DD-MM-YYYY`; real calendar dates only; years 2000 to 2100. Past dates are allowed but flagged as overdue |
| Notes | optional, up to 500 characters |
| Duplicates | a second *pending* task with the same title is blocked unless you confirm |

## How the key challenges from the brief are handled

* **Corrupted, unformatted or missing storage.** A missing or empty file becomes a clean template. Invalid JSON is renamed to `tasks.json.corrupt-<time>` and a fresh file is started. Individual bad records are skipped (original kept as `tasks.json.skipped-<time>`) rather than failing the whole load. Writes are atomic, so a crash mid-save cannot damage the file.
* **Invalid, non-numeric or blank input.** Every prompt loops until valid input is given and explains how to fix it. The GUI shows the same messages next to the field and disables **Add task** until the form is valid.
* **Readable output at scale.** Fixed-width columns, truncation with an ellipsis, and 10-per-page pagination in the terminal; 8-per-page cards with filters in the GUI.

## Sample data

`data/` contains:

* `seed_tasks.json` and `seed_tasks.csv`: 41 tasks, with normal entries, overdue and due-today work, a 3-character and a 100-character title, Unicode (`Café ☕`), special characters, a far-future date, tasks with no date, a stale task and a recurring title.
* `legacy_import_sample.csv`: a legacy-style file (different headers, `DD/MM/YYYY` dates) with 9 good rows and 6 deliberately bad ones, to demonstrate the import error log.

Dates are relative to the day the files were generated. Loading sample data from either app regenerates them relative to today. To refresh the files: `python -m taskcore.seed`.

## Demo script (matches section 9 of the brief)

1. `python cli.py`: show the branded welcome screen and menu.
2. Choose **10** to load sample data, then **1** and add a task. Enter `ab` as the title and `32/13/2026` as the date to show validation catching them.
3. Choose **7** (warnings) and **6** (summary) to show analytics and trends.
4. Choose **0**, run `python cli.py` again, choose **2**: the tasks are still there.
5. Choose **8**, then **5**, to export Markdown, audit log, CSV and chart to `exports/`.
6. Run `streamlit run app.py` for the GUI. Try **Import** with `legacy_import_sample.csv` to see the skipped-rows table.

## Project layout

```
cli.py              terminal app
app.py              Streamlit GUI
taskcore/           engine (standard library only)
  models.py  validation.py  storage.py  manager.py
  analytics.py  exporter.py  importer.py  seed.py
data/               sample datasets (your own tasks.json is created here)
exports/            generated reports, charts and import error logs
tests/              56 tests, including an end-to-end terminal journey
.streamlit/         GUI theme colour
```

## Notes

* The GUI follows your system's light or dark theme (you can also switch it from Streamlit's settings menu).
* It needs Streamlit 1.40 or newer.
* Spreadsheet safety: exports prefix cells that start with `=`, `+`, `-` or `@` with an apostrophe so Excel cannot run them as formulas. The importer removes that apostrophe on the way back in.
