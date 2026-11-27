"""The weeks 01_meta_holdout.py leaves out of the synthetic-control fit are the spring promo in
data/events_calendar.csv plus its 4 after-weeks, and exactly the window 02_discount_prepost.py measures
(promo weeks + its equal-length follow-up window). Both scripts run unchanged in a temp folder."""
import contextlib
import io
import runpy
import shutil

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402
import pytest  # noqa: E402

from conftest import REPO_ROOT as REPO  # noqa: E402

DATA_FILES = ["data/simulated_weekly_data.csv", "data/events_calendar.csv"]
AFTER_WEEKS = 4                       # the promo's after-effect weeks, as in the budget memo's 8-week window


def run_in_tmp(script: str, folder):
    """Run analysis/<script> unchanged with copies of the data files; return its globals. The repo is not written."""
    for rel in DATA_FILES:
        (folder / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO / rel, folder / rel)
    (folder / "analysis").mkdir(exist_ok=True)
    with contextlib.chdir(folder), contextlib.redirect_stdout(io.StringIO()):
        g = runpy.run_path(str(REPO / "analysis" / script), run_name="__main__")
    plt.close("all")
    return g


@pytest.fixture(scope="module")
def holdout(tmp_path_factory):
    return run_in_tmp("01_meta_holdout.py", tmp_path_factory.mktemp("holdout"))


@pytest.fixture(scope="module")
def weeks(holdout):
    return [pd.Timestamp(w) for w in holdout["weeks"]]


def dates(weeks, idx):
    return [str(weeks[i].date()) for i in sorted(idx)]


def test_excluded_weeks_are_calendar_promo_plus_after_weeks(holdout, weeks):
    cal = pd.read_csv(REPO / "data" / "events_calendar.csv", parse_dates=["start_week", "end_week"])
    promo = cal[cal.event == "promo"]
    assert len(promo) == 1, "expected exactly one promo in data/events_calendar.csv"
    p0 = weeks.index(promo.start_week.iloc[0])
    p1 = weeks.index(promo.end_week.iloc[0])
    expected = set(range(p0, p1 + 1 + AFTER_WEEKS))
    excluded = set(holdout["PROMO"])
    assert excluded == expected, (f"01_meta_holdout.py leaves out {dates(weeks, excluded)}, but the calendar promo "
                                  f"plus {AFTER_WEEKS} after-weeks is {dates(weeks, expected)}")


def test_excluded_weeks_equal_discount_analysis_window(holdout, weeks, tmp_path_factory):
    discount = run_in_tmp("02_discount_prepost.py", tmp_path_factory.mktemp("discount"))
    window = set(discount["nw"])                       # promo weeks + equal-length follow-up window
    excluded = set(holdout["PROMO"])
    assert excluded == window, (f"01_meta_holdout.py leaves out {dates(weeks, excluded)}, but "
                                f"02_discount_prepost.py measures {dates(weeks, window)}")
