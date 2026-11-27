"""Headline chart for the Meta holdout (analysis/01b_meta_holdout_headline.py): its numbers are the published ones,
it draws without touching the committed holdout outputs, and its headline text is exactly as agreed."""
import hashlib
import importlib.util

import pytest
from PIL import Image

from conftest import REPO_ROOT as REPO

SPEC = importlib.util.spec_from_file_location("holdout_headline", REPO / "analysis" / "01b_meta_holdout_headline.py")
hh = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(hh)

COMMITTED = [REPO / "analysis" / "meta_holdout.png", REPO / "analysis" / "meta_holdout_results.txt"]


def digest(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


@pytest.fixture(scope="module")
def run():
    before = {p: digest(p) for p in COMMITTED}
    g = hh.run_holdout()
    assert {p: digest(p) for p in COMMITTED} == before          # the temp-folder run leaves the repo outputs alone
    return g


def test_run_reproduces_published_results(run):
    hh.check_against_results(run)                                # raises SystemExit if the results file is stale


def test_headline_and_subtitle_text(run):
    assert hh.headline(run) == ("Pausing Meta cut German orders by ~7%",
                                "Incremental ROAS 2.45 (95% range 1.0–3.9) vs 1.8 break-even")
    sub = hh.subtitle(run)
    assert "AT, FR, NL, UK and SE" in sub and "Simulated data, fictional brand." in sub
    assert "6,655 orders actual vs 7,152 expected (−6.9%, 95% interval −11.0% to −2.9%)" in sub


def test_headline_numbers_match_results_file(run):
    text = (REPO / "analysis" / "meta_holdout_results.txt").read_text(encoding="utf-8")
    assert f"Incremental ROAS: {run['iroas']:.2f}  (95% interval {run['iroas_lo']:.2f} to {run['iroas_hi']:.2f})" in text
    assert f"({run['pct']:+.1%}, 95% interval {run['lo']:+.1%} to {run['hi']:+.1%})" in text
    assert f"Break-even ROAS: {run['BREAK_EVEN']:.2f}" in text


def test_draws_png(run, tmp_path):
    out = tmp_path / "headline.png"
    hh.draw(run, out)
    assert Image.open(out).size == (1800, 1000)
