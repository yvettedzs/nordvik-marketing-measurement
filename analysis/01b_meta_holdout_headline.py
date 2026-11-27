"""
Headline chart for the Meta geo holdout (Germany): actual orders vs the synthetic control, Meta pause shaded.
ALL DATA IS SIMULATED (fictional brand "Nordvik Outdoor").

Computes nothing itself. It runs analysis/01_meta_holdout.py unchanged in a temporary folder (with copies of the
two data files it reads), takes that run's weekly series and results, and checks the run's results text equals the
committed analysis/meta_holdout_results.txt before drawing. The committed chart and results file are not touched.

Run from the repository root:  python analysis/01b_meta_holdout_headline.py
Output: analysis/meta_holdout_headline.png
"""
from __future__ import annotations

import contextlib
import io
import re
import runpy
import shutil
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt                       # noqa: E402
from matplotlib.lines import Line2D                    # noqa: E402
from matplotlib.patches import Patch                   # noqa: E402

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "analysis" / "01_meta_holdout.py"
RESULTS = REPO / "analysis" / "meta_holdout_results.txt"
PNG_OUT = REPO / "analysis" / "meta_holdout_headline.png"
DATA_FILES = ["data/simulated_weekly_data.csv", "data/events_calendar.csv"]
WEEKS_BEFORE = 26                                      # chart starts 26 weeks before the pause (November 2025)

# same tokens as analysis/04_conversion_lag_cohorts.py and the dashboard
INK, INK2, MUTED = "#0b0b0b", "#52514e", "#898781"
GRID, AXIS, SURFACE, WASH = "#e1e0d9", "#c3c2b7", "#fcfcfb", "#f0efec"
ACTUAL, CONTROL = "#2a78d6", "#eb6834"                 # categorical slots 1 and 2 (validated pair)

WIDTH_IN, HEIGHT_IN, DPI = 12, 6.6667, 150             # 1800 x 1000 px
HEADLINE_PT, HEADLINE2_PT = 32, 24                     # about 15 px and 11 px tall when shown 400 px wide


def run_holdout() -> dict:
    """Run 01_meta_holdout.py unchanged in a temp folder; return its globals (series, weights and results)."""
    with tempfile.TemporaryDirectory() as tmp:
        for rel in DATA_FILES:
            (Path(tmp) / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(REPO / rel, Path(tmp) / rel)
        (Path(tmp) / "analysis").mkdir()
        with contextlib.chdir(tmp), contextlib.redirect_stdout(io.StringIO()):
            g = runpy.run_path(str(SCRIPT), run_name="__main__")
        plt.close("all")
    return g


def check_against_results(g: dict) -> None:
    """The run must reproduce the committed results text exactly; otherwise the chart would disagree with it."""
    committed = RESULTS.read_text(encoding="utf-8")
    if g["res"] != committed:
        raise SystemExit(f"{RESULTS.relative_to(REPO).as_posix()} is out of date: re-run analysis/01_meta_holdout.py "
                         "before drawing this chart.")


def lost_orders() -> int:
    """Orders lost when Meta was paused, as published in the results file ("... 497 lost when paused ...")."""
    m = re.search(r"^Incremental orders from Meta: ([\d,]+) lost when paused", RESULTS.read_text(encoding="utf-8"),
                  re.MULTILINE)
    if not m:
        raise SystemExit(f"{RESULTS.relative_to(REPO).as_posix()}: no 'Incremental orders from Meta: ... lost' line.")
    return int(m[1].replace(",", ""))


def headline(g: dict) -> tuple[str, str]:
    lost = round(-g["pct"] * 100)
    return (f"Pausing Meta cut German orders by ~{lost}%",
            f"Incremental ROAS {g['iroas']:.2f} (95% range {g['iroas_lo']:.1f}–{g['iroas_hi']:.1f}) "
            f"vs {g['BREAK_EVEN']:.1f} break-even")


def signed_pct(v: float) -> str:
    """-0.069 -> '−6.9%' (typographic minus)."""
    return f"{v * 100:+.1f}%".replace("-", "−")


def subtitle(g: dict) -> str:
    return (f"Germany weekly orders vs a synthetic control built from {', '.join(g['CONTROLS'][:-1])} and "
            f"{g['CONTROLS'][-1]}. Simulated data, fictional brand.\n"
            f"24-week window: {g['act'].sum():,.0f} orders actual vs {g['cf'].sum():,.0f} expected "
            f"({signed_pct(g['pct'])}, 95% interval {signed_pct(g['lo'])} to {signed_pct(g['hi'])}).")


def draw(g: dict, out: Path) -> None:
    weeks = pd.to_datetime(g["weeks"])
    x = np.array(weeks)
    T0, T1, win = g["T0"], g["T1"], g["win"]
    start = T0 - WEEKS_BEFORE
    actual = g["y"].astype(float)
    control = g["X"] @ g["w"]                          # the fitted weights applied to the control markets
    control[sorted(g["PROMO"])] = np.nan               # promo weeks were not used to fit the weights
    s = slice(start, None)

    plt.rcParams.update({"font.family": ["Segoe UI", "DejaVu Sans"], "font.size": 12, "axes.edgecolor": AXIS,
                         "axes.labelcolor": INK2, "xtick.color": INK2, "ytick.color": INK2,
                         "axes.facecolor": SURFACE, "figure.facecolor": SURFACE, "savefig.facecolor": SURFACE})
    fig = plt.figure(figsize=(WIDTH_IN, HEIGHT_IN), dpi=DPI)
    ax = fig.add_axes((0.065, 0.09, 0.91, 0.60))

    top = 470
    ax.axvspan(x[T0], x[T1 + 1], ymax=430 / top, color=WASH, lw=0, zorder=0)   # stops below the bracket
    ax.text(x[T0] + (x[T1 + 1] - x[T0]) / 2, 392, "Meta paused\n(12 weeks)", ha="center", va="bottom",
            color=INK2, fontsize=12, linespacing=1.2)
    ax.fill_between(x[win], actual[win], control[win], color=CONTROL, alpha=0.16, lw=0, zorder=1,
                          interpolate=True)
    ax.plot(x[s], control[s], color=CONTROL, lw=2, solid_joinstyle="round", solid_capstyle="round", zorder=3)
    ax.plot(x[s], actual[s], color=ACTUAL, lw=2, solid_joinstyle="round", solid_capstyle="round", zorder=4)

    # effect window bracket: first paused week to the end of the data
    yb = 445
    ax.plot([x[T0], x[T0], x[-1], x[-1]], [yb - 10, yb, yb, yb - 10], color=INK2, lw=1, zorder=2,
            clip_on=False)
    ax.text(x[T0] + (x[-1] - x[T0]) / 2, yb + 6, "Effect measured over 24 weeks: pause + 12 weeks of late orders",
            ha="center", va="bottom", color=INK2, fontsize=12)

    promo = sorted(g["PROMO"])
    # under the break in the synthetic-control line, below the actual line
    ax.text(x[promo[0]] + (x[promo[-1]] - x[promo[0]]) / 2, 205, "Spring promo + after-effect:\nleft out of the fit",
            ha="center", va="top", color=MUTED, fontsize=10.5, linespacing=1.2)

    ax.set_xlim(x[start] - np.timedelta64(5, "D"), x[-1] + np.timedelta64(5, "D"))
    ax.set_ylim(0, top)
    ax.set_yticks(range(0, 401, 100))
    ax.set_ylabel("Orders per week")
    ax.grid(axis="y", color=GRID, lw=1, ls="-")
    ax.set_axisbelow(True)
    ax.spines[["top", "right", "left"]].set_visible(False)
    ax.tick_params(axis="y", length=0)
    ax.xaxis.set_major_locator(matplotlib.dates.MonthLocator())
    ax.xaxis.set_major_formatter(matplotlib.dates.DateFormatter("%b %Y"))
    for lbl in ax.get_xticklabels():
        lbl.set_fontsize(10.5)

    lost = lost_orders()
    handles = [Line2D([], [], color=ACTUAL, lw=2), Line2D([], [], color=CONTROL, lw=2),
               Patch(facecolor=CONTROL, alpha=0.16, lw=0)]
    labels = ["Germany, actual orders", "Synthetic control (expected with Meta on)",
              f"Net gap: {lost:,} fewer orders over the 24 weeks"]
    ax.legend(handles, labels, loc="upper left", bbox_to_anchor=(0.0, 0.985), frameon=False, fontsize=11.5,
              labelcolor=INK, handlelength=1.8)

    h1, h2 = headline(g)
    fig.text(0.065, 0.965, h1, ha="left", va="top", color=INK, fontsize=HEADLINE_PT, fontweight="bold")
    fig.text(0.065, 0.878, h2, ha="left", va="top", color=INK, fontsize=HEADLINE2_PT)
    fig.text(0.065, 0.805, subtitle(g), ha="left", va="top", color=INK2, fontsize=11.5, linespacing=1.4)
    fig.savefig(out, dpi=DPI)
    plt.close(fig)


def main(out: Path | str = PNG_OUT) -> Path:
    g = run_holdout()
    check_against_results(g)
    out = Path(out)
    draw(g, out)
    return out


if __name__ == "__main__":
    path = main(Path(sys.argv[1]) if len(sys.argv) > 1 else PNG_OUT)
    print(f"wrote {path}")
