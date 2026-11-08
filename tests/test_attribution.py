"""
Tests for the attribution extension (generate_journeys.py, analysis/03_attribution_models.py).
Run from the repository root:  python -m pytest tests/test_attribution.py -v      (add -m "not slow" to skip D and E)

  A. toy paths with hand-checked credits, for every model
  B. lift cap: p0 + sum(lifts) never exceeds 1; capped worlds keep exact counterfactual reruns
  C. committed outputs: credits add up to 100% of orders; calibration against the repo assumptions
  D. slow: regenerate in a temp folder -> identical outputs; runtime reported (limit 300 s)
  E. slow: full world in memory -> reruns equal per-order labels and the committed truth file
"""
import gzip
import hashlib
import importlib.util
import re
import shutil
import subprocess
import sys
import time

import numpy as np
import pandas as pd
import pytest

import generate_journeys as gj

_spec = importlib.util.spec_from_file_location("attribution_models", gj.REPO / "analysis" / "03_attribution_models.py")
am = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(am)

ORDER_DAY = 400.0
TOL = 1e-12


# ============================================================ A. toy paths
def toy(path, quote_before=None, pid=1):
    """path: list of (channel, days before the order). quote_before: days before the order, or None."""
    t = pd.DataFrame({"person_id": pid, "day": [ORDER_DAY - d for _, d in path], "channel": [c for c, _ in path]})
    o = pd.DataFrame({"person_id": [pid], "order_day": [ORDER_DAY],
                      "quote_day": [np.nan if quote_before is None else ORDER_DAY - quote_before]})
    return t, o


def credits(model, path, window=90, quote_before=None):
    t, o = toy(path, quote_before)
    c = am.MODELS[model](t, o, window)
    assert abs(c.credit.sum() - 1) < TOL
    return {k: v for k, v in c.groupby("channel").credit.sum().items()}


def approx(got, expected, tol=TOL):
    assert set(got) == set(expected), (got, expected)
    for k, v in expected.items():
        assert abs(got[k] - v) < tol, (k, got[k], v)


PATH_A = [("Meta", 40), ("Google", 20), ("Email", 2), ("Direct", 0.01)]


def test_path_a_all_models_90d():
    approx(credits("last_click", PATH_A), {"Direct": 1})
    approx(credits("last_non_direct", PATH_A), {"Email": 1})
    approx(credits("first_click", PATH_A), {"Meta": 1})
    approx(credits("linear", PATH_A), {"Meta": .25, "Google": .25, "Email": .25, "Direct": .25})
    approx(credits("u_shaped", PATH_A), {"Meta": .4, "Google": .1, "Email": .1, "Direct": .4})
    # hand-computed: weights 2^(-40/7)=0.01905, 2^(-20/7)=0.13802, 2^(-2/7)=0.82034, 2^(-0.01/7)=0.99901
    approx(credits("time_decay_7d", PATH_A), {"Meta": .00964, "Google": .06983, "Email": .41506, "Direct": .50547}, 1e-4)
    # 2^(-40/30)=0.39685, 2^(-20/30)=0.62996, 2^(-2/30)=0.95483, 2^(-0.01/30)=0.99977
    approx(credits("time_decay_30d", PATH_A), {"Meta": .13311, "Google": .21130, "Email": .32026, "Direct": .33533}, 1e-4)


def test_w_shaped_anchor_and_fallback():
    # quote 10 days before the order -> anchor = Google (last touch at or before the quote)
    approx(credits("w_shaped", PATH_A, quote_before=10), {"Meta": .3, "Google": .3, "Email": .1, "Direct": .3})
    # quote 30 days before -> anchor = Meta, which is also the first touch: roles add up (0.6); rest 0.1 split
    approx(credits("w_shaped", PATH_A, quote_before=30), {"Meta": .6, "Google": .05, "Email": .05, "Direct": .3})
    # no quote (self-serve) -> U-shaped
    approx(credits("w_shaped", PATH_A), credits("u_shaped", PATH_A))
    # anchor touch outside the lookback window -> U-shaped on what is left
    approx(credits("w_shaped", PATH_A, window=30, quote_before=30), credits("u_shaped", PATH_A, window=30))
    # 2 touches, anchor = first: first .3 + anchor .3, last .3, rest .1 over both
    approx(credits("w_shaped", [("SEO", 50), ("Email", 1)], quote_before=20), {"SEO": .65, "Email": .35})


def test_lookback_windows():
    approx(credits("first_click", PATH_A, window=30), {"Google": 1})
    approx(credits("linear", PATH_A, window=30), {"Google": 1 / 3, "Email": 1 / 3, "Direct": 1 / 3})
    approx(credits("u_shaped", PATH_A, window=30), {"Google": .4, "Email": .2, "Direct": .4})
    approx(credits("last_non_direct", PATH_A, window=7), {"Email": 1})
    approx(credits("first_click", PATH_A, window=7), {"Email": 1})
    approx(credits("u_shaped", PATH_A, window=7), {"Email": .5, "Direct": .5})
    # boundary is inclusive: a touch exactly 30 days before the order is in the 30-day window
    approx(credits("first_click", [("Meta", 31), ("SEO", 30)], window=30), {"SEO": 1})
    # touches after the order never count
    approx(credits("last_click", [("Google", 3), ("Meta", -1)]), {"Google": 1})


@pytest.mark.parametrize("model", list(am.MODELS))
def test_edge_paths_every_model(model):
    approx(credits(model, [("TikTok", 12)]), {"TikTok": 1})                       # single touch
    approx(credits(model, [("Google", 100)], window=90), {"Direct": 1})           # nothing in the window
    approx(credits(model, [("Direct", 5), ("Direct", 1)]), {"Direct": 1})         # Direct only
    t = pd.DataFrame({"person_id": pd.Series([], dtype=int), "day": pd.Series([], dtype=float),
                      "channel": pd.Series([], dtype=str)})
    o = pd.DataFrame({"person_id": [7], "order_day": [ORDER_DAY], "quote_day": [np.nan]})
    approx({k: v for k, v in am.MODELS[model](t, o, 90).groupby("channel").credit.sum().items()}, {"Direct": 1})


def test_two_touch_u_shape_and_half_life_and_ties():
    approx(credits("u_shaped", [("Meta", 20), ("Google", 3)]), {"Meta": .5, "Google": .5})
    approx(credits("time_decay_7d", [("Meta", 7), ("Google", 0)]), {"Meta": 1 / 3, "Google": 2 / 3})
    approx(credits("time_decay_30d", [("Meta", 30), ("Google", 0)]), {"Meta": 1 / 3, "Google": 2 / 3})
    # same-day touches keep input order: the one listed later is the last click
    approx(credits("last_click", [("Meta", 2), ("Email", 2)]), {"Email": 1})
    approx(credits("first_click", [("Meta", 2), ("Email", 2)]), {"Meta": 1})


def test_last_non_direct_skips_direct_only():
    approx(credits("last_non_direct", [("Meta", 20), ("Direct", 3), ("Direct", 0.01)]), {"Meta": 1})
    approx(credits("last_click", [("Meta", 20), ("Direct", 3), ("Direct", 0.01)]), {"Direct": 1})


@pytest.mark.parametrize("model", list(am.MODELS))
def test_many_orders_each_sum_to_one(model):
    paths = [PATH_A, [("SEO", 3)], [("Direct", 1)], [("Google", 200)], [("Meta", 60), ("Meta", 30), ("Email", 1)]]
    ts, os_ = zip(*[toy(p, q, pid=i) for i, (p, q) in enumerate(zip(paths, [10, None, None, None, 45]))])
    c = am.MODELS[model](pd.concat(ts), pd.concat(os_), 90)
    per = c.groupby("person_id").credit.sum()
    assert len(per) == len(paths) and np.allclose(per, 1, atol=TOL)
    assert (c.credit >= 0).all()


# ============================================================ B. lift cap
def test_apply_cap_by_hand():
    p0 = np.array([0.5, 0.1])
    person = np.array([0, 0, 1])
    raw = np.array([0.3, 0.4, 0.2])               # person 0: 0.5 + 0.7 > 1 -> scale 0.5/0.7; person 1 unchanged
    lift, scale, uncapped = gj.apply_cap(p0, raw, person, 2)
    assert np.allclose(lift, [0.3 * 5 / 7, 0.4 * 5 / 7, 0.2])
    assert np.allclose(scale, [5 / 7, 1.0]) and np.allclose(uncapped, [1.2, 0.3])
    assert abs(p0[0] + lift[:2].sum() - 1) < TOL


@pytest.fixture(scope="module")
def capped_world():
    """A 1:50 sample with every raw lift multiplied by 40, so the cap binds for many people."""
    w = gj.build_world(n=5_000)
    gj.set_lifts(w, w["raw_lift"] * 40)
    return w


def test_cap_binds_and_holds(capped_world):
    w = capped_world
    tot = w["p0"] + np.bincount(w["t_person"], weights=w["lift"], minlength=w["n"])
    capped = w["uncapped_total"] > 1
    assert capped.sum() > 500                                   # the cap really is exercised
    assert tot.max() <= 1 + TOL
    assert np.allclose(tot[capped], 1, atol=TOL)                # capped people sit exactly at 1
    assert np.all(w["cap_scale"][~capped] == 1)                 # everyone else is untouched
    pos = w["raw_lift"] > 0                                     # same scale factor for all of a person's touches
    assert np.allclose(w["lift"][pos] / w["raw_lift"][pos], w["cap_scale"][w["t_person"][pos]])


def test_capped_world_reruns_stay_exact(capped_world):
    w = capped_world
    f = gj.simulate(w)
    truth = gj.true_effects(w, f)
    assert (truth.true_incremental_orders == truth.label_orders).all()
    assert truth.true_incremental_orders.sum() == f["buy"].sum()
    # a capped person's stretches fill [0, 1], so they always have a cause
    capped = w["uncapped_total"] > 1
    assert np.all(f["cause"][capped] > -2)


def test_default_world_cap_not_triggered(repo_root):
    key = (repo_root / gj.KEY_REL).read_text(encoding="utf-8")
    assert "People capped: 0 of 250,000" in key


# ============================================================ C. committed outputs
@pytest.fixture(scope="module")
def journeys():
    return am.load_journeys()


@pytest.fixture(scope="module")
def truth(repo_root):
    return pd.read_csv(repo_root / gj.TRUTH_REL).set_index("channel")


@pytest.mark.parametrize("view", ["observed", "full"])
@pytest.mark.parametrize("window", am.LOOKBACKS)
def test_credits_sum_to_orders_on_simulated_data(journeys, view, window):
    touches, orders = journeys
    t = am.observed(touches) if view == "observed" else touches
    for name, model in am.MODELS.items():
        c = model(t, orders, window)
        assert abs(c.credit.sum() - len(orders)) < 1e-6, name
        assert (c.credit >= 0).all(), name
        per = c.groupby("person_id").credit.sum()
        assert len(per) == len(orders) and np.allclose(per, 1, atol=1e-9), name
        assert set(c.channel) <= set(gj.ALL_TOUCH_CHANNELS), name


def test_untracked_orders_go_to_direct(journeys):
    touches, orders = journeys
    untracked = set(touches.loc[touches.tracked == 0, "person_id"])
    c = am.last_non_direct(am.observed(touches), orders, 90)
    assert (c[c.person_id.isin(untracked)].channel == "Direct").all()


def test_truth_matches_planted_ranking_and_size(truth, journeys):
    ch = gj.CHANNELS
    assert truth.true_incremental_orders.sum() == len(journeys[1])      # exact: channels + baseline == all orders
    assert list(truth.loc[ch].true_iroas.sort_values(ascending=False).index) == \
        sorted(ch, key=lambda c: -gj.PLANTED_IROAS[c])
    for c in ch:
        assert abs(truth.loc[c, "true_iroas"] / gj.PLANTED_IROAS[c] - 1) < 0.15, c
    assert 0.35 <= truth.loc["Direct_Other", "true_share_of_revenue"] <= 0.45
    assert abs(truth.true_share_of_orders.sum() - 1) < 1e-5            # file rounds to 6 decimals
    assert abs(truth.true_share_of_revenue.sum() - 1) < 1e-5


def test_spend_matches_csv_year1(repo_root):
    ev = pd.read_csv(repo_root / gj.EVENTS_REL, usecols=["channel", "cost_eur"], dtype={"channel": "category"})
    sim = ev.groupby("channel", observed=True).cost_eur.sum()
    csv = pd.read_csv(repo_root / gj.DATA_REL)
    y1 = csv[csv.week_start < "2025-10-27"]
    exp = y1[y1.channel.isin(gj.CHANNELS)].groupby("channel").spend_eur.sum()
    for c in gj.CHANNELS:
        assert abs(sim[c] - exp[c]) < 1.0, c                               # EUR, not just %: catches rounding bias
    assert sim.get("Direct", 0) == 0


def test_mix_lags_and_consent(repo_root, journeys):
    touches, orders = journeys
    assert abs((orders["product"] == "summer_house").mean() - 0.15) < 0.02
    csv = pd.read_csv(repo_root / gj.DATA_REL)
    y1 = csv[csv.week_start < "2025-10-27"].groupby("market").orders.sum()
    sim = orders.market.value_counts(normalize=True)
    for m in gj.MARKETS:
        assert abs(sim[m] - y1[m] / y1.sum()) < 0.02, m
    # lead path: quote before order, quote -> order at most 365 days; self-serve: no quote
    lead = orders[orders.path_type == "lead"]
    gap = lead.order_day - lead.quote_day
    assert gap.notna().all() and (gap > 0).all() and gap.max() <= 365
    assert orders.loc[orders.path_type == "self_serve", "quote_day"].isna().all()

    ev = pd.read_csv(repo_root / gj.EVENTS_REL, usecols=["event_id", "person_id", "market", "tracked", "day",
                                                         "event", "path_type", "true_cause_event_id"])
    # self-serve lag from the causing touch: log-normal median 31, truncated at 91 days
    pur = ev[(ev.event == "purchase") & (ev.path_type == "self_serve") & ev.true_cause_event_id.notna()]
    cause_day = ev.set_index("event_id").day.reindex(pur.true_cause_event_id.astype(int)).to_numpy()
    lag = pur.day.to_numpy() - cause_day
    assert lag.min() > 0 and lag.max() <= 91 and 28 <= np.median(lag) <= 34
    # consent loss per person, by market
    ppl = ev.drop_duplicates("person_id")
    for m, share in ppl.groupby("market").tracked.mean().items():
        assert abs((1 - share) - gj.CONSENT_LOSS[m]) < 0.015, m
    assert ev.groupby("person_id").tracked.nunique().max() == 1            # consent is per person


def test_every_purchase_has_a_true_cause(journeys):
    _, orders = journeys
    assert set(orders.true_cause_channel) <= set(gj.CHANNELS) | {"baseline"}


def test_comparison_csv_consistent(repo_root, truth, journeys):
    df = pd.read_csv(repo_root / "analysis" / "attribution_comparison.csv")
    n_orders = len(journeys[1])
    assert len(df) == 2 * len(am.MODELS) * len(am.LOOKBACKS) * 7
    sums = df.groupby(["view", "model", "lookback_days"]).credited_orders.sum()
    assert np.allclose(sums, n_orders, atol=1e-3)                        # 100% of orders, every combination
    assert np.allclose(df.groupby(["view", "model", "lookback_days"]).credit_share.sum(), 1, atol=1e-5)
    for ch, g in df.groupby("channel"):
        assert np.allclose(g.true_incremental_orders, truth.loc[ch, "true_incremental_orders"])
        assert np.allclose(g.spend_eur, truth.loc[ch, "spend_eur"], atol=0.01)
    paid = df[df.channel != "Direct_Other"]
    assert np.allclose(paid.model_roas, paid.credited_revenue_eur / paid.spend_eur, rtol=0, atol=1e-6)  # CSV: 6 dp
    assert (df.ga4_lookback_supported == (df.lookback_days <= 90)).all()


def test_campaign_types_add_up_to_channels(repo_root, journeys):
    touches, orders = journeys
    camp = am.campaign_types(touches, orders)
    df = pd.read_csv(repo_root / "analysis" / "attribution_comparison.csv")
    d = df[(df.view == "observed") & (df.lookback_days == 90)].set_index(["model", "channel"]).credit_share
    for ch in ["Google", "Meta"]:
        rows = [r for r in camp.index if r.startswith(ch)]
        for m in am.MODELS:
            assert abs(camp.loc[rows, m].sum() - d[(m, ch)]) < 1e-5, (ch, m)
        assert abs(camp.loc[rows, "TRUE"].sum() - df[df.channel == ch].true_share.iloc[0]) < 1e-5
    # the selection-bias mechanism shows at campaign-type level: brand over-credited by last click, generic under
    assert camp.loc["Google brand", "last_click"] > 2 * camp.loc["Google brand", "TRUE"]
    assert camp.loc["Google generic", "last_click"] < 0.5 * camp.loc["Google generic", "TRUE"]


# ---------------------------------------------------------------- cohorts (analysis/04_conversion_lag_cohorts.py)
_spec4 = importlib.util.spec_from_file_location("lag_cohorts", gj.REPO / "analysis" / "04_conversion_lag_cohorts.py")
cl = importlib.util.module_from_spec(_spec4)
_spec4.loader.exec_module(cl)


@pytest.fixture(scope="module")
def people():
    return cl.load_people()


def test_people_table(people, journeys):
    _, orders = journeys
    assert len(people) == gj.N_PEOPLE
    assert people.order_day.notna().sum() == len(orders)
    assert (people.lag_first.dropna() > 0).all()
    assert abs(people.spend_eur.sum() - pd.read_csv(gj.REPO / gj.TRUTH_REL).spend_eur.sum()) < 1


def test_cohort_curves(people):
    pooled, weekly = cl.first_click_cohorts(people)
    for frame in (pooled.T, weekly):
        assert (np.diff(frame.to_numpy(), axis=1) >= 0).all()              # cumulative: never decreasing
    c = people[cl.complete(people.first_week)]
    assert abs(pooled.loc[365, "all"] - (c.lag_first <= 365).sum() / len(c)) < 1e-12
    assert pooled.loc[180, "self_serve"] == pooled.loc[365, "self_serve"]   # self-serve lag <= 91 + journey <= 90
    q_pooled, _ = cl.quote_cohorts(people)
    assert (np.diff(q_pooled.to_numpy()) >= 0).all() and 0.22 < q_pooled[365] < 0.33
    assert (cl.complete(c.first_week)).all() and ((c.first_week + 1) * 7 + 365 <= cl.HORIZON_END_DAY).all()


def test_visible_share_and_cac(people):
    for by in ("first_channel", "true_cause"):
        v = cl.visible_share(people[people.true_cause.notna()] if by == "true_cause" else people, by)
        vals = v[cl.CHECKPOINTS[:-1]].to_numpy()
        assert ((vals >= 0) & (vals <= 1)).all() and (np.diff(vals, axis=1) >= 0).all()
    cac = cl.cac_by_horizon(people)
    assert cac.blended_cac_eur.is_monotonic_decreasing                       # more orders counted -> lower CAC
    assert cac.payback_ratio.is_monotonic_increasing
    assert abs(cac.loc[365, "blended_cac_eur"] - cac.loc[365, "spend_eur"] / cac.loc[365, "orders"]) < 1e-9


def test_output_file_sizes(repo_root):
    for rel in (gj.EVENTS_REL, gj.TRUTH_REL, gj.KEY_REL):
        assert (repo_root / rel).stat().st_size < 25e6, rel


# ============================================================ D. slow: regenerate -> identical outputs
def _sha_no_cr(fh):
    """SHA-256 of the content with line endings normalised: every \\r is dropped, so a file written on Windows
    (\\r\\n) and one written on Linux/Mac (\\n) hash the same. The data contains no other \\r."""
    h = hashlib.sha256()
    for chunk in iter(lambda: fh.read(1 << 20), b""):
        h.update(chunk.replace(b"\r", b""))
    return h.hexdigest()


def _gz_sha(path):
    with gzip.open(path, "rb") as fh:
        return _sha_no_cr(fh)


def _sha(path):
    with open(path, "rb") as fh:
        return _sha_no_cr(fh)


_SIZE_LINE = re.compile(r"^- `[^`]+`: [\d.]+ (MB|KB)$")      # e.g. "- `data/simulated_journeys.csv.gz`: 20.76 MB"


def _key_without_runtime(text):
    """Answer key without the lines that vary by machine: runtime, and file sizes (gzip output differs by
    platform / zlib version, and CSV size by line endings, even when the content is identical)."""
    return "\n".join(l for l in text.splitlines() if not l.startswith("- Runtime:") and not _SIZE_LINE.match(l))


@pytest.mark.slow
def test_regenerate_reproduces_outputs(repo_root, tmp_path, record_property):
    (tmp_path / "data").mkdir()
    (tmp_path / "docs").mkdir()
    shutil.copy(repo_root / "generate_journeys.py", tmp_path)
    shutil.copy(repo_root / gj.DATA_REL, tmp_path / "data")
    t0 = time.time()
    subprocess.run([sys.executable, "generate_journeys.py"], cwd=tmp_path, check=True, capture_output=True)
    runtime = time.time() - t0
    record_property("generate_journeys_runtime_s", round(runtime, 1))
    print(f"\ngenerate_journeys.py runtime: {runtime:.1f} s")
    assert runtime < 300
    assert _gz_sha(tmp_path / gj.EVENTS_REL) == _gz_sha(repo_root / gj.EVENTS_REL)
    assert _sha(tmp_path / gj.TRUTH_REL) == _sha(repo_root / gj.TRUTH_REL)
    assert _key_without_runtime((tmp_path / gj.KEY_REL).read_text(encoding="utf-8")) == \
        _key_without_runtime((repo_root / gj.KEY_REL).read_text(encoding="utf-8"))


# ============================================================ E. slow: full world in memory
@pytest.mark.slow
def test_full_world_truth(truth):
    w = gj.build_world()
    f = gj.simulate(w)
    t = gj.true_effects(w, f)
    assert (t.true_incremental_orders == t.label_orders).all()          # rerun difference == per-order labels
    assert np.allclose(t.true_incremental_revenue_eur, t.label_revenue_eur)
    assert t.true_incremental_orders.sum() == f["buy"].sum()             # baseline + channels == all orders
    t = t.set_index("channel")
    assert (t.true_incremental_orders == truth.true_incremental_orders).all()
    assert np.allclose(t.true_iroas.dropna(), truth.true_iroas.dropna(), rtol=1e-6)
    assert (w["uncapped_total"] <= 1).all()                              # default world: cap never binds
