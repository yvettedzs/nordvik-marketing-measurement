"""
Attribution models on the simulated user journeys (attribution extension).

ALL DATA IS SIMULATED (fictional brand "Nordvik Outdoor"). Spec: docs/attribution_extension_spec.md.
Input: data/simulated_journeys.csv.gz (written by generate_journeys.py).

Every model has the same signature:   model(touches, orders, lookback_days) -> credits
  touches  person_id, day, channel           (one row per touch; ties keep input order)
  orders   person_id, order_day, quote_day   (quote_day NaN when there was no quote_request)
  credits  person_id, channel, credit        (each order hands out exactly 1.0 credit)

Conventions shared by all models
  - A touch is in the lookback window if 0 <= order_day - day <= lookback_days.
  - An order with no touch in the window gives its whole credit to Direct (as GA4 does).
  - "Direct" touches are ordinary touches, except in last_non_direct, which skips them
    (if only Direct touches are in the window, the credit stays with Direct).
  - Position models (U, W) use named roles. Each role's share goes to the touch holding it and adds up
    when one touch holds several roles; the "rest" share is split over the touches holding no role,
    or over all touches if every touch holds a role. So a 1-touch path gives 100%, a 2-touch U-shaped
    path 50/50.
  - W-shaped: roles first 30%, lead 30%, last 30%, rest 10%. The lead anchor is the last touch at or before
    the quote_request. With no quote (self-serve) or no touch in the window before it, W falls back to U.
  - S-shape is not implemented: it is mentioned in practice, but no standard definition was found.
  - GA4's maximum lookback window is 90 days; 365 days is shown for comparison only.

Not in this version: a data-driven proxy (Markov removal effect). Listed as a next step in the findings.
"""
from __future__ import annotations

from functools import partial
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
EVENTS_REL = "data/simulated_journeys.csv.gz"
DIRECT = "Direct"
LOOKBACKS = [7, 30, 90, 365]
GA4_MAX_LOOKBACK = 90


# ---------------------------------------------------------------- data
def load_journeys(path: Path | str | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Buyer touches and orders from the event file. Touches keep `tracked` and `navigational` so the caller
    can choose the observed view (tracked == 1) or the full view (all touches)."""
    path = Path(path) if path else REPO / EVENTS_REL
    ev = pd.read_csv(path, usecols=["event_id", "person_id", "market", "path_type", "tracked", "day", "event",
                                    "channel", "campaign_type", "navigational", "product", "order_value_eur",
                                    "true_cause_channel", "true_cause_event_id"],
                     dtype={"market": "category", "path_type": "category", "event": "category",
                            "channel": "category", "campaign_type": "category", "product": "category",
                            "true_cause_channel": "category", "tracked": "int8", "navigational": "int8"})
    pur = ev[ev.event == "purchase"]
    orders = pd.DataFrame({"person_id": pur.person_id.to_numpy(), "order_day": pur.day.to_numpy(),
                           "order_value_eur": pur.order_value_eur.to_numpy(), "market": pur.market.to_numpy(),
                           "path_type": pur.path_type.to_numpy(), "product": pur["product"].to_numpy(),
                           "true_cause_channel": pur.true_cause_channel.astype(str).to_numpy()})
    q = ev[ev.event == "quote_request"].groupby("person_id").day.min()
    orders["quote_day"] = q.reindex(orders.person_id).to_numpy()
    buyers = ev.person_id.isin(orders.person_id)
    t = ev[(ev.event == "touch") & buyers]
    touches = pd.DataFrame({"event_id": t.event_id.to_numpy(), "person_id": t.person_id.to_numpy(),
                            "day": t.day.to_numpy(), "channel": t.channel.astype(str).to_numpy(),
                            "campaign_type": t.campaign_type.astype(str).to_numpy(),
                            "tracked": t.tracked.to_numpy(), "navigational": t.navigational.to_numpy()})
    # campaign type of the causing touch (truth; the causing touch always precedes the order, so it is in `touches`)
    ct = touches.set_index("event_id").campaign_type
    cause_eid = pur.true_cause_event_id.to_numpy()
    orders["true_cause_campaign_type"] = np.where(
        np.isnan(cause_eid), "baseline", ct.reindex(np.nan_to_num(cause_eid, nan=-1).astype(int)).to_numpy())
    return touches, orders


def observed(touches: pd.DataFrame) -> pd.DataFrame:
    """What an analytics tool sees: touches of people who gave consent (per-person consent loss)."""
    return touches[touches.tracked == 1]


# ---------------------------------------------------------------- shared helpers
def _paths(touches: pd.DataFrame, orders: pd.DataFrame, lookback_days: float) -> pd.DataFrame:
    o = orders[["person_id", "order_day"]].copy()
    o["quote_day"] = orders["quote_day"] if "quote_day" in orders else np.nan
    p = touches[["person_id", "day", "channel"]].merge(o, on="person_id", how="inner")
    p["age"] = p.order_day - p.day
    p = p[(p.age >= 0) & (p.age <= lookback_days)]
    p = p.sort_values(["person_id", "day"], kind="stable").reset_index(drop=True)
    g = p.groupby("person_id", sort=False)
    p["pos"] = g.cumcount()
    p["n"] = g.day.transform("size")
    return p


def _finish(p: pd.DataFrame, weight: np.ndarray | pd.Series, orders: pd.DataFrame) -> pd.DataFrame:
    """Normalise weights per order, add Direct for orders without credited touches, sum by channel."""
    p = p.assign(w=np.asarray(weight, dtype=float))
    p = p[p.w > 0]
    tot = p.groupby("person_id").w.transform("sum")
    c = pd.DataFrame({"person_id": p.person_id.to_numpy(), "channel": p.channel.to_numpy(),
                      "credit": (p.w / tot).to_numpy()})
    missing = np.setdiff1d(orders.person_id.to_numpy(), c.person_id.unique())
    c = pd.concat([c, pd.DataFrame({"person_id": missing, "channel": DIRECT, "credit": 1.0})], ignore_index=True)
    return c.groupby(["person_id", "channel"], as_index=False, sort=True).credit.sum()


def _roles(p: pd.DataFrame, roles: list[tuple[np.ndarray, float]], rest: float) -> np.ndarray:
    w = np.zeros(len(p))
    has_role = np.zeros(len(p), dtype=bool)
    for mask, share in roles:
        w += np.where(mask, share, 0.0)
        has_role |= mask
    pid = p.person_id.to_numpy()
    n_free = pd.Series(~has_role).groupby(pid).transform("sum").to_numpy()
    n_all = p.n.to_numpy()
    w += np.where(n_free > 0, np.where(~has_role, rest / np.maximum(n_free, 1), 0.0), rest / n_all)
    return w


# ---------------------------------------------------------------- models
def last_click(touches, orders, lookback_days):
    p = _paths(touches, orders, lookback_days)
    return _finish(p, p.pos == p.n - 1, orders)


def last_non_direct(touches, orders, lookback_days):
    """GA4 'paid and organic last click': the last non-Direct touch; Direct only if nothing else is in the window."""
    p = _paths(touches[touches.channel != DIRECT], orders, lookback_days)
    return _finish(p, p.pos == p.n - 1, orders)


def first_click(touches, orders, lookback_days):
    p = _paths(touches, orders, lookback_days)
    return _finish(p, p.pos == 0, orders)


def linear(touches, orders, lookback_days):
    p = _paths(touches, orders, lookback_days)
    return _finish(p, np.ones(len(p)), orders)


def time_decay(touches, orders, lookback_days, half_life_days: float = 7.0):
    """Weight 2^(-age / half_life), age = days between touch and order, normalised per order."""
    p = _paths(touches, orders, lookback_days)
    return _finish(p, 0.5 ** (p.age / half_life_days), orders)


def u_shaped(touches, orders, lookback_days):
    p = _paths(touches, orders, lookback_days)
    first, last = (p.pos == 0).to_numpy(), (p.pos == p.n - 1).to_numpy()
    return _finish(p, _roles(p, [(first, 0.4), (last, 0.4)], 0.2), orders)


def w_shaped(touches, orders, lookback_days):
    p = _paths(touches, orders, lookback_days)
    first, last = (p.pos == 0).to_numpy(), (p.pos == p.n - 1).to_numpy()
    before_q = p.day <= p.quote_day                               # False when quote_day is NaN
    anchor_pos = p[before_q].groupby("person_id").pos.max()
    ap = p.person_id.map(anchor_pos)
    has_anchor = ap.notna().to_numpy()
    anchor = (p.pos == ap).to_numpy() & has_anchor
    w_w = _roles(p, [(first, 0.3), (anchor, 0.3), (last, 0.3)], 0.1)
    w_u = _roles(p, [(first, 0.4), (last, 0.4)], 0.2)
    return _finish(p, np.where(has_anchor, w_w, w_u), orders)


MODELS = {
    "last_click": last_click,
    "last_non_direct": last_non_direct,
    "first_click": first_click,
    "linear": linear,
    "time_decay_7d": partial(time_decay, half_life_days=7.0),
    "time_decay_30d": partial(time_decay, half_life_days=30.0),
    "u_shaped": u_shaped,
    "w_shaped": w_shaped,
}


def credit_by_channel(credits: pd.DataFrame) -> pd.Series:
    return credits.groupby("channel").credit.sum()


# ================================================================ runner: all models x windows -> CSV, charts, text
CHANNELS = ["Google", "Meta", "Affiliates", "TikTok", "SEO", "Email"]
OUT_CHANNELS = CHANNELS + ["Direct_Other"]            # model credit to Direct is compared with the baseline truth
TRUTH_REL = "data/journey_truth_by_channel.csv"
CSV_OUT = "analysis/attribution_comparison.csv"
TXT_OUT = "analysis/attribution_results.txt"
PNG_MODELS = "analysis/attribution_by_model.png"
PNG_WINDOWS = "analysis/attribution_by_window.png"
VIEWS = ["observed", "full"]
LABELS = {"last_click": "Last click", "last_non_direct": "Last non-direct", "first_click": "First click",
          "linear": "Linear", "time_decay_7d": "Time decay (7d half-life)",
          "time_decay_30d": "Time decay (30d half-life)", "u_shaped": "U-shaped 40/20/40",
          "w_shaped": "W-shaped 30/30/30+10"}


def compare(touches: pd.DataFrame, orders: pd.DataFrame, truth: pd.DataFrame) -> pd.DataFrame:
    value = orders.set_index("person_id").order_value_eur
    n_orders, revenue = len(orders), float(value.sum())
    rows = []
    for view in VIEWS:
        t = observed(touches) if view == "observed" else touches
        for name, model in MODELS.items():
            for lb in LOOKBACKS:
                c = model(t, orders, lb)
                c["channel"] = c.channel.replace({DIRECT: "Direct_Other"})
                c["rev"] = c.credit * value.reindex(c.person_id).to_numpy()
                g = c.groupby("channel")[["credit", "rev"]].sum().reindex(OUT_CHANNELS, fill_value=0.0)
                for ch in OUT_CHANNELS:
                    tr = truth.loc[ch]
                    spend = float(tr.spend_eur)
                    rows.append(dict(
                        view=view, model=name, lookback_days=lb, ga4_lookback_supported=lb <= GA4_MAX_LOOKBACK,
                        channel=ch, credited_orders=g.loc[ch, "credit"], credit_share=g.loc[ch, "credit"] / n_orders,
                        credited_revenue_eur=g.loc[ch, "rev"], credited_revenue_share=g.loc[ch, "rev"] / revenue,
                        spend_eur=spend, model_roas=g.loc[ch, "rev"] / spend if spend > 0 else np.nan,
                        true_incremental_orders=float(tr.true_incremental_orders),
                        true_share=float(tr.true_share_of_orders),
                        true_incremental_revenue_eur=float(tr.true_incremental_revenue_eur),
                        true_iroas=float(tr.true_iroas) if spend > 0 else np.nan,
                        credit_to_true_ratio=g.loc[ch, "credit"] / float(tr.true_incremental_orders)))
    out = pd.DataFrame(rows)
    sums = out.groupby(["view", "model", "lookback_days"]).credited_orders.sum()
    assert np.allclose(sums, n_orders), "credits must add up to 100% of orders"
    return out


CAMPAIGN_ROWS = ["Google brand", "Google generic", "Meta prospecting", "Meta retargeting"]


def campaign_types(touches: pd.DataFrame, orders: pd.DataFrame, lookback_days: int = 90) -> pd.DataFrame:
    """Credit share vs true share for Google brand/generic and Meta prospecting/retargeting (observed paths).
    Paid navigational brand clicks count as Google brand. Truth = orders whose causing touch had that campaign type
    (exact: the reruns are additive, so a sub-channel's removal effect equals its per-order labels)."""
    t = observed(touches).copy()
    split = t.channel.isin(["Google", "Meta"])
    t.loc[split, "channel"] = t.loc[split, "channel"] + " " + t.loc[split, "campaign_type"]
    n = len(orders)
    out = {name: model(t, orders, lookback_days).groupby("channel").credit.sum().reindex(CAMPAIGN_ROWS).fillna(0) / n
           for name, model in MODELS.items()}
    key = orders.true_cause_channel + " " + orders.true_cause_campaign_type
    out["TRUE"] = key.value_counts().reindex(CAMPAIGN_ROWS).fillna(0) / n
    return pd.DataFrame(out)


# ---------------------------------------------------------------- charts (matplotlib, static PNG)
INK, INK2, MUTED = "#0b0b0b", "#52514e", "#898781"
GRID, AXIS, SURFACE, SERIES1 = "#e1e0d9", "#c3c2b7", "#fcfcfb", "#2a78d6"
WINDOW_RAMP = {7: "#86b6ef", 30: "#3987e5", 90: "#1c5cab", 365: "#0d366b"}   # ordinal blue, steps 250-700


def _style(plt):
    plt.rcParams.update({"font.family": ["Segoe UI", "DejaVu Sans"], "font.size": 9,
                         "axes.edgecolor": AXIS, "axes.labelcolor": INK2, "xtick.color": MUTED,
                         "ytick.color": INK2, "axes.facecolor": SURFACE, "figure.facecolor": SURFACE,
                         "savefig.facecolor": SURFACE})


def _panel(ax, ch, sub, models, colors_by, show_y):
    ys = np.arange(len(models))[::-1]
    true = sub.true_share.iloc[0]
    xmax = max(sub.credit_share.max(), true) * 1.18
    ax.set_xlim(0, xmax)
    ax.set_ylim(-0.7, len(models) - 0.3)
    ax.grid(axis="x", color=GRID, linewidth=0.6)
    ax.set_axisbelow(True)
    for s in ("top", "right", "left"):
        ax.spines[s].set_visible(False)
    ax.tick_params(axis="y", length=0)
    ax.axvline(true, color=INK, linewidth=2, zorder=3)
    for key, color, label in colors_by:
        d = sub[key(sub)].set_index("model").reindex(models)
        ax.scatter(d.credit_share, ys, s=46, color=color, edgecolor=SURFACE, linewidth=1.2, zorder=4, label=label)
    ax.set_yticks(ys)
    ax.set_yticklabels([LABELS[m] for m in models] if show_y else [])
    from matplotlib.ticker import MultipleLocator, PercentFormatter
    step = next(s for s in (0.01, 0.02, 0.05, 0.10, 0.20, 0.25) if xmax / s <= 6)   # whole percentages only
    ax.xaxis.set_major_locator(MultipleLocator(step))
    ax.xaxis.set_major_formatter(PercentFormatter(xmax=1, decimals=0))
    ax.set_title(f"{ch}   true {true:.1%}", loc="left", color=INK, fontsize=10, fontweight="bold")


def chart_by_model(df, path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    _style(plt)
    d = df[(df.view == "observed") & (df.lookback_days == 90)]
    models = list(MODELS)
    fig, axes = plt.subplots(2, 4, figsize=(15, 7.2))
    for i, ch in enumerate(OUT_CHANNELS):
        ax = axes.flat[i]
        _panel(ax, ch, d[d.channel == ch], models, [(lambda s: slice(None), SERIES1, "Model credit share")],
               show_y=(i % 4 == 0))
    ax = axes.flat[7]
    ax.axis("off")
    ax.scatter([], [], s=46, color=SERIES1, label="Credit share under the model")
    ax.plot([], [], color=INK, linewidth=2, label="True incremental share (counterfactual reruns)")
    ax.legend(loc="upper left", frameon=False, fontsize=9, labelcolor=INK2)
    ax.text(0, 0.55, "Observed paths (after per-person consent loss), 90-day lookback (GA4 maximum).\n"
                     "Each panel has its own scale. Direct_Other = Direct touches + orders\n"
                     "with no tracked touch, compared with the baseline (would buy anyway).\n"
                     "70% of orders have a zero-lift navigational session just before\n"
                     "purchase: a design choice that drives the last-click results.\n"
                     "Simulated data, fictional brand.", transform=ax.transAxes, va="top", color=MUTED, fontsize=8.5)
    fig.suptitle("Attribution models disagree with each other and with incrementality", x=0.01, ha="left",
                 color=INK, fontsize=13, fontweight="bold")
    fig.text(0.01, 0.935, "Share of orders credited to each channel, by model, vs the true incremental share (black line)",
             color=INK2, fontsize=10)
    fig.tight_layout(rect=(0, 0, 1, 0.92))
    fig.savefig(REPO / path, dpi=150)
    plt.close(fig)


def chart_by_window(df, path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    _style(plt)
    d = df[df.view == "observed"]
    models = list(MODELS)
    fig, axes = plt.subplots(2, 4, figsize=(15, 7.2))
    series = [((lambda s, lb=lb: s.lookback_days == lb), WINDOW_RAMP[lb], f"{lb}-day lookback") for lb in LOOKBACKS]
    for i, ch in enumerate(OUT_CHANNELS):
        _panel(axes.flat[i], ch, d[d.channel == ch], models, series, show_y=(i % 4 == 0))
    ax = axes.flat[7]
    ax.axis("off")
    for _, color, label in series:
        ax.scatter([], [], s=46, color=color, label=label)
    ax.plot([], [], color=INK, linewidth=2, label="True incremental share")
    ax.legend(loc="upper left", frameon=False, fontsize=9, labelcolor=INK2)
    ax.text(0, 0.38, "Observed paths. GA4's maximum lookback is 90 days;\n365 days is shown for comparison only.\n"
                     "Each panel has its own scale. Simulated data, fictional brand.",
            transform=ax.transAxes, va="top", color=MUTED, fontsize=8.5)
    fig.suptitle("Shorter lookback windows move credit to Direct and to late-funnel touches", x=0.01, ha="left",
                 color=INK, fontsize=13, fontweight="bold")
    fig.text(0.01, 0.935, "Share of orders credited to each channel, by model and lookback window, vs the true incremental share",
             color=INK2, fontsize=10)
    fig.tight_layout(rect=(0, 0, 1, 0.92))
    fig.savefig(REPO / path, dpi=150)
    plt.close(fig)


# ---------------------------------------------------------------- results text
def results_text(df: pd.DataFrame, n_orders: int, camp: pd.DataFrame) -> str:
    obs90 = df[(df.view == "observed") & (df.lookback_days == 90)]
    share = obs90.pivot(index="channel", columns="model", values="credit_share").reindex(OUT_CHANNELS)[list(MODELS)]
    true = obs90.groupby("channel").true_share.first().reindex(OUT_CHANNELS)
    ratio = obs90.pivot(index="channel", columns="model", values="credit_to_true_ratio").reindex(OUT_CHANNELS)[list(MODELS)]
    sens = pd.DataFrame({"true": true, "min": share.min(axis=1), "max": share.max(axis=1),
                         "ratio_min": ratio.min(axis=1), "ratio_max": ratio.max(axis=1)})
    sens["range_pp"] = (sens["max"] - sens["min"]) * 100
    sens["max_over_min"] = sens["max"] / sens["min"]
    sens = sens.sort_values("max_over_min", ascending=False)

    def table(frame, fmt):
        cols = list(frame.columns)
        width = max(11, max(len(str(c)) for c in cols) + 2)
        lw = max(14, max(len(str(i)) for i in frame.index) + 2)
        head = f"{'':<{lw}}" + "".join(f"{c:>{width}}" for c in cols)
        return "\n".join([head] + [f"{i:<{lw}}" + "".join(f"{fmt(v):>{width}}" for v in r) for i, r in frame.iterrows()])

    short = {"last_click": "last", "last_non_direct": "last_nd", "first_click": "first", "linear": "linear",
             "time_decay_7d": "decay_7d", "time_decay_30d": "decay_30d", "u_shaped": "U", "w_shaped": "W"}
    hs = share.rename(columns=short).assign(TRUE=true)
    roas = obs90[obs90.channel != "Direct_Other"].pivot(index="channel", columns="model", values="model_roas") \
        .reindex(CHANNELS)[list(MODELS)].rename(columns=short)
    roas["TRUE_iROAS"] = obs90[obs90.channel != "Direct_Other"].groupby("channel").true_iroas.first().reindex(CHANNELS)
    lnd = df[(df.view == "observed") & (df.model == "last_non_direct")].pivot(
        index="channel", columns="lookback_days", values="credit_share").reindex(OUT_CHANNELS)
    lnd.columns = [f"{c}d" for c in lnd.columns]
    lnd["TRUE"] = true
    cons = df[(df.model == "last_non_direct") & (df.lookback_days == 90)].pivot(
        index="channel", columns="view", values="credit_share").reindex(OUT_CHANNELS)[["full", "observed"]]
    cons["TRUE"] = true
    pct = lambda v: f"{v:.1%}"
    camp_s = camp.rename(columns=short)
    camp_r = camp[list(MODELS)].div(camp["TRUE"], axis=0).rename(columns=short)
    return f"""Attribution models vs counterfactual truth (simulated journeys, fictional brand "Nordvik Outdoor")
Source: data/simulated_journeys.csv.gz, truth from data/journey_truth_by_channel.csv. Orders: {n_orders:,}.
Observed paths = after per-person consent loss (DE/AT 30%, FR/NL 20%, UK 15%, SE 10%).
Direct_Other = credit to Direct touches + orders with no tracked touch in the window; truth = baseline orders.

1. Credit share of orders by model (observed paths, 90-day lookback) vs true incremental share
{table(hs, pct)}

2. Model sensitivity (observed, 90-day): spread of credit share across the 8 model variants, most sensitive first
{table(sens[["true", "min", "max", "range_pp", "max_over_min", "ratio_min", "ratio_max"]], lambda v: f"{v:.2f}" if abs(v) >= 1 or v == 0 else f"{v:.3f}")}
   (ratio = credited orders / true incremental orders; 1.00 = the model matches the truth)

3. Model ROAS (credited revenue / spend; observed, 90-day) vs true iROAS
{table(roas, lambda v: f"{v:.2f}")}

4. Last non-direct click by lookback window (observed): credit share
{table(lnd, pct)}

5. Consent loss (last non-direct, 90-day): full paths vs observed paths
{table(cons, pct)}

6. Campaign types (observed, 90-day): attribution errs in both directions; channel totals can hide sub-channel bias
   Credit share of orders (paid navigational brand clicks count as Google brand) vs true share
{table(camp_s, pct)}
   Credited / true
{table(camp_r, lambda v: f"{v:.2f}")}

Notes
- Every model hands out exactly 1.0 credit per order (checked for all {len(MODELS)} variants x {len(LOOKBACKS)} windows x 2 views).
- GA4's maximum lookback window is 90 days; 365 days is shown for comparison only.
- S-shape is mentioned in practice, but no standard definition was found, so it is not implemented.
- W-shaped falls back to U-shaped when there is no quote_request touch in the window (all self-serve orders).
- 70% of orders have a zero-lift navigational session (Direct 45%, Google brand 30%, SEO 15%, Email 10%) just
  before purchase. This is a design choice of the simulation and it drives the last-click results.
- Not in this version: a data-driven proxy (Markov removal effect). Next step.
"""


def main() -> None:
    touches, orders = load_journeys()
    truth = pd.read_csv(REPO / TRUTH_REL).set_index("channel")
    df = compare(touches, orders, truth)
    df.round(6).to_csv(REPO / CSV_OUT, index=False)
    chart_by_model(df, PNG_MODELS)
    chart_by_window(df, PNG_WINDOWS)
    txt = results_text(df, len(orders), campaign_types(touches, orders))
    (REPO / TXT_OUT).write_text(txt, encoding="utf-8")
    print(txt)


if __name__ == "__main__":
    main()
