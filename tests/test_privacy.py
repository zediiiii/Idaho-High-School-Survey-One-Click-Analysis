"""
Privacy and data-selection checks, run on SYNTHETIC data only (no real responses):

    python tests/test_privacy.py

Builds a fake Qualtrics export in a temp folder, then checks that
  * the small-cell rules never show a group of 1-5 students,
  * a school report holds only that school's responses for one school year,
  * a selection under 6 students, or --internal with --school, is refused,
  * qualtrics_pull strips location/IP columns.
"""
import csv
import os
import random
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import survey_viz as sv            # noqa: E402
import qualtrics_pull as qp        # noqa: E402

LIKERT = sv.LIKERT_ORDER
LIKERT_COLS = [c for con in sv.CONSTRUCTS for c, _ in con["items"]]


def fake_rows(school, n, date, badging_share=0.5, seed=0):
    rnd = random.Random(seed)
    rows = []
    for k in range(n):
        badging = rnd.random() < badging_share
        r = {"StartDate": date, "EndDate": date, "Status": "IP Address", "IPAddress": "",
             "Progress": "100", "Finished": "True", "RecordedDate": date,
             "ResponseId": f"R_{school}{k}", "LocationLatitude": "", "LocationLongitude": "",
             "School": school, "DE_Grade": rnd.choice(["9th", "10th", "11th", "11th", "12th"]),
             "DE_Class": rnd.choice(sv.SINGLE_SELECT[1]["order"]),
             "B_1": "Yes" if badging else "No",
             "MUI_2": ",".join(rnd.sample(["Go to college", "Work", "Military", "Gap year"], 2)),
             "MEI_2": "Good teacher", "MCP_3": "Gaps in knowledge"}
        for c in LIKERT_COLS:
            r[c] = rnd.choice(LIKERT[2:]) if rnd.random() < 0.9 else rnd.choice(LIKERT)
        if badging:
            r.update({"B_2": "In the middle of my badging class", "B_5": "Yes",
                      "B_6": "College applications", "B_7": "Pre-Calculus"})
        rows.append(r)
    return rows


def write_export(path, rows):
    cols = list(dict.fromkeys(c for r in rows for c in r))
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(cols)
        w.writerow(cols)                                  # question-text row
        w.writerow(['{"ImportId":"%s"}' % c for c in cols])
        for r in rows:
            w.writerow([r.get(c, "") for c in cols])


def run(args, answers=""):
    p = subprocess.run([sys.executable, os.path.join(ROOT, "survey_viz.py")] + args,
                       input=answers, capture_output=True, text=True, encoding="utf-8",
                       env=dict(os.environ, PYTHONIOENCODING="utf-8"))
    return p.returncode, p.stdout + p.stderr


def pdf_text(path):
    from pypdf import PdfReader
    return "\n".join(pg.extract_text() or "" for pg in PdfReader(path).pages)


def check(cond, msg):
    print(("  ok    " if cond else "  FAIL  ") + msg)
    if not cond:
        check.failed += 1


check.failed = 0


def unit_tests():
    print("unit:")
    check(sv.school_year(sv.pd.Timestamp("2026-07-01")) == "2026-27", "1 July starts a school year")
    check(sv.school_year(sv.pd.Timestamp("2027-06-30 23:59")) == "2026-27", "30 June ends it")
    out = sv.protect_counts({"a": 20, "b": 3, "c": 2, "d": 9})
    check(all(n == 0 or n >= 6 for n in out.values()), f"single-choice cells all 0 or 6+: {out}")
    check(sum(out.values()) == 34, "single-choice total kept")
    out = sv.protect_counts({"a": 20, "b": 3})
    check(all(n == 0 or n >= 6 for n in out.values()), f"lone small cell pooled with the next: {out}")
    check(sv.protect_counts({"a": 4}) == {}, "group under 6 shows nothing")
    how, _ = sv.protect_likert({c: 10 for c in LIKERT})
    check(how == "full", "Likert row with 6+ everywhere stays full")
    how, d = sv.protect_likert({"Strongly Disagree": 2, "Disagree": 5, "Agree": 20})
    check(how == "collapsed" and d == {"Disagree": 7, "Agree": 20}, f"Likert collapses to two sides: {d}")
    how, _ = sv.protect_likert({"Disagree": 3, "Agree": 20})
    check(how == "suppressed", "Likert side under 6 suppresses the row")
    rows, filled = qp.strip_identifying([["IPAddress", "School", "LocationLatitude", "Q"],
                                         ["", "", "", ""], ["", "", "", ""], ["1.2.3.4", "WJ26", "43.1", "x"]])
    check(rows[0] == ["School", "Q"] and filled == {"IPAddress": 1, "LocationLatitude": 1},
          "pull removes IP/location columns and reports filled ones")
    check(qp.school_year("2026-10-30 14:05:22") == "2026-27", "pull dates map to school years")


def end_to_end(tmp):
    print("end to end:")
    rows = (fake_rows("BIG", 60, "2026-10-20 10:00:00", seed=1)
            + fake_rows("BIG", 15, "2027-09-15 10:00:00", seed=2)          # next school year
            + fake_rows("SMALL", 9, "2026-11-02 09:00:00", badging_share=0.2, seed=3)
            + fake_rows("TINY", 4, "2026-11-03 09:00:00", seed=4))
    rows[0]["Status"] = "Survey Preview"
    csv_path = os.path.join(tmp, "export.csv")
    write_export(csv_path, rows)
    out = os.path.join(tmp, "out")

    # School BIG, 2026-27: wizard answers = split (1, two labels), title, folder, dpi, go
    code, log = run([csv_path, "--school", "BIG", "--year", "2026-27"],
                    answers=f"1\n\n\n\n{out}\n96\nY\n")
    check(code == 0, "BIG 2026-27 report builds")
    check("59 responses: school BIG, 2026-27" in log, "only BIG's 2026-27 responses, preview dropped")
    pdf = os.path.join(out, "survey_BIG_2026-27.pdf")
    check(os.path.isfile(pdf), "file name carries school and year")
    if os.path.isfile(pdf):
        text = pdf_text(pdf)
        small = re.findall(r"\bn ?= ?([1-5])\b", text)
        check(not small, f"no 'n=1..5' anywhere in the PDF {small[:5]}")
        check("SMALL" not in text and "TINY" not in text, "no other school named in the PDF")
        check("designated primary contact" in text, "cover says who the report is for")

    # SMALL: one comparison group under 6 -> all students together
    code, log = run([csv_path, "--school", "SMALL", "--year", "2026-27"],
                    answers=f"1\n\n{out}\n96\nY\n")
    check(code == 0 and "all students together" in log, "SMALL report drops the too-small split")

    # TINY: 4 responses -> refused
    code, log = run([csv_path, "--school", "TINY", "--year", "2026-27"])
    check(code != 0 and "at least 6" in log, "TINY (4 responses) is refused")

    # --internal cannot make a school report
    code, log = run([csv_path, "--school", "BIG", "--year", "2026-27", "--internal"])
    check(code != 0, "--internal with --school is refused")

    # Unknown code
    code, log = run([csv_path, "--school", "big", "--year", "2026-27"])
    check(code != 0 and "case sensitive" in log, "school codes are matched exactly")


if __name__ == "__main__":
    unit_tests()
    with tempfile.TemporaryDirectory() as tmp:
        end_to_end(tmp)
    print("FAILED: %d" % check.failed if check.failed else "all checks passed")
    sys.exit(1 if check.failed else 0)
