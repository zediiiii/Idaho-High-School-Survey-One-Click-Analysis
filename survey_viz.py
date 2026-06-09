"""
Idaho Math Badging Survey — Diverging Bar Chart Visualizer
===========================================================
Usage
-----
  python survey_viz.py <input_csv> [options]

  <input_csv>   Qualtrics-exported CSV (3-row header format).
                Pre-filter rows BEFORE passing the file in; this script
                visualizes whatever rows are present.

Options
-------
  --split-col   Column name to use as the Yes/No cross-section split.
                Default: B_1

  --yes-label   Display label for the "Yes" group.  Default: "Math Badging"
  --no-label    Display label for the "No" group.   Default: "Non-Badging"

  --out-dir     Directory for saved PNG files.  Default: ./output
  --no-save     Display charts interactively instead of saving to disk.
  --dpi         Resolution of saved PNGs (default 150).

  --title       Optional overall title suffix added to each chart header.

Examples
--------
  # Full dataset, default split on B_1
  python survey_viz.py survey.csv

  # Pre-filtered to 11th graders only, custom labels
  python survey_viz.py survey_11th.csv --yes-label "Badging 11th" --no-label "Non-Badging 11th"

  # Different split column (e.g. B_5 = badge awareness)
  python survey_viz.py survey.csv --split-col B_5 --yes-label "Aware" --no-label "Not Aware"
"""

import argparse
import os
import sys
import textwrap
from pathlib import Path

import matplotlib
import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Survey structure definition
# ---------------------------------------------------------------------------

LIKERT_ORDER = [
    "Strongly Disagree",
    "Disagree",
    "Somewhat Disagree",
    "Somewhat Agree",
    "Agree",
    "Strongly Agree",
]

# Canonical normalisation — handles Qualtrics mixed-case exports
LIKERT_NORM = {v.lower(): v for v in LIKERT_ORDER}
LIKERT_NORM["strongly disagree"] = "Strongly Disagree"
LIKERT_NORM["disagree"]          = "Disagree"
LIKERT_NORM["somewhat disagree"] = "Somewhat Disagree"
LIKERT_NORM["somewhat agree"]    = "Somewhat Agree"
LIKERT_NORM["agree"]             = "Agree"
LIKERT_NORM["strongly agree"]    = "Strongly Agree"

# Colour palette: negative (left) → positive (right)
LIKERT_COLORS = {
    "Strongly Disagree": "#c0392b",
    "Disagree":          "#e07060",
    "Somewhat Disagree": "#f0b8a8",
    "Somewhat Agree":    "#a8c8f0",
    "Agree":             "#5090d0",
    "Strongly Agree":    "#1a5fa8",
}

# Multi-select questions (comma-separated values in a single cell)
MULTI_SELECT_COLS = {"MUI_2", "MEI_2", "MCP_3", "B_6"}

# Construct definitions: each entry is (column_id, short_label)
CONSTRUCTS = [
    {
        "key":   "MUI",
        "title": "Math Utility & Identity",
        "subtitle": "How much students see math as relevant and important to them",
        "items": [
            ("MUI_1_1", "It is important for me to do well in math"),
            ("MUI_1_2", "Math in school feels related to real life"),
            ("MUI_1_3", "Math relates to my goals after high school"),
            ("MUI_1_4", "I plan to take four years of math in high school"),
        ],
    },
    {
        "key":   "MEI",
        "title": "Math Engagement & Interest",
        "subtitle": "How much students enjoy and are engaged by math",
        "items": [
            ("MEI_1_1", "I enjoy learning math"),
            ("MEI_1_7", "Math is interesting"),
            ("MEI_1_8", "I look forward to taking math"),
            ("MEI_1_9", "I find satisfaction in doing math"),
        ],
    },
    {
        "key":   "MCP",
        "title": "Math Competence Perception",
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

# Single-select non-Likert questions rendered as horizontal bar charts
SINGLE_SELECT = [
    {
        "key":   "DE_Grade",
        "title": "Current Grade Level",
        "subtitle": "Distribution of respondents by grade",
        "order": ["9th", "10th", "11th", "12th"],
    },
    {
        "key":   "DE_Class",
        "title": "Current Math Class",
        "subtitle": "Math course currently enrolled in",
        "order": [
            "Algebra 1 OR Math 1",
            "Geometry OR Math 2",
            "Algebra 2 OR Math 3",
            "Dual Credit Math Course",
        ],
    },
    {
        "key":   "B_7",
        "title": "Next Planned Math Course",
        "subtitle": "Badging students only — which course comes next",
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
        "key":   "B_2",
        "title": "Badging Class Progress",
        "subtitle": "Where in their badging class students currently are",
        "badging_only": True,
        "order": [
            "Towards the beginning of my badging class",
            "In the middle of my badging class",
            "Towards the end of my badging class",
        ],
    },
    {
        "key":   "B_5",
        "title": "Badge Awareness",
        "subtitle": "Were students aware they could earn math badges?",
        "badging_only": True,
        "order": ["Yes", "No"],
    },
]

# Multi-select questions rendered as frequency bar charts
MULTI_SELECT_CHARTS = [
    {
        "key":     "MUI_2",
        "title":   "Post-Graduation Plans",
        "subtitle": "What students plan to do after high school (select all that apply)",
    },
    {
        "key":     "MEI_2",
        "title":   "What Makes a Favourite Math Class",
        "subtitle": "Attributes of their favourite math class (select all that apply)",
    },
    {
        "key":     "MCP_3",
        "title":   "Sources of Math Difficulty",
        "subtitle": "What makes math class difficult (select all that apply)",
    },
    {
        "key":     "B_6",
        "title":   "Ideal Badge Uses",
        "subtitle": "How students would ideally use their earned badges (select all that apply)",
        "badging_only": True,
    },
]

# ---------------------------------------------------------------------------
# Data loading & preparation
# ---------------------------------------------------------------------------

def load_qualtrics(path: str) -> pd.DataFrame:
    """
    Load a Qualtrics CSV that has 3 header rows:
      row 0 — column codes  (used as column names)
      row 1 — question text (skipped here; used only for reference)
      row 2 — import IDs    (skipped)
    Returns a clean DataFrame starting at the first real response row.
    Drops the School column if present.
    """
    df = pd.read_csv(path, skiprows=[1, 2], low_memory=False)
    # Drop school column to protect anonymity during disaggregation
    if "School" in df.columns:
        df = df.drop(columns=["School"])
    # Strip whitespace from string columns
    for col in df.select_dtypes("object").columns:
        df[col] = df[col].str.strip()
    return df


def normalise_likert(series: pd.Series) -> pd.Series:
    return series.map(lambda v: LIKERT_NORM.get(str(v).lower().strip(), np.nan)
                      if pd.notna(v) else np.nan)


def split_groups(df: pd.DataFrame, col: str):
    """Return (yes_df, no_df) split on col == 'Yes' / 'No'."""
    yes = df[df[col] == "Yes"].copy()
    no  = df[df[col] == "No"].copy()
    return yes, no


def pct_counts(series: pd.Series) -> dict:
    """Return {category: (count, pct)} for a normalised Likert series."""
    total = series.dropna().shape[0]
    result = {}
    for cat in LIKERT_ORDER:
        n = (series == cat).sum()
        result[cat] = (int(n), round(100 * n / total, 1) if total else 0.0)
    return result, total


def explode_multiselect(series: pd.Series) -> pd.Series:
    """Explode comma-separated multi-select cells into individual values."""
    exploded = series.dropna().str.split(",").explode().str.strip()
    return exploded


# ---------------------------------------------------------------------------
# Chart helpers
# ---------------------------------------------------------------------------

FONT_TITLE    = {"fontsize": 13, "fontweight": "bold", "color": "#1a1a2e"}
FONT_SUBTITLE = {"fontsize": 9,  "color": "#555577", "style": "italic"}
FONT_AXIS     = {"fontsize": 9,  "color": "#333333"}
FONT_BAR      = {"fontsize": 7.5}

GROUP_COLORS = {
    "yes": "#1a5fa8",
    "no":  "#888899",
}

STRIPE_ALPHA = 0.04   # background row striping


def _add_metadata_footer(fig, yes_n: int, no_n: int,
                          yes_label: str, no_label: str,
                          title_suffix: str = ""):
    fig.text(
        0.5, 0.01,
        f"n={yes_label}: {yes_n}   |   n={no_label}: {no_n}"
        + (f"   |   {title_suffix}" if title_suffix else ""),
        ha="center", fontsize=7.5, color="#777777",
        transform=fig.transFigure,
    )


def _legend_patches(yes_label: str, no_label: str) -> list:
    return [
        mpatches.Patch(facecolor=GROUP_COLORS["yes"], label=yes_label),
        mpatches.Patch(facecolor=GROUP_COLORS["no"],  label=no_label),
    ]


# ---------------------------------------------------------------------------
# Diverging stacked bar chart (Likert constructs)
# ---------------------------------------------------------------------------

def plot_diverging_construct(
    yes_df: pd.DataFrame,
    no_df:  pd.DataFrame,
    construct: dict,
    yes_label: str,
    no_label:  str,
    title_suffix: str = "",
    dpi: int = 150,
) -> plt.Figure:
    """
    Renders one diverging stacked bar panel for a single construct.
    Each item gets TWO rows: one for yes_label, one for no_label.
    The bars diverge from centre (negative categories left, positive right).
    Percentage labels are printed inside each segment when wide enough.
    """
    items  = construct["items"]
    n_items = len(items)
    # Two rows per item (yes on top, no below), plus small gap between items
    n_rows = n_items * 2

    fig_h = max(3.5, 0.55 * n_rows + 2.0)
    fig, ax = plt.subplots(figsize=(13, fig_h), dpi=dpi)
    fig.patch.set_facecolor("white")
    ax.set_facecolor("white")

    # Y positions: each item occupies 2 rows spaced by 1 unit; items separated by 0.4
    item_gap  = 0.35
    row_h     = 1.0
    bar_thick = 0.75

    y_ticks_label  = []  # centre of each item's pair, for item labels
    y_ticks_group  = []  # individual bar centres, for Yes/No labels
    y_group_labels = []

    neg_cats = ["Strongly Disagree", "Disagree", "Somewhat Disagree"]
    pos_cats = ["Somewhat Agree",    "Agree",     "Strongly Agree"]

    def _bar_data(sub_df, col):
        ser = normalise_likert(sub_df[col])
        counts, total = pct_counts(ser)
        return counts, total

    for i, (col, short_label) in enumerate(items):
        # y positions: yes row on top, no row below
        base = i * (2 * row_h + item_gap)
        y_yes = base + row_h
        y_no  = base

        item_centre = base + row_h / 2
        y_ticks_label.append(item_centre)
        y_ticks_group += [y_yes, y_no]
        y_group_labels += [yes_label, no_label]

        # Alternating row background
        if i % 2 == 0:
            ax.barh(
                [y_yes, y_no], [200, 200], left=-100,
                height=bar_thick + 0.05,
                color="#f0f2f8", zorder=0, alpha=0.5,
            )

        for y, sub_df, g_key in [(y_yes, yes_df, "yes"), (y_no, no_df, "no")]:
            counts, total = _bar_data(sub_df, col)
            if total == 0:
                continue

            # Compute pivot: negative categories accumulate leftward from 0
            neg_pcts = [counts[c][1] for c in neg_cats]
            pos_pcts = [counts[c][1] for c in pos_cats]

            # Draw negative bars (left of zero)
            left = 0.0
            for cat, pct in zip(reversed(neg_cats), reversed(neg_pcts)):
                if pct > 0:
                    ax.barh(
                        y, -pct, left=left,
                        height=bar_thick,
                        color=LIKERT_COLORS[cat],
                        edgecolor="white", linewidth=0.4,
                        zorder=3,
                    )
                    if pct >= 5:
                        ax.text(
                            left - pct / 2, y,
                            f"{pct:.0f}%",
                            ha="center", va="center",
                            color="white", fontsize=6.5, fontweight="bold",
                            zorder=4,
                        )
                    left -= pct

            # Draw positive bars (right of zero)
            left = 0.0
            for cat, pct in zip(pos_cats, pos_pcts):
                if pct > 0:
                    ax.barh(
                        y, pct, left=left,
                        height=bar_thick,
                        color=LIKERT_COLORS[cat],
                        edgecolor="white", linewidth=0.4,
                        zorder=3,
                    )
                    if pct >= 5:
                        ax.text(
                            left + pct / 2, y,
                            f"{pct:.0f}%",
                            ha="center", va="center",
                            color="white", fontsize=6.5, fontweight="bold",
                            zorder=4,
                        )
                    left += pct

    # --- Axes formatting ---
    ax.axvline(0, color="#444455", linewidth=1.0, zorder=5)

    total_span = max(
        sum(counts[c][1] for c in neg_cats)
        for col, _ in items
        for counts, _ in [_bar_data(yes_df, col), _bar_data(no_df, col)]
        if _ > 0
    ) if items else 60
    x_lim = max(70, total_span + 10)
    ax.set_xlim(-x_lim, x_lim)

    ax.xaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"{abs(v):.0f}%"))
    ax.tick_params(axis="x", labelsize=8, colors="#555555")
    ax.set_xlabel("← Disagree                Agree →", fontsize=8.5,
                  color="#444444", labelpad=6)

    # Item labels on left y-axis
    ax.set_yticks(y_ticks_label)
    ax.set_yticklabels(
        ["\n".join(textwrap.wrap(short, 34)) for _, short in items],
        fontsize=8.5, color="#1a1a2e",
    )
    ax.yaxis.set_tick_params(length=0)

    # Secondary y-axis: Yes/No group labels on the right
    ax2 = ax.twinx()
    ax2.set_ylim(ax.get_ylim())
    ax2.set_yticks(y_ticks_group)
    ax2.set_yticklabels(y_group_labels, fontsize=7.5, color="#555577")
    ax2.yaxis.set_tick_params(length=0)
    ax2.set_ylabel("")

    ax.spines[["top", "right", "left"]].set_visible(False)
    ax.spines["bottom"].set_color("#cccccc")
    ax2.spines[["top", "left", "bottom"]].set_visible(False)
    ax2.spines["right"].set_color("#cccccc")

    # --- Likert legend ---
    legend_patches = [
        mpatches.Patch(facecolor=LIKERT_COLORS[c], label=c)
        for c in LIKERT_ORDER
    ]
    ax.legend(
        handles=legend_patches,
        loc="lower center",
        bbox_to_anchor=(0.5, -0.18 if n_items <= 5 else -0.14),
        ncol=6,
        fontsize=7.5,
        frameon=False,
        handlelength=1.2,
    )

    # --- Title ---
    title_text = construct["title"]
    if title_suffix:
        title_text += f" — {title_suffix}"
    fig.suptitle(title_text, **FONT_TITLE, y=1.01)
    ax.set_title(construct["subtitle"], **FONT_SUBTITLE, pad=4)

    _add_metadata_footer(fig, len(yes_df), len(no_df), yes_label, no_label)
    fig.tight_layout(rect=[0, 0.04, 1, 1])
    return fig


# ---------------------------------------------------------------------------
# Single-select grouped horizontal bar chart
# ---------------------------------------------------------------------------

def plot_single_select(
    yes_df: pd.DataFrame,
    no_df:  pd.DataFrame,
    q_def: dict,
    yes_label: str,
    no_label:  str,
    title_suffix: str = "",
    dpi: int = 150,
) -> plt.Figure:
    col     = q_def["key"]
    order   = q_def.get("order", [])
    badging_only = q_def.get("badging_only", False)

    # Build ordered frequency tables
    def freq(sub_df):
        vc = sub_df[col].value_counts()
        total = vc.sum()
        result = {}
        for cat in order:
            n = int(vc.get(cat, 0))
            result[cat] = (n, round(100 * n / total, 1) if total else 0.0)
        # Catch any categories not in order
        for cat in vc.index:
            if cat not in result:
                n = int(vc[cat])
                result[cat] = (n, round(100 * n / total, 1) if total else 0.0)
        return result, total

    yes_freq, yes_n = freq(yes_df)
    no_freq,  no_n  = freq(no_df)

    all_cats = list(dict.fromkeys(order + [c for c in (list(yes_freq) + list(no_freq)) if c not in order]))
    # Remove categories with zero across both groups
    all_cats = [c for c in all_cats if yes_freq.get(c, (0,))[0] + no_freq.get(c, (0,))[0] > 0]

    n_cats = len(all_cats)
    fig_h  = max(3.0, 0.5 * n_cats + 2.0)
    fig, ax = plt.subplots(figsize=(10, fig_h), dpi=dpi)
    fig.patch.set_facecolor("white")
    ax.set_facecolor("white")

    bar_w  = 0.35
    y_base = np.arange(n_cats)

    groups = ([(yes_freq, GROUP_COLORS["yes"], yes_label, yes_n)]
              if badging_only
              else [(yes_freq, GROUP_COLORS["yes"], yes_label, yes_n),
                    (no_freq,  GROUP_COLORS["no"],  no_label,  no_n)])
    n_grp  = len(groups)

    for g_idx, (freq_d, color, label, total) in enumerate(groups):
        offset = (g_idx - (n_grp - 1) / 2) * bar_w
        pcts   = [freq_d.get(c, (0, 0.0))[1] for c in all_cats]
        cnts   = [freq_d.get(c, (0, 0.0))[0] for c in all_cats]
        bars   = ax.barh(y_base + offset, pcts, height=bar_w,
                         color=color, alpha=0.88,
                         edgecolor="white", linewidth=0.5,
                         label=label, zorder=3)
        for bar, pct, cnt in zip(bars, pcts, cnts):
            if pct > 0:
                ax.text(
                    pct + 0.8, bar.get_y() + bar.get_height() / 2,
                    f"{pct:.0f}% (n={cnt})",
                    va="center", ha="left",
                    fontsize=7.5, color="#333333",
                )

    ax.set_yticks(y_base)
    ax.set_yticklabels(
        ["\n".join(textwrap.wrap(c, 36)) for c in all_cats],
        fontsize=8.5,
    )
    ax.set_xlabel("Percentage of respondents", fontsize=8.5, color="#444444")
    ax.xaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"{v:.0f}%"))
    ax.set_xlim(0, 105)
    ax.tick_params(axis="x", labelsize=8, colors="#555555")

    ax.spines[["top", "right"]].set_visible(False)
    ax.spines[["bottom", "left"]].set_color("#cccccc")

    if not badging_only:
        ax.legend(fontsize=8, frameon=False, loc="lower right")

    title_text = q_def["title"]
    if title_suffix:
        title_text += f" — {title_suffix}"
    fig.suptitle(title_text, **FONT_TITLE, y=1.01)
    ax.set_title(q_def["subtitle"], **FONT_SUBTITLE, pad=4)

    _add_metadata_footer(fig, yes_n, no_n if not badging_only else 0,
                         yes_label, no_label)
    fig.tight_layout(rect=[0, 0.04, 1, 1])
    return fig


# ---------------------------------------------------------------------------
# Multi-select frequency chart
# ---------------------------------------------------------------------------

def plot_multi_select(
    yes_df: pd.DataFrame,
    no_df:  pd.DataFrame,
    q_def: dict,
    yes_label: str,
    no_label:  str,
    title_suffix: str = "",
    dpi: int = 150,
) -> plt.Figure:
    col          = q_def["key"]
    badging_only = q_def.get("badging_only", False)

    def freq(sub_df):
        total = sub_df[col].notna().sum()
        exploded = explode_multiselect(sub_df[col])
        vc = exploded.value_counts()
        return vc, total

    yes_vc, yes_n = freq(yes_df)
    no_vc,  no_n  = freq(no_df)

    # Union of categories, sorted by yes frequency descending
    all_cats = list(dict.fromkeys(
        list(yes_vc.index) + [c for c in no_vc.index if c not in yes_vc.index]
    ))

    n_cats = len(all_cats)
    fig_h  = max(3.5, 0.52 * n_cats + 2.2)
    fig, ax = plt.subplots(figsize=(11, fig_h), dpi=dpi)
    fig.patch.set_facecolor("white")
    ax.set_facecolor("white")

    bar_w  = 0.36
    y_base = np.arange(n_cats)

    groups = ([(yes_vc, yes_n, GROUP_COLORS["yes"], yes_label)]
              if badging_only
              else [(yes_vc, yes_n, GROUP_COLORS["yes"], yes_label),
                    (no_vc,  no_n,  GROUP_COLORS["no"],  no_label)])
    n_grp  = len(groups)

    for g_idx, (vc, total, color, label) in enumerate(groups):
        offset = (g_idx - (n_grp - 1) / 2) * bar_w
        pcts   = [round(100 * vc.get(c, 0) / total, 1) if total else 0 for c in all_cats]
        cnts   = [int(vc.get(c, 0)) for c in all_cats]
        bars   = ax.barh(y_base + offset, pcts, height=bar_w,
                         color=color, alpha=0.88,
                         edgecolor="white", linewidth=0.5,
                         label=label, zorder=3)
        for bar, pct, cnt in zip(bars, pcts, cnts):
            if pct > 0:
                ax.text(
                    pct + 0.8, bar.get_y() + bar.get_height() / 2,
                    f"{pct:.0f}% (n={cnt})",
                    va="center", ha="left",
                    fontsize=7.5, color="#333333",
                )

    ax.set_yticks(y_base)
    ax.set_yticklabels(
        ["\n".join(textwrap.wrap(c, 40)) for c in all_cats],
        fontsize=8.2,
    )
    ax.set_xlabel("% of respondents who selected this option", fontsize=8.5, color="#444444")
    ax.xaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"{v:.0f}%"))
    ax.set_xlim(0, 110)
    ax.tick_params(axis="x", labelsize=8, colors="#555555")

    ax.spines[["top", "right"]].set_visible(False)
    ax.spines[["bottom", "left"]].set_color("#cccccc")

    if not badging_only:
        ax.legend(fontsize=8.5, frameon=False, loc="lower right")

    title_text = q_def["title"]
    if title_suffix:
        title_text += f" — {title_suffix}"
    fig.suptitle(title_text, **FONT_TITLE, y=1.01)
    ax.set_title(q_def["subtitle"], **FONT_SUBTITLE, pad=4)

    _add_metadata_footer(fig, yes_n, no_n if not badging_only else 0,
                         yes_label, no_label)
    fig.tight_layout(rect=[0, 0.04, 1, 1])
    return fig


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Idaho Math Badging Survey — diverging bar chart visualizer",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("input_csv", help="Path to the Qualtrics CSV file")
    p.add_argument("--split-col",  default="B_1",        help="Column to split on (default: B_1)")
    p.add_argument("--yes-label",  default="Math Badging", help="Label for Yes group")
    p.add_argument("--no-label",   default="Non-Badging",  help="Label for No group")
    p.add_argument("--out-dir",    default="output",      help="Output directory for PNGs")
    p.add_argument("--no-save",    action="store_true",   help="Show charts interactively")
    p.add_argument("--dpi",        type=int, default=150, help="PNG resolution (default 150)")
    p.add_argument("--title",      default="",            help="Optional title suffix on each chart")
    return p


def save_or_show(fig: plt.Figure, name: str, out_dir: str,
                 no_save: bool, dpi: int):
    if no_save:
        plt.show()
    else:
        os.makedirs(out_dir, exist_ok=True)
        path = os.path.join(out_dir, f"{name}.png")
        fig.savefig(path, dpi=dpi, bbox_inches="tight", facecolor="white")
        print(f"  Saved → {path}")
    plt.close(fig)


def main():
    args = build_parser().parse_args()

    print(f"\nLoading: {args.input_csv}")
    df = load_qualtrics(args.input_csv)
    print(f"  {len(df)} responses loaded")

    yes_df, no_df = split_groups(df, args.split_col)
    print(f"  {args.yes_label}: n={len(yes_df)}   {args.no_label}: n={len(no_df)}\n")

    kw = dict(
        yes_label=args.yes_label,
        no_label=args.no_label,
        title_suffix=args.title,
        dpi=args.dpi,
    )

    # 1. Diverging Likert constructs
    print("── Likert constructs ──────────────────────────────────")
    for construct in CONSTRUCTS:
        print(f"  Rendering: {construct['title']}")
        fig = plot_diverging_construct(yes_df, no_df, construct, **kw)
        save_or_show(fig, f"likert_{construct['key'].lower()}", args.out_dir,
                     args.no_save, args.dpi)

    # 2. Single-select questions
    print("\n── Single-select questions ────────────────────────────")
    for q_def in SINGLE_SELECT:
        col = q_def["key"]
        if col not in df.columns:
            print(f"  Skipping {col} — not in data")
            continue
        print(f"  Rendering: {q_def['title']}")
        fig = plot_single_select(yes_df, no_df, q_def, **kw)
        save_or_show(fig, f"single_{col.lower()}", args.out_dir,
                     args.no_save, args.dpi)

    # 3. Multi-select questions
    print("\n── Multi-select questions ─────────────────────────────")
    for q_def in MULTI_SELECT_CHARTS:
        col = q_def["key"]
        if col not in df.columns:
            print(f"  Skipping {col} — not in data")
            continue
        print(f"  Rendering: {q_def['title']}")
        fig = plot_multi_select(yes_df, no_df, q_def, **kw)
        save_or_show(fig, f"multi_{col.lower()}", args.out_dir,
                     args.no_save, args.dpi)

    print(f"\n✓ Done — {0 if args.no_save else 'charts saved to'} {'' if args.no_save else args.out_dir}\n")


if __name__ == "__main__":
    main()
