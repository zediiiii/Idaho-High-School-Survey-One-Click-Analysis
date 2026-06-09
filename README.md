# Idaho High School Survey One-Click Analysis

Turn a raw Qualtrics survey export into a full set of publication-ready charts
in a single terminal command — no programming experience required.

---

## What This Does

This tool reads an Idaho High School Mathematics Survey CSV file (exported
directly from Qualtrics) and automatically produces three types of charts:

| Chart type | What it shows |
|---|---|
| **Diverging stacked bar** | Likert-scale responses (Strongly Disagree → Strongly Agree), split by any two groups you choose |
| **Grouped horizontal bar** | Single-choice questions (grade level, current course, next course, etc.) |
| **Frequency bar** | Multi-select questions (post-graduation plans, sources of difficulty, badge uses, etc.) |

Every chart shows exact percentages and counts directly on the bars — no
squinting at a legend required. Charts are saved as high-resolution PNG files
you can drop straight into a Word document, PowerPoint, or report.

The three main constructs measured by the survey are:

- **MUI — Math Utility & Identity:** Does math feel relevant and important?
- **MEI — Math Engagement & Interest:** Do students enjoy and engage with math?
- **MCP — Math Competence Perception:** Do students believe they can succeed in math?

---

## What You Need Before You Start

**One-time setup — you only do this once.**

1. **Python 3.10 or newer.**
   Check whether you already have it by opening a terminal and typing:
   ```
   python3 --version
   ```
   If you see a version number starting with 3.10 or higher, you're good.
   If not, download Python from [python.org/downloads](https://www.python.org/downloads/)
   and install it. Accept all defaults during installation.

2. **This repository** (the code files you are reading right now).
   If you received a ZIP file, unzip it somewhere you can find it (your Desktop
   works fine). If you are reading this on GitHub, click the green **Code**
   button → **Download ZIP**, then unzip it.

3. **The survey libraries.** Open a terminal, navigate to the folder you just
   unzipped, and run:
   ```
   pip install -r requirements.txt
   ```
   This downloads three standard scientific libraries (matplotlib, numpy, pandas)
   that do the heavy lifting. You only need to do this once per computer.

> **What is a terminal?**
> On Windows: press `Win + R`, type `cmd`, press Enter.
> On Mac: open Spotlight (`Cmd + Space`), type `Terminal`, press Enter.
> To navigate to your folder, type `cd ` (with a space after it), then drag
> and drop the folder onto the terminal window, then press Enter.

---

## Preparing Your Data

The tool expects a Qualtrics CSV export with its standard three-row header
(row 1 = column codes, row 2 = question text, row 3 = import IDs). This is
exactly what Qualtrics produces when you click **Data & Analysis → Export &
Import → Export Data → CSV**.

> ⚠️ **Do not include the School column** in files you share or publish.
> The `.gitignore` file in this repository is configured to prevent any `.csv`
> file from ever being uploaded to GitHub accidentally.

### Filtering before you run

This tool visualises whatever rows you give it. If you want charts for a
specific subgroup — say, 11th graders only, or a single school — filter your
spreadsheet first (Excel, Google Sheets, or Numbers all work fine) and save a
new CSV. Then run the tool on that filtered file.

---

## Running the Tool

Open a terminal in the project folder and run:

```bash
python3 survey_viz.py your_survey_file.csv
```

That's it. Charts will appear in a new folder called `output/` right alongside
the script.

### Common variations

**Give the two groups meaningful names on the charts:**
```bash
python3 survey_viz.py survey.csv --yes-label "Badging Students" --no-label "Non-Badging Students"
```

**Add a subtitle to every chart (useful for filtered subsets):**
```bash
python3 survey_viz.py survey_11th.csv --title "11th Grade Only"
```

**Use a different column as the Yes/No split:**
The default split is column `B_1` (Are you a Math Badging student?).
To split on badge awareness (`B_5`) instead:
```bash
python3 survey_viz.py survey.csv --split-col B_5 --yes-label "Badge Aware" --no-label "Not Aware"
```

**Save higher-resolution images (good for print):**
```bash
python3 survey_viz.py survey.csv --dpi 300
```

**Preview charts on screen instead of saving:**
```bash
python3 survey_viz.py survey.csv --no-save
```

**Save charts to a custom folder:**
```bash
python3 survey_viz.py survey.csv --out-dir "charts/spring2026"
```

---

## Output Files

Running the tool produces up to 12 PNG files:

| File | Content |
|---|---|
| `likert_mui.png` | Math Utility & Identity — 4 Likert items |
| `likert_mei.png` | Math Engagement & Interest — 4 Likert items |
| `likert_mcp.png` | Math Competence Perception — 9 Likert items |
| `single_de_grade.png` | Current grade level |
| `single_de_class.png` | Current math class |
| `single_b_7.png` | Next planned math course *(badging students only)* |
| `single_b_2.png` | Where in badging class *(badging students only)* |
| `single_b_5.png` | Badge awareness *(badging students only)* |
| `multi_mui_2.png` | Post-graduation plans |
| `multi_mei_2.png` | What makes a favourite math class |
| `multi_mcp_3.png` | Sources of math difficulty |
| `multi_b_6.png` | How students want to use badges *(badging students only)* |

---

## Typical Workflow for a New Data Pull

```
1. Export CSV from Qualtrics (no changes needed).
2. Optionally filter to a subgroup in Excel.
3. Open terminal → navigate to this folder.
4. Run:  python3 survey_viz.py your_file.csv --title "Spring 2026"
5. Open the output/ folder — your charts are ready.
```

Total time after setup: about 10 seconds.

---

## Understanding the Chart Layout

### Diverging bar charts (Likert items)

```
Item label   ◄─── Disagree side ──── | ──── Agree side ───►
             ██████████████████████ | ██████████████████
             (Badging group)
             ███████████████ | █████████████████████████
             (Non-Badging group)
```

- The vertical line at the centre is the neutral point (0%).
- Red shades = disagree responses; blue shades = agree responses.
- Percentages are printed directly on each segment.
- Group labels (e.g. "Math Badging" / "Non-Badging") appear on the right axis.
- Sample sizes appear in the footer.

### Bar charts (single- and multi-select)

- Each category gets two bars side-by-side, one per group.
- Percentages and raw counts (`n=`) are printed at the end of each bar.
- Multi-select percentages can exceed 100% because respondents could choose
  more than one option.

---

## Adapting for Future Surveys

If the survey instrument changes or a new version is fielded, the only section
of the code you need to update is the **Survey structure definition** block near
the top of `survey_viz.py` (lines 50–130). It is written in plain, readable
Python — each construct is just a list of `(column_name, "Short label")` pairs.
No statistics or chart-drawing code needs to change.

---

## Data Privacy

- **No data file is ever stored in this repository.** The `.gitignore` blocks
  all `.csv`, `.xlsx`, and image files.
- The `School` column is automatically removed from analysis at load time.
- Always filter to remove individually identifying information before sharing
  any output charts when `n` is small.

---

## Questions or Problems?

Common issues:

| Problem | Fix |
|---|---|
| `python3: command not found` | Install Python from python.org |
| `No module named 'matplotlib'` | Run `pip install -r requirements.txt` |
| `FileNotFoundError` | Check that your CSV filename is spelled correctly and is in the same folder as the script |
| Charts save but are blank | Make sure the CSV has real responses (not just the 3 header rows) |
| Wrong split — both groups show the same data | Confirm that your `--split-col` column contains exactly the values `Yes` and `No` |

For anything else, open an issue on GitHub or contact the Regional Mathematics
Center at LCSC.
