"""
Idaho Math Badging Survey — Diverging Bar Chart Visualizer
==========================================================
Run with no arguments for an interactive guided setup:

    python3 survey_viz.py

Or pass a CSV path to skip the file prompt:

    python3 survey_viz.py your_survey.csv
"""

import os
import re
import sys
import glob
import textwrap
from pathlib import Path

# Use the non-interactive Agg backend so matplotlib never tries to open
# a GUI window regardless of how the script is launched on Windows.
import matplotlib
matplotlib.use('Agg')

import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np
import pandas as pd

# Always resolve paths relative to the script's own folder,
# not wherever the user's terminal happens to be open.
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# ---------------------------------------------------------------------------
# Survey structure definition
# Edit this section when the survey instrument changes.
# ---------------------------------------------------------------------------

LIKERT_ORDER = [
    "Strongly Disagree",
    "Disagree",
    "Somewhat Disagree",
    "Somewhat Agree",
    "Agree",
    "Strongly Agree",
]

# Normalises Qualtrics mixed-case exports to a single canonical form
LIKERT_NORM = {
    "strongly disagree": "Strongly Disagree",
    "disagree":          "Disagree",
    "somewhat disagree": "Somewhat Disagree",
    "somewhat agree":    "Somewhat Agree",
    "agree":             "Agree",
    "strongly agree":    "Strongly Agree",
}

LIKERT_COLORS = {
    "Strongly Disagree": "#c0392b",
    "Disagree":          "#e07060",
    "Somewhat Disagree": "#f0b8a8",
    "Somewhat Agree":    "#a8c8f0",
    "Agree":             "#5090d0",
    "Strongly Agree":    "#1a5fa8",
}

CONSTRUCTS = [
    {
        "key":      "MUI",
        "title":    "Math Utility & Identity",
        "subtitle": "How much students see math as relevant and important to them",
        "items": [
            ("MUI_1_1", "It is important for me to do well in math"),
            ("MUI_1_2", "Math in school feels related to real life"),
            ("MUI_1_3", "Math relates to my goals after high school"),
            ("MUI_1_4", "I plan to take four years of math in high school"),
        ],
    },
    {
        "key":      "MEI",
        "title":    "Math Engagement & Interest",
        "subtitle": "How much students enjoy and are engaged by math",
        "items": [
            ("MEI_1_1", "I enjoy learning math"),
            ("MEI_1_7", "Math is interesting"),
            ("MEI_1_8", "I look forward to taking math"),
            ("MEI_1_9", "I find satisfaction in doing math"),
        ],
    },
    {
        "key":      "MCP",
        "title":    "Math Competence Perception",
        "subtitle": "How capable students believe themselves to be in mathematics",
        "items": [
            ("MCP_1_1",  "I understand the math I have studied"),
            ("MCP_1_12", "I can understand math in school"),
            ("MCP_1_13", "I can understand math outside of school"),
            ("MCP_1_14", "I can do well on math tests"),
            ("MCP_1_15", "I can overcome setbacks in math"),
            ("MCP_2_1",  "I am good at solving math problems"),
            ("MCP_2_12", "I can get good grades in math"),
            ("MCP_2_13", "Doing math is easy for me"),
            ("MCP_2_14", "Math is not a barrier for my future"),
        ],
    },
]

SINGLE_SELECT = [
    {
        "key":      "DE_Grade",
        "title":    "Current Grade Level",
        "subtitle": "Distribution of respondents by grade",
        "order":    ["9th", "10th", "11th", "12th"],
    },
    {
        "key":      "DE_Class",
        "title":    "Current Math Class",
        "subtitle": "Math course currently enrolled in",
        "order": [
            "Algebra 1 OR Math 1",
            "Geometry OR Math 2",
            "Algebra 2 OR Math 3",
            "Dual Credit Math Course",
        ],
    },
    {
        "key":          "B_7",
        "title":        "Next Planned Math Course",
        "subtitle":     "Badging students only — which course comes next",
        "badging_only": True,
        "order": [
            "Geometry (or Math 2)",
            "Algebra 2 (or Math 3 or equivalent)",
            "Pre-Calculus",
            "Calculus (AP or dual credit)",
            "Statistics (AP or dual credit)",
            "I do not plan to take any more math courses",
            "Other",
        ],
    },
    {
        "key":          "B_2",
        "title":        "Badging Class Progress",
        "subtitle":     "Where in their badging class students currently are",
        "badging_only": True,
        "order": [
            "Towards the beginning of my badging class",
            "In the middle of my badging class",
            "Towards the end of my badging class",
        ],
    },
    {
        "key":          "B_5",
        "title":        "Badge Awareness",
        "subtitle":     "Were students aware they could earn math badges?",
        "badging_only": True,
        "order":        ["Yes", "No"],
    },
]

MULTI_SELECT_CHARTS = [
    {
        "key":      "MUI_2",
        "title":    "Post-Graduation Plans",
        "subtitle": "What students plan to do after high school (select all that apply)",
    },
    {
        "key":      "MEI_2",
        "title":    "What Makes a Favourite Math Class",
        "subtitle": "Attributes of their favourite math class (select all that apply)",
    },
    {
        "key":      "MCP_3",
        "title":    "Sources of Math Difficulty",
        "subtitle": "What makes math class difficult (select all that apply)",
    },
    {
        "key":          "B_6",
        "title":        "Ideal Badge Uses",
        "subtitle":     "How students would ideally use their earned badges (select all that apply)",
        "badging_only": True,
    },
]

# ---------------------------------------------------------------------------
# Data selection & privacy  (approved LC State IRB, Idaho HS Math Survey)
# ---------------------------------------------------------------------------
# Each school's survey link ends in ?School=<code>, which Qualtrics records as
# the embedded-data column "School". A school keeps ONE code every year, so
# school years (1 July - 30 June) are told apart by RecordedDate, never by code.
# A school's report holds only that school's responses for one school year and
# goes only to the school's designated primary contact.

SCHOOL_COL = "School"
DATE_COL   = "RecordedDate"
YEAR_COL   = "_SchoolYear"           # helper column, dropped before charting

# Idaho Code 33-133 aggregate data; SBOE DMC minimum of 5. The IRB application
# commits to "no combination of data ... represented by n<6 students", so every
# count, bar and percentage shown must rest on at least MIN_CELL students.
MIN_CELL = 6
PRIVACY  = True                      # False only via --internal (never shared)

# Qualtrics Status values that are not real responses (labels and codes)
NOT_RESPONSES = {"Survey Preview", "Survey Test", "Spam", "1", "2", "8"}

COMBINED_LABEL = "Other (combined for privacy)"
ALL_COL        = "_All"              # one-group split used when a group is too small


def school_year(ts) -> str | None:
    """'2026-27' for any timestamp from 1 Jul 2026 through 30 Jun 2027."""
    if pd.isna(ts):
        return None
    start = ts.year if ts.month >= 7 else ts.year - 1
    return f"{start}-{(start + 1) % 100:02d}"


def year_span(year: str) -> str:
    start = int(year[:4])
    return f"1 July {start} – 30 June {start + 1}"


def protect_counts(counts: dict) -> dict:
    """
    Single-choice counts in which no shown category holds 1-5 students.
    Small categories are pooled into COMBINED_LABEL; if that pool is itself
    under MIN_CELL, the smallest remaining categories join it until it is not
    (so no small count can be worked out by subtraction). Returns {} when the
    whole group is too small to show.
    """
    if not PRIVACY:
        return counts
    keep   = {c: n for c, n in counts.items() if n == 0 or n >= MIN_CELL}
    pooled = sum(n for n in counts.values() if 0 < n < MIN_CELL)
    while 0 < pooled < MIN_CELL:
        live = [c for c, n in keep.items() if n > 0]
        if not live:
            return {}
        smallest = min(live, key=lambda c: keep[c])
        pooled  += keep.pop(smallest)
    if pooled:
        keep[COMBINED_LABEL] = pooled
    return keep


def protect_likert(counts: dict) -> tuple[str, dict]:
    """
    One Likert row ({category: n}). Returns
      ('full', counts)            every non-zero category has MIN_CELL+ students
      ('collapsed', {"Disagree": n, "Agree": n})   the two sides, each MIN_CELL+
      ('suppressed', {})          not even the two sides are safe to show
    """
    if not PRIVACY or all(n == 0 or n >= MIN_CELL for n in counts.values()):
        return "full", counts
    neg = sum(counts.get(c, 0) for c in LIKERT_ORDER[:3])
    pos = sum(counts.get(c, 0) for c in LIKERT_ORDER[3:])
    if all(n == 0 or n >= MIN_CELL for n in (neg, pos)):
        return "collapsed", {"Disagree": neg, "Agree": pos}
    return "suppressed", {}


# ---------------------------------------------------------------------------
# Interactive wizard
# ---------------------------------------------------------------------------

DIVIDER  = "─" * 62
DIVIDER2 = "═" * 62

# Column descriptions shown to the user during the split-column step.
# Add or update entries here whenever the survey instrument changes.
COLUMN_DESCRIPTIONS = {
    "B_1": "Are you currently a Math Badging student? (the primary split)",
    "B_5": "Were you aware you could earn math badges in this course?",
    "DE_Grade": "What grade are you in?  (not a Yes/No column)",
}


def _hr(double: bool = False):
    print(DIVIDER2 if double else DIVIDER)


def _blank():
    print()


def _ask(prompt: str, default: str = "") -> str:
    """
    Display a prompt and return the user's input.
    Returns `default` when the user just presses Enter.
    Exits cleanly on Ctrl-C or EOF.
    """
    display = f"  {prompt} [{default}]: " if default else f"  {prompt}: "
    try:
        val = input(display).strip()
    except (EOFError, KeyboardInterrupt):
        _blank()
        print("  Cancelled — no files were written.")
        sys.exit(0)
    if val.lower() == "q":
        _blank()
        print("  Cancelled — no files were written.")
        sys.exit(0)
    return val if val else default


def _warn(msg: str):
    print(f"\n  ⚠  {msg}")


def _err(msg: str):
    print(f"\n  ✗  {msg}")


def _ok(msg: str):
    print(f"  ✓  {msg}")


# ---------------------------------------------------------------------------
# Step helpers
# ---------------------------------------------------------------------------

def _find_csv_files() -> list[str]:
    """CSVs in the current working directory, newest first."""
    files = glob.glob(os.path.join(SCRIPT_DIR, "*.csv"))
    files.sort(key=os.path.getmtime, reverse=True)
    return files


def _find_zip_files() -> list[str]:
    """ZIP files in the current working directory."""
    files = glob.glob(os.path.join(SCRIPT_DIR, "*.zip"))
    files.sort(key=os.path.getmtime, reverse=True)
    return files


def _preflight_check():
    """
    Look for common problems before asking any questions.
    Warn about ZIPs (Qualtrics exports are often downloaded as ZIP).
    Return a list of warning strings (empty = all clear).
    """
    warnings = []
    zips = _find_zip_files()
    if zips:
        names = ", ".join(zips[:3])
        warnings.append(
            f"ZIP file(s) found: {names}\n"
            "     Qualtrics exports are sometimes downloaded as a ZIP archive.\n"
            "     If your CSV is inside a ZIP, you must extract it first:\n"
            "       • Windows: right-click the ZIP → 'Extract All'\n"
            "       • Mac: double-click the ZIP file\n"
            "     Then move the extracted .csv file into this same folder."
        )
    return warnings


def _step1_select_file(preselected: str | None) -> tuple[str, "pd.DataFrame"]:
    """
    STEP 1 — Locate and load the CSV.
    Handles: preselected path, nearby CSVs, manual path entry, bad files.
    Returns (csv_path, dataframe).
    """
    _blank()
    print("  STEP 1 of 4  —  Select your data file")
    _hr()
    print(
        "\n"
        "  This tool expects a Qualtrics survey export in CSV format.\n"
        "  The file must be:\n"
        "    • Unzipped  (a plain .csv file, not a .zip archive)\n"
        "    • Located in the same folder as this script  (survey_viz.py)\n"
        "    • Exported from Qualtrics using:  Data & Analysis → Export Data → CSV\n"
        "\n"
        "  If your file is still inside a ZIP, close this program, extract the ZIP,\n"
        "  and move the .csv file into this folder before running again."
    )
    _blank()

    # --- If a path was given on the command line, validate and use it ---
    if preselected:
        if preselected.lower().endswith(".zip"):
            _err(
                f"'{preselected}' is a ZIP file.\n"
                "     Please extract it and point to the .csv file inside."
            )
            sys.exit(1)
        if not os.path.isfile(preselected):
            _err(f"File not found: {preselected}")
            sys.exit(1)
        return _load_file(preselected)

    # --- Auto-detect CSVs in the current folder ---
    nearby = _find_csv_files()

    if nearby:
        print("  CSV files found in this folder (most recent first):")
        _blank()
        for i, f in enumerate(nearby[:9], 1):
            size_kb = os.path.getsize(f) // 1024
            mtime   = os.path.getmtime(f)
            import datetime
            age = datetime.datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M")
            print(f"    {i})  {f:<45}  {size_kb:>5} KB   {age}")
        _blank()
        print("    0)  My file is somewhere else — let me type the path")
        _hr()
        print(
            "  Tip: if you just exported from Qualtrics and the file is not listed,\n"
            "  make sure you moved it into this folder and that it ends in .csv\n"
            "  (not .xlsx or .zip)."
        )
        _blank()

        while True:
            choice = _ask("Enter a number to select a file, or 0 to type a path", default="1")
            if choice.isdigit():
                n = int(choice)
                if 1 <= n <= len(nearby[:9]):
                    return _load_file(nearby[n - 1])
                elif n == 0:
                    break  # fall through to manual entry
                else:
                    _warn(f"Please enter a number between 0 and {min(9, len(nearby))}.")
            elif os.path.isfile(choice):
                return _load_file(choice)
            elif choice.lower().endswith(".zip"):
                _warn(
                    "That is a ZIP file. Please extract it first and select the .csv inside.\n"
                    "     Windows: right-click → 'Extract All'   |   Mac: double-click the ZIP"
                )
            else:
                _warn(f"'{choice}' not found. Try again, or enter 0 to type a path manually.")

    else:
        # No CSVs at all
        _warn(
            "No CSV files were found in this folder.\n"
            "\n"
            "     Where to find your data file:\n"
            "       1. Log in to Qualtrics and open your survey.\n"
            "       2. Go to  Data & Analysis  →  Export & Import  →  Export Data.\n"
            "       3. Choose CSV format and click  Export Data.\n"
            "       4. The file will download, often inside a ZIP archive.\n"
            "       5. If it's a ZIP: extract it (right-click → Extract All on Windows;\n"
            "          double-click on Mac).\n"
            "       6. Move the .csv file into this folder:\n"
            f"          {SCRIPT_DIR}\n"
            "       7. Run this program again."
        )
        _blank()

    # --- Manual path entry (loop until valid) ---
    print("  Enter the full path to your CSV file.")
    print("  Tip: you can drag the file onto this window instead of typing the path.")
    _blank()
    while True:
        path = _ask("Path to CSV file")
        if not path:
            _warn("A file path is required. Press Ctrl-C to cancel.")
            continue
        path = path.strip("'\"")   # strip quotes that some OSes add when dragging
        if path.lower().endswith(".zip"):
            _warn(
                "That is a ZIP file. Please extract it first.\n"
                "     Windows: right-click → 'Extract All'   |   Mac: double-click the ZIP"
            )
            continue
        if not path.lower().endswith(".csv"):
            _warn(
                f"'{os.path.basename(path)}' doesn't look like a CSV file.\n"
                "     The file should end in  .csv  — make sure you exported as CSV,\n"
                "     not Excel (.xlsx) or another format."
            )
            cont = _ask("Try to open it anyway? [y/N]", default="N").lower()
            if cont not in ("y", "yes"):
                continue
        if not os.path.isfile(path):
            _err(f"File not found: {path}")
            _warn("Double-check the path, or drag the file onto this window.")
            continue
        return _load_file(path)


def _load_file(path: str) -> tuple[str, "pd.DataFrame"]:
    """Load and validate a CSV. Returns (path, df) or exits with a clear message."""
    print(f"\n  Loading {os.path.basename(path)} …")
    try:
        df = load_qualtrics(path)
    except Exception as exc:
        _err(
            f"Could not read the file: {exc}\n"
            "\n"
            "     Common causes:\n"
            "       • The file is open in Excel — close it and try again.\n"
            "       • The file is not a Qualtrics CSV export.\n"
            "       • The file is corrupted or only partially downloaded."
        )
        sys.exit(1)

    if len(df) == 0:
        _err(
            "The file loaded but contains no responses.\n"
            "     Make sure this is the actual response export, not just a\n"
            "     blank template or a file with only the header rows."
        )
        sys.exit(1)

    _ok(f"{len(df)} responses loaded from {os.path.basename(path)}")
    return path, df


def _pick(prompt: str, options: list[str], default: str = "1") -> str:
    """Numbered choice from `options`; returns the chosen option."""
    for i, opt in enumerate(options, 1):
        print(f"    {i})  {opt}")
    _blank()
    while True:
        choice = _ask(prompt, default=default)
        if choice.isdigit() and 1 <= int(choice) <= len(options):
            return options[int(choice) - 1]
        _warn(f"Please enter a number between 1 and {len(options)}.")


def _step_select_data(df: "pd.DataFrame", school: str | None = None,
                      year: str | None = None) -> tuple["pd.DataFrame", str | None, str | None]:
    """
    STEP 2 — Choose which responses go into the report: all schools, or ONE
    school's responses for ONE school year (the report that may go back to that
    school's designated primary contact). `school` / `year` come from the
    command line when given. Returns (filtered df, school or None, year or None).
    """
    _blank()
    print("  STEP 2 of 4  —  Choose which responses to include")
    _hr()

    if "Status" in df.columns:
        fake = df["Status"].astype(str).isin(NOT_RESPONSES)
        if fake.any():
            print(f"\n  Leaving out {int(fake.sum())} survey preview / test / spam row(s).")
            df = df[~fake]

    years = sorted(y for y in df[YEAR_COL].dropna().unique())
    has_school = SCHOOL_COL in df.columns
    codes = df[SCHOOL_COL].fillna("").astype(str).str.strip() if has_school else None

    print("\n  Responses by school year (1 July – 30 June, by recorded date):")
    for y in years:
        print(f"      {y}:  {int((df[YEAR_COL] == y).sum())}")
    if has_school:
        print("\n  Responses by school code (survey link ?School=...):")
        for code, n in codes.value_counts().sort_index().items():
            print(f"      {code or '(no code)':<16}  {n}")
    else:
        _warn(
            f"This file has no '{SCHOOL_COL}' column, so it cannot be split by school.\n"
            "     In Qualtrics, the Survey Flow needs an Embedded Data element named\n"
            "     School (set from the panel or URL) for the ?School= code to be saved."
        )
    _blank()

    if school is None and year is None:
        scopes = ["All schools  (statewide report)"]
        if has_school:
            scopes.append("One school, one school year  (report for that school's primary contact)")
        scope = _pick("Which report?", scopes) if len(scopes) > 1 else scopes[0]
        if scope.startswith("One school"):
            school = _pick("Which school code?", sorted(c for c in codes.unique() if c))
    if school is not None:
        if not has_school:
            _err(f"--school given, but this file has no '{SCHOOL_COL}' column.")
            sys.exit(1)
        if school not in set(codes):
            _err(f"No responses carry the school code '{school}' (codes are case sensitive).")
            sys.exit(1)
        df = df[codes == school]
        years = sorted(y for y in df[YEAR_COL].dropna().unique())
        if year is None:
            if not years:
                _err("None of this school's responses has a recorded date.")
                sys.exit(1)
            print(f"\n  School years with responses from {school}:")
            year = _pick("Which school year?", years, default=str(len(years)))
    elif year is None:
        year = _pick("Which school year?", ["All years"] + years)
        year = None if year == "All years" else year
    if year is not None:
        df = df[df[YEAR_COL] == year]

    if PRIVACY and len(df) < MIN_CELL:
        _err(
            f"Only {len(df)} response(s) match. A report must rest on at least {MIN_CELL}\n"
            "     students (IRB small-cell rule), so no report can be made for this selection."
        )
        sys.exit(1)
    what = f"school {school}" if school else "all schools"
    _ok(f"{len(df)} responses: {what}, {year + ' school year' if year else 'all years'}")
    # The school code never reaches a chart; only the cover page names the school.
    df = df.drop(columns=[c for c in (SCHOOL_COL, YEAR_COL) if c in df.columns]).copy()
    return df, school, year


def _step2_split_column(df: "pd.DataFrame") -> tuple[str, str, str]:
    """
    STEP 3 — Choose which column splits the data into two groups,
    then name each group. Returns (split_col, yes_label, no_label).
    When a group would hold fewer than MIN_CELL students, the split is dropped
    and every chart shows all students together.
    """
    _blank()
    print("  STEP 3 of 4  —  Choose your comparison groups")
    _hr()
    print(
        "\n"
        "  The charts compare two groups of respondents side by side.\n"
        "  You choose which question defines those groups — it must be a\n"
        "  Yes/No question (i.e. a column where every answer is either Yes or No).\n"
        "\n"
        "  For the standard Math Badging analysis, choose B_1 (option 1 below).\n"
        "  You can also split on any other Yes/No column, for example B_5\n"
        "  (badge awareness) to compare students who knew about badges vs. those\n"
        "  who did not."
    )
    _blank()

    # Detect binary Yes/No columns
    binary_cols = [
        col for col in df.columns
        if set(df[col].dropna().unique()) <= {"Yes", "No"}
        and "Yes" in df[col].values
        and "No"  in df[col].values
    ]

    if binary_cols:
        print("  Yes/No columns detected in this dataset:")
        _blank()
        for i, col in enumerate(binary_cols, 1):
            yes_n = int((df[col] == "Yes").sum())
            no_n  = int((df[col] == "No").sum())
            desc  = COLUMN_DESCRIPTIONS.get(col, "")
            desc_str = f"  ←  {desc}" if desc else ""
            print(f"    {i})  {col:<12}  Yes: {yes_n:>3},  No: {no_n:>3}{desc_str}")
        _blank()
        print("    0)  I want to enter a column name manually")
        _hr()

        default_idx = "1"
        while True:
            choice = _ask(
                "Which column defines your two groups?  (Enter a number)",
                default=default_idx,
            )
            if choice.isdigit():
                n = int(choice)
                if 1 <= n <= len(binary_cols):
                    split_col = binary_cols[n - 1]
                    break
                elif n == 0:
                    split_col = _ask_column_manually(df)
                    break
                else:
                    _warn(f"Please enter a number between 0 and {len(binary_cols)}.")
            else:
                # User typed a column name directly
                if choice in df.columns:
                    split_col = choice
                    break
                _warn(
                    f"'{choice}' is not a recognised column name.\n"
                    "     Enter a number from the list, or 0 to type a column name."
                )
    else:
        _warn(
            "No Yes/No columns were automatically detected.\n"
            "     This can happen if the split column uses different values\n"
            "     (e.g. 'yes'/'no' in lowercase, or '1'/'0').\n"
            "     You can still enter the column name manually below."
        )
        _blank()
        split_col = _ask_column_manually(df)

    # Confirm the split counts
    yes_n = int((df[split_col] == "Yes").sum())
    no_n  = int((df[split_col] == "No").sum())
    other_n = len(df) - yes_n - no_n
    _blank()
    print(f"  Selected column:  {split_col}")
    print(f"    'Yes' responses:  {yes_n}")
    print(f"    'No'  responses:  {no_n}")
    if other_n > 0:
        _warn(
            f"{other_n} row(s) have a value other than Yes/No in this column\n"
            "     and will be excluded from both groups."
        )
    _blank()

    if min(yes_n, no_n) == 0 or (PRIVACY and min(yes_n, no_n) < MIN_CELL):
        _warn(
            f"One group has only {min(yes_n, no_n)} student(s), fewer than {MIN_CELL}, so the two\n"
            "     groups cannot be shown separately. Every chart will show all students together."
        )
        df[ALL_COL] = "Yes"
        return ALL_COL, "All students", ""

    # Name the groups
    _hr()
    print(
        "\n"
        "  Now give each group a short label that will appear on the charts.\n"
        "  Press Enter to accept the suggested label, or type your own.\n"
        "  Keep labels short — they sit on the right-hand axis of each chart.\n"
        "  Examples:  'Badging'  'Non-Badging'  'Badge Aware'  '11th Grade'\n"
    )
    yes_label = _ask(f'Label for the "Yes" group  ({yes_n} students)', default="Math Badging")
    no_label  = _ask(f'Label for the "No"  group  ({no_n} students)',  default="Non-Badging")

    return split_col, yes_label, no_label


def _ask_column_manually(df: "pd.DataFrame") -> str:
    """Prompt the user to type a column name, with retry on bad input."""
    print("\n  Available columns in this dataset:")
    cols = [c for c in df.columns
            if c not in ("StartDate","EndDate","Status","IPAddress","Progress",
                         "Duration (in seconds)","Finished","RecordedDate",
                         "ResponseId","RecipientLastName","RecipientFirstName",
                         "RecipientEmail","ExternalReference",
                         "LocationLatitude","LocationLongitude",
                         "DistributionChannel","UserLanguage")]
    for col in cols:
        print(f"      {col}")
    _blank()
    while True:
        name = _ask("Column name")
        if name in df.columns:
            return name
        _warn(f"'{name}' not found. Check the spelling (column names are case-sensitive).")


def _step3_output_settings() -> tuple[str, str, int]:
    """
    STEP 4 — Title suffix, output folder, resolution.
    Returns (title_suffix, out_dir, dpi).
    """
    _blank()
    print("  STEP 4 of 4  —  Output settings")
    _hr()
    print(
        "\n"
        "  The tool will generate a single PDF report containing a cover page and all 12 charts.\n"
        "  All charts are generated automatically and assembled into one file.\n"
    )

    # Title suffix
    print(
        "  TITLE SUFFIX\n"
        "  A short label added to the top of every chart — useful for keeping\n"
        "  track of which run produced which charts.\n"
        "  Examples:  'Spring 2026'  |  '11th Grade Only'  |  'Region 1'\n"
        "  Leave blank to omit a suffix.\n"
    )
    title = _ask("Title suffix", default="")

    _blank()

    # Output folder
    print(
        "  OUTPUT FOLDER\n"
        "  The PDF will be saved here. The folder will be created\n"
        "  automatically if it does not already exist. Using a descriptive name\n"
        "  helps you keep runs organised.\n"
        "  Examples:  'output'  |  'charts_spring2026'  |  'region1_11th'\n"
    )
    out_dir = _ask("Output folder name", default="output")

    _blank()

    # DPI
    print(
        "  IMAGE RESOLUTION (DPI)\n"
        "    150 DPI  —  good for on-screen viewing and presentations\n"
        "    300 DPI  —  recommended for printed reports and publications\n"
        "    96  DPI  —  smaller file size, fine for email or drafts\n"
    )
    while True:
        dpi_str = _ask("Resolution in DPI", default="150")
        if dpi_str.isdigit() and 72 <= int(dpi_str) <= 600:
            dpi = int(dpi_str)
            break
        _warn("Please enter a whole number between 72 and 600  (150 is a good default).")

    return title, out_dir, dpi


def run_wizard(preselected_csv: str | None, school: str | None = None,
               year: str | None = None) -> dict:
    """
    Full interactive wizard. Returns a config dict ready for main().
    """
    # Header
    _blank()
    _hr(double=True)
    print("  Idaho High School Math Survey  —  Chart Generator")
    _hr(double=True)
    _blank()
    print("  This tool walks you through 4 short steps and then")
    print("  automatically generates all 12 analysis charts as PNG files.")
    _blank()
    print("  At each prompt:")
    print("    • Press Enter to accept the  [default value]  shown in brackets.")
    print("    • Type your answer and press Enter to choose something different.")
    print("    • Type  q  and press Enter (or press Ctrl-C) at any time to quit.")
    _blank()

    # Pre-flight warnings
    warnings = _preflight_check()
    if warnings:
        _hr()
        print("  ⚠  BEFORE YOU CONTINUE — please read:")
        _blank()
        for w in warnings:
            print(f"  {w}")
        _blank()
        cont = _ask("Continue anyway?  [Y/n]", default="Y").lower()
        if cont not in ("y", "yes", ""):
            print("  Cancelled — no files were written.")
            sys.exit(0)

    _hr()

    # Step 1 — file
    csv_path, df = _step1_select_file(preselected_csv)

    # Step 2 — which school(s) and school year
    _hr()
    df, school, year = _step_select_data(df, school, year)

    # Step 3 — split column and group labels
    _hr()
    split_col, yes_label, no_label = _step2_split_column(df)

    # Step 4 — output
    _hr()
    title_suffix, out_dir, dpi = _step3_output_settings()

    # Confirmation summary
    yes_n = int((df[split_col] == "Yes").sum())
    no_n  = int((df[split_col] == "No").sum())
    est_time = max(1, round(12 * (dpi / 150) * 0.4))

    _blank()
    _hr(double=True)
    print("  READY TO GENERATE — here is what will happen:")
    _hr()
    print(f"  Data file:       {os.path.basename(csv_path)}")
    print(f"  Responses:       {len(df)} respondents selected")
    print(f"  School:          {school or 'all schools'}")
    print(f"  School year:     {year + '  (' + year_span(year) + ')' if year else 'all years'}")
    print(f"  Privacy:         {'groups of fewer than ' + str(MIN_CELL) + ' students are combined or hidden' if PRIVACY else 'OFF (--internal): research team only, never share'}")
    if no_label:
        print(f"  Comparison:      '{yes_label}'  (n={yes_n})  vs  '{no_label}'  (n={no_n})")
    else:
        print(f"  Comparison:      none — all students together (n={yes_n})")
    print(f"  Split column:    {split_col}  —  {COLUMN_DESCRIPTIONS.get(split_col, 'user-selected column')}")
    print(f"  Title suffix:    {title_suffix or '(none)'}")
    print(f"  Output folder:   {os.path.abspath(out_dir)}/")
    print(f"  Resolution:      {dpi} DPI")
    print(f"  Output:          1 PDF file  (cover page + 12 charts)")
    print(f"  Est. run time:   ~{est_time} second(s)")
    _hr(double=True)
    _blank()

    go = _ask("Generate all 12 charts now?  [Y/n]", default="Y").lower()
    if go not in ("y", "yes", ""):
        print("\n  Cancelled — no files were written.")
        sys.exit(0)

    return {
        "df":           df,
        "split_col":    split_col,
        "yes_label":    yes_label,
        "no_label":     no_label,
        "title_suffix": title_suffix,
        "out_dir":      out_dir,
        "dpi":          dpi,
        "school":       school,
        "year":         year,
    }


# ---------------------------------------------------------------------------
# Data loading & preparation
# ---------------------------------------------------------------------------

def load_qualtrics(path: str) -> pd.DataFrame:
    """
    Load a Qualtrics CSV (3-row header: column codes / question text / import IDs).
    Keeps the School column only for the data-selection step (which drops it
    before any chart is drawn) and adds the school year of each response.
    """
    df = pd.read_csv(path, skiprows=[1, 2], low_memory=False)
    for col in df.select_dtypes(include=["object", "string"]).columns:
        df[col] = df[col].str.strip()
    when = pd.to_datetime(df[DATE_COL], errors="coerce") if DATE_COL in df.columns else pd.Series(pd.NaT, index=df.index)
    df[YEAR_COL] = when.map(school_year)
    return df


def normalise_likert(series: pd.Series) -> pd.Series:
    return series.map(
        lambda v: LIKERT_NORM.get(str(v).lower().strip(), np.nan) if pd.notna(v) else np.nan
    )


def split_groups(df: pd.DataFrame, col: str):
    return df[df[col] == "Yes"].copy(), df[df[col] == "No"].copy()


def pct_counts(series: pd.Series):
    total = series.dropna().shape[0]
    result = {}
    for cat in LIKERT_ORDER:
        n = (series == cat).sum()
        result[cat] = (int(n), round(100 * n / total, 1) if total else 0.0)
    return result, total


def explode_multiselect(series: pd.Series) -> pd.Series:
    return series.dropna().str.split(",").explode().str.strip()


# ---------------------------------------------------------------------------
# Chart helpers
# ---------------------------------------------------------------------------

FONT_TITLE    = {"fontsize": 13, "fontweight": "bold", "color": "#1a1a2e"}
FONT_SUBTITLE = {"fontsize": 9,  "color": "#555577",   "style": "italic"}
GROUP_COLORS  = {"yes": "#1a5fa8", "no": "#888899"}


def _n(n: int) -> str:
    """A group size as it may be printed: small groups only as '<6'."""
    return f"<{MIN_CELL}" if PRIVACY and 0 < n < MIN_CELL else str(n)


def _add_footer(fig, yes_n, no_n, yes_label, no_label, title_suffix=""):
    parts = [f"n={yes_label}: {_n(yes_n)}"]
    if no_label and no_n:
        parts.append(f"n={no_label}: {_n(no_n)}")
    if title_suffix:
        parts.append(title_suffix)
    if PRIVACY:
        parts.append(f"groups of fewer than {MIN_CELL} students are combined or not shown")
    fig.text(
        0.5, 0.01, "   |   ".join(parts),
        ha="center", fontsize=7.5, color="#777777",
        transform=fig.transFigure,
    )


def _draw_likert_row(ax, y, series, bar_thick, label_min):
    """
    Draw one diverging Likert bar at height y, applying the small-cell rule.
    Returns 'full', 'collapsed' (two hatched sides), 'suppressed' or 'empty'.
    """
    counts, total = pct_counts(normalise_likert(series))
    if total == 0:
        return "empty"
    how, shown = protect_likert({c: counts[c][0] for c in LIKERT_ORDER})
    if how == "suppressed":
        ax.text(0, y, f"not shown: fewer than {MIN_CELL} students on one side",
                ha="center", va="center", fontsize=7, color="#999999",
                style="italic", zorder=4)
        return how
    if how == "collapsed":
        for cat, sign in (("Disagree", -1), ("Agree", 1)):
            pct = 100 * shown[cat] / total
            if pct > 0:
                ax.barh(y, sign * pct, left=0, height=bar_thick,
                        color=LIKERT_COLORS[cat], hatch="///",
                        edgecolor="white", linewidth=0.4, zorder=3)
                if pct >= label_min:
                    ax.text(sign * pct / 2, y, f"{pct:.0f}%",
                            ha="center", va="center", color="white",
                            fontsize=6.5, fontweight="bold", zorder=4)
        return how
    neg_cats, pos_cats = LIKERT_ORDER[:3], LIKERT_ORDER[3:]
    left = 0.0
    for cat in reversed(neg_cats):
        pct = counts[cat][1]
        if pct > 0:
            ax.barh(y, -pct, left=left, height=bar_thick,
                    color=LIKERT_COLORS[cat],
                    edgecolor="white", linewidth=0.4, zorder=3)
            if pct >= label_min:
                ax.text(left - pct / 2, y, f"{pct:.0f}%",
                        ha="center", va="center",
                        color="white", fontsize=6.5, fontweight="bold", zorder=4)
            left -= pct
    left = 0.0
    for cat in pos_cats:
        pct = counts[cat][1]
        if pct > 0:
            ax.barh(y, pct, left=left, height=bar_thick,
                    color=LIKERT_COLORS[cat],
                    edgecolor="white", linewidth=0.4, zorder=3)
            if pct >= label_min:
                ax.text(left + pct / 2, y, f"{pct:.0f}%",
                        ha="center", va="center",
                        color="white", fontsize=6.5, fontweight="bold", zorder=4)
            left += pct
    return how


def _likert_legend(ax, hows, n_items, wide_at):
    patches = [mpatches.Patch(facecolor=LIKERT_COLORS[c], label=c) for c in LIKERT_ORDER]
    if "collapsed" in hows:
        patches.append(mpatches.Patch(facecolor="#bbbbbb", hatch="///", edgecolor="white",
                                      label="Combined (privacy)"))
    ax.legend(handles=patches, loc="lower center",
              bbox_to_anchor=(0.5, -0.18 if n_items <= wide_at else -0.14),
              ncol=len(patches), fontsize=7.5, frameon=False, handlelength=1.2)


def save_to_pdf(fig, pdf):
    """Save a figure as the next page in an open PdfPages object."""
    if not PRIVACY:
        fig.text(0.5, 0.995, "INTERNAL — research team only  ·  small groups NOT hidden  ·  do not share",
                 ha="center", va="top", fontsize=9, color="#c0392b", fontweight="bold")
    pdf.savefig(fig, bbox_inches="tight", facecolor="white")
    print("  saved")    # completes the "• Chart name … saved" line
    plt.close(fig)


def make_cover_page(yes_label, no_label, split_col, title_suffix,
                    total_n, yes_n, no_n, dpi=150, school=None, year=None):
    """Cover / table-of-contents page for the PDF report."""
    import datetime
    fig = plt.figure(figsize=(13, 8.5), dpi=dpi)
    fig.patch.set_facecolor("white")

    # Accent bar
    bar_ax = fig.add_axes([0, 0.93, 1, 0.07])
    bar_ax.set_facecolor("#1a1a2e")
    bar_ax.set_axis_off()

    ax = fig.add_axes([0.08, 0.08, 0.84, 0.82])
    ax.set_axis_off()

    title    = "Idaho High School Mathematics Survey"
    subtitle = "Analysis Report" + (f"  —  {title_suffix}" if title_suffix else "")

    ax.text(0.5, 0.95, title,
            ha="center", va="top", fontsize=22, fontweight="bold",
            color="#1a1a2e", transform=ax.transAxes)
    ax.text(0.5, 0.86, subtitle,
            ha="center", va="top", fontsize=14, color="#555577",
            style="italic", transform=ax.transAxes)

    ax.plot([0, 1], [0.80, 0.80], color="#cccccc", linewidth=1, transform=ax.transAxes)

    if not PRIVACY:
        notice, color = ("INTERNAL — research team only. Small groups are NOT hidden. "
                         "Do not share outside the research team."), "#c0392b"
    elif school:
        notice, color = (f"For this school's designated primary contact only. Holds only this school's "
                         f"responses for the {year} school year, aggregated: no figure rests on fewer "
                         f"than {MIN_CELL} students."), "#1a5fa8"
    else:
        notice, color = (f"Aggregated results: no figure rests on fewer than {MIN_CELL} students; "
                         "no school is identified."), "#1a5fa8"
    ax.text(0.5, 0.775, notice, ha="center", va="top", fontsize=9.5, color=color,
            fontweight="bold", wrap=True, transform=ax.transAxes)

    summary_lines = [
        f"School:         {school if school else 'All participating schools'}",
        f"School year:    {year + '   (' + year_span(year) + ')' if year else 'All years'}",
        f"Total respondents:    {total_n}",
        "",
    ]
    if no_label:
        summary_lines += [
            f'Group A  ·  "{yes_label}"    n = {yes_n}',
            f'Group B  ·  "{no_label}"    n = {no_n}',
            f"Split column:   {split_col}   —   {COLUMN_DESCRIPTIONS.get(split_col, 'user-selected column')}",
        ]
    else:
        summary_lines += [f"All students shown together (a comparison group had fewer than {MIN_CELL} students)."]
    summary_lines.append(f"Generated:      {datetime.datetime.now().strftime('%B %d, %Y  %H:%M')}")
    for i, line in enumerate(summary_lines):
        ax.text(0.12, 0.72 - i * 0.048, line,
                ha="left", va="top", fontsize=11, color="#333333",
                transform=ax.transAxes)

    ax.plot([0, 1], [0.30, 0.30], color="#cccccc", linewidth=1, transform=ax.transAxes)

    ax.text(0.12, 0.27, "Contents", ha="left", va="top", fontsize=11,
            fontweight="bold", color="#1a1a2e", transform=ax.transAxes)
    toc = [
        "1–3    Likert Scale Constructs",
        "         1.  Math Utility & Identity",
        "         2.  Math Engagement & Interest",
        "         3.  Math Competence Perception",
        "4–8    Single-Choice Questions",
        "         4.  Current Grade Level          5.  Current Math Class",
        "         6.  Next Planned Course          7.  Badging Class Progress",
        "         8.  Badge Awareness",
        "9–12   Multi-Choice Questions",
        "         9.  Post-Graduation Plans       10.  What Makes a Favourite Math Class",
        "        11.  Sources of Math Difficulty  12.  Ideal Badge Uses (badging only)",
        "13–17   Grade-Level Breakdown  (confound analysis)",
        "        13.  Grade composition by group",
        "        14.  Mean construct scores by grade",
        "        15.  Math Utility & Identity by grade",
        "        16.  Math Engagement & Interest by grade",
        "        17.  Math Competence Perception by grade",
    ]
    for i, line in enumerate(toc):
        ax.text(0.12, 0.21 - i * 0.048, line,
                ha="left", va="top", fontsize=9.5, color="#444444",
                transform=ax.transAxes)

    fig.text(0.5, 0.02,
             "Idaho Regional Mathematics Center  ·  Lewis-Clark State College  ·  Regions 1 & 2",
             ha="center", fontsize=8, color="#aaaaaa")
    return fig


# ---------------------------------------------------------------------------
# Chart renderers
# ---------------------------------------------------------------------------

def plot_diverging_construct(yes_df, no_df, construct, yes_label, no_label,
                              title_suffix="", dpi=150):
    items   = construct["items"]
    n_items = len(items)
    groups  = [(yes_label, yes_df)] + ([(no_label, no_df)] if no_label else [])
    n_rows  = n_items * len(groups)
    fig_h   = max(3.5, 0.55 * n_rows + 2.0)
    fig, ax = plt.subplots(figsize=(13, fig_h), dpi=dpi)
    fig.patch.set_facecolor("white")
    ax.set_facecolor("white")

    item_gap  = 0.35
    row_h     = 1.0
    bar_thick = 0.75

    y_ticks_label, y_ticks_group, y_group_labels = [], [], []
    hows = set()

    for i, (col, short_label) in enumerate(items):
        base = i * (len(groups) * row_h + item_gap)
        ys   = [base + (len(groups) - 1 - k) * row_h for k in range(len(groups))]
        y_ticks_label.append(base + (len(groups) - 1) * row_h / 2)
        y_ticks_group  += ys
        y_group_labels += [label for label, _ in groups]

        if i % 2 == 0:
            ax.barh(ys, [200] * len(ys), left=-100,
                    height=bar_thick + 0.05, color="#f0f2f8", zorder=0, alpha=0.5)

        for y, (_, sub_df) in zip(ys, groups):
            hows.add(_draw_likert_row(ax, y, sub_df[col], bar_thick, label_min=5))

    ax.axvline(0, color="#444455", linewidth=1.0, zorder=5)
    ax.set_xlim(-75, 75)
    ax.xaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"{abs(v):.0f}%"))
    ax.tick_params(axis="x", labelsize=8, colors="#555555")
    ax.set_xlabel("← Disagree                Agree →", fontsize=8.5,
                  color="#444444", labelpad=6)
    ax.set_yticks(y_ticks_label)
    ax.set_yticklabels(
        ["\n".join(textwrap.wrap(s, 34)) for _, s in items],
        fontsize=8.5, color="#1a1a2e")
    ax.yaxis.set_tick_params(length=0)

    ax2 = ax.twinx()
    ax2.set_ylim(ax.get_ylim())
    ax2.set_yticks(y_ticks_group)
    ax2.set_yticklabels(y_group_labels, fontsize=7.5, color="#555577")
    ax2.yaxis.set_tick_params(length=0)
    ax2.set_ylabel("")

    for spine in ["top", "right", "left"]:
        ax.spines[spine].set_visible(False)
    ax.spines["bottom"].set_color("#cccccc")
    for spine in ["top", "left", "bottom"]:
        ax2.spines[spine].set_visible(False)
    ax2.spines["right"].set_color("#cccccc")

    _likert_legend(ax, hows, n_items, wide_at=5)

    title_text = construct["title"] + (f" — {title_suffix}" if title_suffix else "")
    fig.suptitle(title_text, **FONT_TITLE, y=1.01)
    ax.set_title(construct["subtitle"], **FONT_SUBTITLE, pad=4)
    _add_footer(fig, len(yes_df), len(no_df), yes_label, no_label, title_suffix)
    fig.tight_layout(rect=[0, 0.04, 1, 1])
    return fig


def plot_single_select(yes_df, no_df, q_def, yes_label, no_label,
                        title_suffix="", dpi=150):
    col          = q_def["key"]
    order        = q_def.get("order", [])
    badging_only = q_def.get("badging_only", False)

    one_group    = badging_only or not no_label

    def freq(sub_df):
        vc = sub_df[col].value_counts()
        counts = {cat: int(vc.get(cat, 0)) for cat in order}
        counts.update({cat: int(vc[cat]) for cat in vc.index if cat not in counts})
        total = sum(counts.values())
        counts = protect_counts(counts)        # no category of 1-5 students
        return ({cat: (n, round(100 * n / total, 1) if total else 0.0)
                 for cat, n in counts.items()}, total)

    yes_freq, yes_n = freq(yes_df)
    no_freq,  no_n  = freq(no_df) if not one_group else ({}, 0)
    all_cats = list(dict.fromkeys(
        order + [c for c in list(yes_freq) + list(no_freq)
                 if c not in order and c != COMBINED_LABEL] + [COMBINED_LABEL]))
    all_cats = [c for c in all_cats
                if yes_freq.get(c, (0,))[0] + no_freq.get(c, (0,))[0] > 0]

    fig_h = max(3.0, 0.5 * len(all_cats) + 2.0)
    fig, ax = plt.subplots(figsize=(10, fig_h), dpi=dpi)
    fig.patch.set_facecolor("white")
    ax.set_facecolor("white")

    bar_w  = 0.35
    y_base = np.arange(len(all_cats))
    groups = ([(yes_freq, GROUP_COLORS["yes"], yes_label, yes_n)]
              if one_group
              else [(yes_freq, GROUP_COLORS["yes"], yes_label, yes_n),
                    (no_freq,  GROUP_COLORS["no"],  no_label,  no_n)])
    if not all_cats:
        ax.text(0.5, 0.5, f"Not shown: fewer than {MIN_CELL} students answered.",
                ha="center", va="center", fontsize=10, color="#999999",
                style="italic", transform=ax.transAxes)

    for g_idx, (freq_d, color, label, total) in enumerate(groups):
        offset = (g_idx - (len(groups) - 1) / 2) * bar_w
        pcts   = [freq_d.get(c, (0, 0.0))[1] for c in all_cats]
        cnts   = [freq_d.get(c, (0, 0.0))[0] for c in all_cats]
        bars   = ax.barh(y_base + offset, pcts, height=bar_w, color=color,
                         alpha=0.88, edgecolor="white", linewidth=0.5,
                         label=label, zorder=3)
        for bar, pct, cnt in zip(bars, pcts, cnts):
            if pct > 0:
                ax.text(pct + 0.8, bar.get_y() + bar.get_height() / 2,
                        f"{pct:.0f}% (n={cnt})",
                        va="center", ha="left", fontsize=7.5, color="#333333")

    ax.set_yticks(y_base)
    ax.set_yticklabels(["\n".join(textwrap.wrap(c, 36)) for c in all_cats],
                       fontsize=8.5)
    ax.set_xlabel("Percentage of respondents", fontsize=8.5, color="#444444")
    ax.xaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"{v:.0f}%"))
    ax.set_xlim(0, 105)
    ax.tick_params(axis="x", labelsize=8, colors="#555555")
    ax.spines[["top", "right"]].set_visible(False)
    ax.spines[["bottom", "left"]].set_color("#cccccc")
    if not one_group:
        ax.legend(fontsize=8, frameon=False, loc="lower right")

    title_text = q_def["title"] + (f" — {title_suffix}" if title_suffix else "")
    fig.suptitle(title_text, **FONT_TITLE, y=1.01)
    ax.set_title(q_def["subtitle"], **FONT_SUBTITLE, pad=4)
    _add_footer(fig, yes_n, no_n if not one_group else 0, yes_label, no_label)
    fig.tight_layout(rect=[0, 0.04, 1, 1])
    return fig


def plot_multi_select(yes_df, no_df, q_def, yes_label, no_label,
                       title_suffix="", dpi=150):
    col          = q_def["key"]
    badging_only = q_def.get("badging_only", False)

    one_group    = badging_only or not no_label

    def freq(sub_df):
        total = sub_df[col].notna().sum()
        vc    = explode_multiselect(sub_df[col]).value_counts()
        if PRIVACY:                    # options chosen by 1-5 students are not shown
            vc = vc[vc >= MIN_CELL]
        return vc, int(total)

    yes_vc, yes_n = freq(yes_df)
    no_vc,  no_n  = freq(no_df) if not one_group else (pd.Series(dtype=int), 0)
    all_cats = list(dict.fromkeys(
        list(yes_vc.index) + [c for c in no_vc.index if c not in yes_vc.index]))

    fig_h = max(3.5, 0.52 * len(all_cats) + 2.2)
    fig, ax = plt.subplots(figsize=(11, fig_h), dpi=dpi)
    fig.patch.set_facecolor("white")
    ax.set_facecolor("white")

    bar_w  = 0.36
    y_base = np.arange(len(all_cats))
    groups = ([(yes_vc, yes_n, GROUP_COLORS["yes"], yes_label)]
              if one_group
              else [(yes_vc, yes_n, GROUP_COLORS["yes"], yes_label),
                    (no_vc,  no_n,  GROUP_COLORS["no"],  no_label)])
    if not all_cats:
        ax.text(0.5, 0.5, f"Not shown: no option was chosen by {MIN_CELL} or more students.",
                ha="center", va="center", fontsize=10, color="#999999",
                style="italic", transform=ax.transAxes)

    for g_idx, (vc, total, color, label) in enumerate(groups):
        offset = (g_idx - (len(groups) - 1) / 2) * bar_w
        pcts   = [round(100 * vc.get(c, 0) / total, 1) if total else 0 for c in all_cats]
        cnts   = [int(vc.get(c, 0)) for c in all_cats]
        bars   = ax.barh(y_base + offset, pcts, height=bar_w, color=color,
                         alpha=0.88, edgecolor="white", linewidth=0.5,
                         label=label, zorder=3)
        for bar, pct, cnt in zip(bars, pcts, cnts):
            if pct > 0:
                ax.text(pct + 0.8, bar.get_y() + bar.get_height() / 2,
                        f"{pct:.0f}% (n={cnt})",
                        va="center", ha="left", fontsize=7.5, color="#333333")

    ax.set_yticks(y_base)
    ax.set_yticklabels(["\n".join(textwrap.wrap(c, 40)) for c in all_cats],
                       fontsize=8.2)
    ax.set_xlabel("% of respondents who selected this option",
                  fontsize=8.5, color="#444444")
    ax.xaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"{v:.0f}%"))
    ax.set_xlim(0, 110)
    ax.tick_params(axis="x", labelsize=8, colors="#555555")
    ax.spines[["top", "right"]].set_visible(False)
    ax.spines[["bottom", "left"]].set_color("#cccccc")
    if not one_group:
        ax.legend(fontsize=8.5, frameon=False, loc="lower right")

    title_text = q_def["title"] + (f" — {title_suffix}" if title_suffix else "")
    fig.suptitle(title_text, **FONT_TITLE, y=1.01)
    ax.set_title(q_def["subtitle"], **FONT_SUBTITLE, pad=4)
    _add_footer(fig, yes_n, no_n if not one_group else 0, yes_label, no_label)
    fig.tight_layout(rect=[0, 0.04, 1, 1])
    return fig


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

# Grade-level breakdown charts
# ---------------------------------------------------------------------------

GRADE_ORDER = ["9th", "10th", "11th", "12th"]

LIKERT_NUMERIC = {
    "strongly disagree": 1,
    "disagree":          2,
    "somewhat disagree": 3,
    "somewhat agree":    4,
    "agree":             5,
    "strongly agree":    6,
}

CONSTRUCT_COLS = {
    "MUI": ["MUI_1_1", "MUI_1_2", "MUI_1_3", "MUI_1_4"],
    "MEI": ["MEI_1_1", "MEI_1_7", "MEI_1_8", "MEI_1_9"],
    "MCP": ["MCP_1_1", "MCP_1_12", "MCP_1_13", "MCP_1_14", "MCP_1_15",
            "MCP_2_1", "MCP_2_12", "MCP_2_13", "MCP_2_14"],
}

CONSTRUCT_LABELS = {
    "MUI": "Math Utility & Identity",
    "MEI": "Math Engagement & Interest",
    "MCP": "Math Competence Perception",
}

MIN_N_LABEL = 5   # cells below this get a small-n warning marker


def _numeric_scores(df):
    """Add numeric Likert columns and construct mean columns to a copy of df."""
    d = df.copy()
    for key, cols in CONSTRUCT_COLS.items():
        num_cols = []
        for col in cols:
            if col not in d.columns:
                continue
            nc = col + "_num"
            d[nc] = d[col].str.lower().str.strip().map(LIKERT_NUMERIC)
            num_cols.append(nc)
        if num_cols:
            d[key + "_mean"] = d[num_cols].mean(axis=1)
    return d


def plot_grade_composition(df, yes_label, no_label, split_col,
                            title_suffix="", dpi=150):
    """
    Stacked horizontal bar showing grade composition of each group.
    Makes the confounding variable visible at a glance.
    """
    grade_colors = {
        "9th":  "#4e79a7",
        "10th": "#f28e2b",
        "11th": "#59a14f",
        "12th": "#e15759",
    }

    groups      = [g for g in (yes_label, no_label) if g]
    group_dfs   = {
        yes_label: df[df[split_col] == "Yes"],
        no_label:  df[df[split_col] == "No"],
    }

    fig, axes = plt.subplots(1, len(groups), figsize=(13 if len(groups) > 1 else 7.5, 3.5),
                             dpi=dpi, squeeze=False)
    axes = axes[0]
    fig.patch.set_facecolor("white")

    for ax, grp_name in zip(axes, groups):
        sub    = group_dfs[grp_name]
        counts = protect_counts({g: int((sub["DE_Grade"] == g).sum()) for g in GRADE_ORDER})
        total  = sum(counts.values())
        ax.set_facecolor("white")

        left = 0.0
        for grade, n in counts.items():
            pct = round(100 * n / total, 1) if total else 0
            if pct == 0:
                continue
            name = "Combined" if grade == COMBINED_LABEL else grade
            bar = ax.barh(0, pct, left=left, height=0.5,
                          color=grade_colors.get(grade, "#aaaaaa"),
                          edgecolor="white", linewidth=0.8)
            if pct >= 8:
                ax.text(left + pct / 2, 0,
                        f"{name}\n{pct:.0f}%\n(n={n})",
                        ha="center", va="center",
                        fontsize=8.5, color="white", fontweight="bold")
            left += pct

        ax.set_xlim(0, 100)
        ax.set_ylim(-0.6, 0.6)
        ax.set_yticks([])
        ax.set_xlabel("Percentage of group", fontsize=9, color="#444444")
        ax.xaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"{v:.0f}%"))
        ax.tick_params(axis="x", labelsize=8, colors="#555555")
        ax.spines[["top", "left", "right"]].set_visible(False)
        ax.spines["bottom"].set_color("#cccccc")
        ax.set_title(f"{grp_name}  (n={_n(total)})",
                     fontsize=11, fontweight="bold", color="#1a1a2e", pad=8)

    # Legend
    patches = [mpatches.Patch(color=grade_colors[g], label=g)
               for g in GRADE_ORDER if g in grade_colors]
    fig.legend(handles=patches, loc="lower center", ncol=4,
               fontsize=9, frameon=False, bbox_to_anchor=(0.5, -0.08))

    title_text = "Grade-Level Composition by Group"
    if title_suffix:
        title_text += f"  —  {title_suffix}"
    fig.suptitle(title_text, fontsize=13, fontweight="bold",
                 color="#1a1a2e", y=1.04)
    fig.text(0.5, 0.96,
             "Shows whether the two groups differ in grade-level composition "
             "(a potential confounding variable)",
             ha="center", fontsize=9, color="#555577", style="italic")

    fig.tight_layout(rect=[0, 0.06, 1, 1])
    return fig


def plot_grade_construct_means(df, split_col, yes_label, no_label,
                                title_suffix="", dpi=150):
    """
    Dot plot: mean construct score (1–6) by grade, with separate markers
    for Yes and No groups. Includes small-n warning where n < MIN_N_LABEL.
    One panel per construct (MUI, MEI, MCP) stacked vertically.
    """
    d = _numeric_scores(df)
    grades = [g for g in GRADE_ORDER if g in d["DE_Grade"].values]

    n_constructs = len(CONSTRUCT_COLS)
    fig, axes = plt.subplots(n_constructs, 1,
                              figsize=(11, 3.2 * n_constructs), dpi=dpi,
                              sharex=True)
    fig.patch.set_facecolor("white")

    x_pos = {g: i for i, g in enumerate(grades)}

    for ax, (key, cols) in zip(axes, CONSTRUCT_COLS.items()):
        ax.set_facecolor("white")
        mean_col = key + "_mean"

        for grp_val, grp_label, color, marker in [
            ("Yes", yes_label, GROUP_COLORS["yes"], "o"),
            ("No",  no_label,  GROUP_COLORS["no"],  "s"),
        ]:
            sub = d[d[split_col] == grp_val]
            xs, ys, ns = [], [], []
            for grade in grades:
                g_sub = sub[sub["DE_Grade"] == grade][mean_col].dropna()
                n     = len(g_sub)
                if n == 0 or (PRIVACY and n < MIN_CELL):
                    continue
                xs.append(x_pos[grade])
                ys.append(g_sub.mean())
                ns.append(n)

            if not xs:
                continue

            ax.plot(xs, ys, color=color, linewidth=1.4,
                    linestyle="--", alpha=0.5, zorder=2)
            ax.scatter(xs, ys, color=color, marker=marker, s=80,
                       zorder=3, label=f"{grp_label}")

            for x, y, n in zip(xs, ys, ns):
                va   = "bottom" if grp_val == "Yes" else "top"
                off  = 0.06  if grp_val == "Yes" else -0.06
                warn = f"*" if n < MIN_N_LABEL else ""
                ax.text(x, y + off, f"{y:.2f}{warn}  n={n}",
                        ha="center", va=va, fontsize=7.5,
                        color=color)

        ax.set_ylim(1, 6.3)
        ax.set_yticks([1, 2, 3, 4, 5, 6])
        ax.set_yticklabels(
            ["1\nStr. Disagree", "2", "3", "4", "5", "6\nStr. Agree"],
            fontsize=7.5, color="#555555")
        ax.yaxis.grid(True, color="#eeeeee", linewidth=0.8, zorder=0)
        ax.set_axisbelow(True)
        ax.spines[["top", "right"]].set_visible(False)
        ax.spines[["bottom", "left"]].set_color("#cccccc")
        ax.set_ylabel(CONSTRUCT_LABELS[key], fontsize=9,
                      color="#1a1a2e", fontweight="bold")

    axes[-1].set_xticks(list(x_pos.values()))
    axes[-1].set_xticklabels(grades, fontsize=10, color="#333333")
    axes[-1].set_xlabel("Grade Level", fontsize=10, color="#444444")

    # Shared legend
    handles = [mpatches.Patch(color=GROUP_COLORS[k], label=lab)
               for k, lab in (("yes", yes_label), ("no", no_label)) if lab]
    axes[0].legend(handles=handles, fontsize=9, frameon=False,
                   loc="upper right")

    title_text = "Mean Construct Scores by Grade Level"
    if title_suffix:
        title_text += f"  —  {title_suffix}"

    # Reserve top margin so title and subtitle don't overlap
    fig.tight_layout(rect=[0, 0, 1, 0.93])
    fig.suptitle(title_text, fontsize=13, fontweight="bold",
                 color="#1a1a2e", y=0.98)
    fig.text(0.5, 0.945,
             "Scale 1–6 (Strongly Disagree → Strongly Agree)  ·  "
             + (f"grade groups of fewer than {MIN_CELL} students are not shown" if PRIVACY
                else f"* = small sample (n < {MIN_N_LABEL}), interpret with caution"),
             ha="center", fontsize=8.5, color="#555577", style="italic")
    return fig


def plot_grade_likert_construct(df, construct, grade_col="DE_Grade",
                                 title_suffix="", dpi=150):
    """
    Diverging stacked bar chart for ONE construct, with one row per grade
    (pooling all students regardless of badging group).
    Useful for seeing grade-level trends independently of the split.
    """
    grades  = [g for g in GRADE_ORDER if g in df[grade_col].dropna().values]
    n_grades = len(grades)
    items    = construct["items"]
    n_items  = len(items)

    fig_h = max(3.5, 0.6 * n_grades * n_items + 1.8)
    fig, ax = plt.subplots(figsize=(13, fig_h), dpi=dpi)
    fig.patch.set_facecolor("white")
    ax.set_facecolor("white")

    item_gap  = 0.4
    row_h     = 1.0
    bar_thick = 0.72
    y_ticks_label  = []
    y_ticks_grade  = []
    y_grade_labels = []
    hows           = set()

    for i, (col, short_label) in enumerate(items):
        base = i * (n_grades * row_h + item_gap)
        y_ticks_label.append(base + (n_grades * row_h) / 2)

        for j, grade in enumerate(grades):
            y = base + j * row_h
            y_ticks_grade.append(y)
            sub   = df[df[grade_col] == grade]
            n     = sub[col].dropna().shape[0]
            if PRIVACY and 0 < n < MIN_CELL:
                y_grade_labels.append(f"{grade}  (n<{MIN_CELL}, not shown)")
                continue
            y_grade_labels.append(f"{grade}  (n={n})")
            hows.add(_draw_likert_row(ax, y, sub[col], bar_thick, label_min=6))

            # Small-n marker (--internal only; otherwise small rows are hidden)
            if not PRIVACY and n < MIN_N_LABEL:
                ax.text(72, y, f"* n={n}", ha="left", va="center",
                        fontsize=7, color="#cc4444", style="italic")

        # Row stripe
        if i % 2 == 0:
            stripe_y = base - item_gap / 2
            ax.barh(
                [base + j * row_h for j in range(n_grades)],
                [200] * n_grades, left=-100,
                height=bar_thick + 0.05,
                color="#f0f2f8", zorder=0, alpha=0.4,
            )

    ax.axvline(0, color="#444455", linewidth=1.0, zorder=5)
    ax.set_xlim(-75, 75)
    ax.xaxis.set_major_formatter(
        mticker.FuncFormatter(lambda v, _: f"{abs(v):.0f}%"))
    ax.tick_params(axis="x", labelsize=8, colors="#555555")
    ax.set_xlabel("← Disagree                Agree →",
                  fontsize=8.5, color="#444444", labelpad=6)

    ax.set_yticks(y_ticks_label)
    ax.set_yticklabels(
        ["\n".join(textwrap.wrap(s, 34)) for _, s in items],
        fontsize=8.5, color="#1a1a2e")
    ax.yaxis.set_tick_params(length=0)

    ax2 = ax.twinx()
    ax2.set_ylim(ax.get_ylim())
    ax2.set_yticks(y_ticks_grade)
    ax2.set_yticklabels(y_grade_labels, fontsize=7.5, color="#555577")
    ax2.yaxis.set_tick_params(length=0)
    ax2.set_ylabel("")

    for spine in ["top", "right", "left"]:
        ax.spines[spine].set_visible(False)
    ax.spines["bottom"].set_color("#cccccc")
    for spine in ["top", "left", "bottom"]:
        ax2.spines[spine].set_visible(False)
    ax2.spines["right"].set_color("#cccccc")

    _likert_legend(ax, hows, n_items, wide_at=4)

    title_text = construct["title"] + " — By Grade Level (All Students)"
    if title_suffix:
        title_text += f"  |  {title_suffix}"

    # right=0.82 leaves room for the grade labels on the twin axis;
    # top=0.91 gives the title + subtitle space without overlapping.
    fig.tight_layout(rect=[0, 0.05, 0.82, 0.91])
    fig.subplots_adjust(right=0.82, top=0.91)

    fig.suptitle(title_text, fontsize=13, fontweight="bold",
                 color="#1a1a2e", y=0.975)
    # Split subtitle across two short lines so it never overlaps title
    fig.text(0.5, 0.935,
             construct["subtitle"],
             ha="center", fontsize=8.5, color="#555577", style="italic")
    fig.text(0.5, 0.910,
             "Pooled across both groups  ·  "
             + (f"grades with fewer than {MIN_CELL} students are not shown" if PRIVACY
                else f"* = small sample (n < {MIN_N_LABEL}), interpret with caution"),
             ha="center", fontsize=8, color="#888888", style="italic")

    sizes   = df["DE_Grade"].value_counts()
    n_total = int(sum(n for g, n in sizes.items()
                      if g in grades and not (PRIVACY and n < MIN_CELL)))
    fig.text(0.5, 0.01, f"All students combined  |  n={n_total}",
             ha="center", fontsize=7.5, color="#777777")

    return fig



def main():
    from matplotlib.backends.backend_pdf import PdfPages

    import argparse
    global PRIVACY
    ap = argparse.ArgumentParser(description="Idaho HS Math Survey chart generator (guided).")
    ap.add_argument("csv", nargs="?", help="Qualtrics CSV export (asked for if left out)")
    ap.add_argument("--school", help="one school's code (the ?School= value); needs one --year")
    ap.add_argument("--year", help="school year, e.g. 2026-27 (1 July - 30 June, by recorded date)")
    ap.add_argument("--internal", action="store_true",
                    help="research team only: do not hide small groups (all-schools reports only)")
    args = ap.parse_args()
    year = args.year
    if year:
        m = re.fullmatch(r"(\d{4})-(\d{2}|\d{4})", year.strip())
        if not m:
            _err("--year looks like 2026-27 (the school year starting 1 July 2026).")
            sys.exit(1)
        year = f"{m.group(1)}-{m.group(2)[-2:]}"
    if args.internal:
        if args.school:
            _err("--internal is for research-team analysis only and cannot make a school report.")
            sys.exit(1)
        PRIVACY = False
    cfg = run_wizard(args.csv, args.school, year)

    df            = cfg["df"]
    yes_df, no_df = split_groups(df, cfg["split_col"])
    kw = dict(
        yes_label    = cfg["yes_label"],
        no_label     = cfg["no_label"],
        title_suffix = cfg["title_suffix"],
        dpi          = cfg["dpi"],
    )
    out_dir  = cfg["out_dir"]
    skipped  = []
    n_saved  = 0

    # Build output file path — resolve relative to script folder, not terminal cwd
    if not os.path.isabs(out_dir):
        out_dir = os.path.join(SCRIPT_DIR, out_dir)
    os.makedirs(out_dir, exist_ok=True)
    safe_suffix = cfg["title_suffix"].replace(" ", "_").replace("/", "-") if cfg["title_suffix"] else ""
    name_parts  = ["survey", re.sub(r"[^A-Za-z0-9-]", "", cfg["school"] or "") or "all-schools",
                   cfg["year"] or "all-years"] + ([safe_suffix] if safe_suffix else [])                   + ([] if PRIVACY else ["INTERNAL"])
    pdf_name    = "_".join(name_parts) + ".pdf"
    pdf_path    = os.path.join(out_dir, pdf_name)

    _blank()
    _hr(double=True)
    print(f"  Generating PDF report …")
    print(f"  Output: {os.path.abspath(pdf_path)}")
    _hr()

    yes_n = int((df[cfg["split_col"]] == "Yes").sum())
    no_n  = int((df[cfg["split_col"]] == "No").sum())

    with PdfPages(pdf_path) as pdf:

        # Cover page
        print(f"    • Cover page …", end="", flush=True)
        cover = make_cover_page(
            yes_label    = cfg["yes_label"],
            no_label     = cfg["no_label"],
            split_col    = cfg["split_col"],
            title_suffix = cfg["title_suffix"],
            total_n      = len(df),
            yes_n        = yes_n,
            no_n         = no_n,
            dpi          = cfg["dpi"],
            school       = cfg["school"],
            year         = cfg["year"],
        )
        save_to_pdf(cover, pdf)

        # Likert constructs
        _blank()
        print("  Likert scale constructs  (diverging bar charts):")
        for construct in CONSTRUCTS:
            print(f"    • {construct['title']} …", end="", flush=True)
            fig = plot_diverging_construct(yes_df, no_df, construct, **kw)
            save_to_pdf(fig, pdf)
            n_saved += 1

        # Single-select
        _blank()
        print("  Single-choice questions  (grouped bar charts):")
        for q_def in SINGLE_SELECT:
            if q_def["key"] not in df.columns:
                print(f"    – {q_def['title']} … skipped (column {q_def['key']} not in data)")
                skipped.append(q_def["key"])
                continue
            print(f"    • {q_def['title']} …", end="", flush=True)
            fig = plot_single_select(yes_df, no_df, q_def, **kw)
            save_to_pdf(fig, pdf)
            n_saved += 1

        # Multi-select
        _blank()
        print("  Multi-choice questions  (frequency bar charts):")
        for q_def in MULTI_SELECT_CHARTS:
            if q_def["key"] not in df.columns:
                print(f"    – {q_def['title']} … skipped (column {q_def['key']} not in data)")
                skipped.append(q_def["key"])
                continue
            print(f"    • {q_def['title']} …", end="", flush=True)
            fig = plot_multi_select(yes_df, no_df, q_def, **kw)
            save_to_pdf(fig, pdf)
            n_saved += 1

        # Grade-level breakdown section
        _blank()
        print("  Grade-level breakdown  (confound analysis):")

        print(f"    • Grade composition by group …", end="", flush=True)
        fig = plot_grade_composition(df, cfg["yes_label"], cfg["no_label"],
                                     cfg["split_col"], cfg["title_suffix"], cfg["dpi"])
        save_to_pdf(fig, pdf)
        n_saved += 1

        print(f"    • Mean construct scores by grade …", end="", flush=True)
        fig = plot_grade_construct_means(df, cfg["split_col"],
                                         cfg["yes_label"], cfg["no_label"],
                                         cfg["title_suffix"], cfg["dpi"])
        save_to_pdf(fig, pdf)
        n_saved += 1

        for construct in CONSTRUCTS:
            print(f"    • {construct['title']} by grade …", end="", flush=True)
            fig = plot_grade_likert_construct(df, construct,
                                              title_suffix=cfg["title_suffix"],
                                              dpi=cfg["dpi"])
            save_to_pdf(fig, pdf)
            n_saved += 1

        # PDF metadata
        info = pdf.infodict()
        info["Title"]   = "Idaho High School Mathematics Survey — Analysis Report"
        info["Author"]  = "Idaho Regional Mathematics Center, LCSC"
        info["Subject"] = " · ".join(x for x in (cfg["school"], cfg["year"], cfg["title_suffix"]) if x)                           or "Survey Analysis"

    abs_path = os.path.abspath(pdf_path)
    _blank()
    _hr(double=True)
    print(f"  ✓  All done!  {n_saved} charts + cover page written to one PDF.")
    _hr()
    print(f"  File:  {abs_path}")
    if skipped:
        _blank()
        print(f"  Skipped ({len(skipped)} columns not found in this dataset):")
        for s in skipped:
            print(f"    {s}")
    _hr(double=True)
    _blank()
    print("  To open the PDF:")
    print("    Windows:  press  Win + E  and navigate to the location above,")
    print("              or copy the path and paste it into the Explorer address bar.")
    print("    Mac:      open Finder, press  Cmd + Shift + G,  paste the path above.")
    _blank()


if __name__ == "__main__":
    main()

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
