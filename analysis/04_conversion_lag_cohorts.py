"""
Conversion-lag cohorts on the simulated user journeys (attribution extension).

ALL DATA IS SIMULATED (fictional brand "Nordvik Outdoor"). Spec: docs/attribution_extension_spec.md, section 5.
Input: data/simulated_journeys.csv.gz (written by generate_journeys.py).

  - Cumulative conversion by FIRST-CLICK week (orders / people) and by QUOTE week (orders / quote requests),
    read at 7, 30, 90, 180 and 365 days.
  - Per channel: share of a cohort's 365-day orders already visible at day 7 / 30 / 90 / 180, with the channel
    defined two ways: the first-click channel (what an analyst can see) and the true causing channel (truth).
  - Payback: blended CAC measured 30 vs 90 vs 365 days after the first click.

Conventions
  - The clock starts at the person's first touch (full paths: consent loss does not move the order date, and the
    lag question is separate from the tracking question). Quote cohorts start at the quote_request.
  - Only complete cohorts are used: the cohort's last day + 365 days must fall inside the data (ends 2026-10-25).
  - Blended CAC = all marketing spend on the cohort's touches / all orders (new customers) of the cohort
    (docs/metric_dictionary.md). Per-channel figures use true causing-channel orders: validation only.

Outputs: analysis/conversion_lag_cohorts.png, analysis/conversion_lag_results.txt
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
EVENTS_REL = "data/simulated_journeys.csv.gz"
PNG_OUT = "analysis/conversion_lag_cohorts.png"
TXT_OUT = "analysis/conversion_lag_results.txt"
HORIZON_END_DAY = (pd.Timestamp("2026-10-26") - pd.Timestamp("2024-10-28")).days    # as generate_journeys.py
ORIGIN = pd.Timestamp("2024-10-28")
CHECKPOINTS = [7, 30, 90, 180, 365]
CM_RATE = 0.55                                    # contribution margin before marketing (docs/assumptions.md)
CHANNELS = ["Google", "Meta", "Affiliates", "TikTok", "SEO", "Email", "Direct"]


# ---------------------------------------------------------------- data
def load_people(path: Path | str | None = None) -> pd.DataFrame:
    """One row per person: first touch (day, channel), quote, order, spend on their touches, path, true cause."""
    path = Path(path) if path else REPO / EVENTS_REL
    ev = pd.read_csv(path, usecols=["person_id", "day", "event", "channel", "cost_eur", "path_type",
                                    "order_value_eur", "true_cause_channel"],
                     dtype={"event": "category", "channel": "category", "path_type": "category",
                            "true_cause_channel": "category"})
    t = ev[ev.event == "touch"]
    first = t.loc[t.groupby("person_id").day.idxmin(), ["person_id", "day", "channel"]].set_index("person_id")
    p = pd.DataFrame({"first_day": first.day, "first_channel": first.channel.astype(str)})
    p["path_type"] = ev.groupby("person_id", observed=True).path_type.first().reindex(p.index).astype(str)
    p["spend_eur"] = t.groupby("person_id").cost_eur.sum().reindex(p.index).fillna(0.0)
    q = ev[ev.event == "quote_request"].groupby("person_id").day.min()
    p["quote_day"] = q.reindex(p.index)
    o = ev[ev.event == "purchase"].set_index("person_id")
    p["order_day"] = o.day.reindex(p.index)
    p["order_value_eur"] = o.order_value_eur.reindex(p.index)
    p["true_cause"] = o.true_cause_channel.astype(str).reindex(p.index)
    p["lag_first"] = p.order_day - p.first_day
    p["lag_quote"] = p.order_day - p.quote_day
    p["first_week"] = (p.first_day // 7).astype(int)
    p["quote_week"] = (p.quote_day // 7)
    # per-channel spend on the person's touches (for per-channel CAC)
    sp = t.groupby(["person_id", "channel"], observed=True).cost_eur.sum().unstack(fill_value=0.0)
    for c in CHANNELS[:-1]:
        p[f"spend_{c}"] = sp[c].reindex(p.index).fillna(0.0) if c in sp else 0.0
    return p.reset_index()


def complete(week: pd.Series) -> pd.Series:
    """Cohort week is complete if its last day + 365 days is inside the data."""
    return (week + 1) * 7 + 365 <= HORIZON_END_DAY


def week_start(w: int) -> str:
    return (ORIGIN + pd.Timedelta(days=7 * int(w))).date().isoformat()


# ---------------------------------------------------------------- analyses
def conversion_at(lags: pd.Series, n_base: int, days=CHECKPOINTS) -> pd.Series:
    """Cumulative conversion (orders with lag <= d) / base, at each checkpoint."""
    lags = lags.dropna()
    return pd.Series({d: float((lags <= d).sum()) / n_base for d in days})


def first_click_cohorts(p: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    c = p[complete(p.first_week)]
    pooled = pd.DataFrame({"all": conversion_at(c.lag_first, len(c))})
    for path in ["self_serve", "lead"]:
        s = c[c.path_type == path]
        pooled[path] = conversion_at(s.lag_first, len(s))
    weekly = c.groupby("first_week").apply(lambda g: conversion_at(g.lag_first, len(g)), include_groups=False)
    return pooled, weekly


def quote_cohorts(p: pd.DataFrame) -> tuple[pd.Series, pd.DataFrame]:
    q = p[p.quote_day.notna() & complete(p.quote_week.fillna(10 ** 6))]
    pooled = conversion_at(q.lag_quote, len(q))
    weekly = q.groupby("quote_week").apply(lambda g: conversion_at(g.lag_quote, len(g)), include_groups=False)
    return pooled, weekly


def visible_share(p: pd.DataFrame, by: str) -> pd.DataFrame:
    """Share of each channel's 365-day orders (complete first-click cohorts) visible by day 7/30/90/180."""
    c = p[complete(p.first_week) & (p.lag_first <= 365)]
    out = c.groupby(by).lag_first.apply(lambda s: pd.Series({d: (s <= d).mean() for d in CHECKPOINTS[:-1]})).unstack()
    out["orders_365d"] = c.groupby(by).size()
    return out


def cac_by_horizon(p: pd.DataFrame) -> pd.DataFrame:
    """Blended and per-channel CAC on complete first-click cohorts, measured d days after the first click."""
    c = p[complete(p.first_week)]
    spend = c.spend_eur.sum()
    rows = []
    for d in [30, 90, 365]:
        got = c.lag_first <= d
        orders = int(got.sum())
        aov = float(c.loc[got, "order_value_eur"].mean())
        cac = spend / orders
        row = {"horizon_days": d, "orders": orders, "spend_eur": spend, "blended_cac_eur": cac,
               "cm_per_order_eur": CM_RATE * aov, "payback_ratio": CM_RATE * aov / cac}
        for ch in CHANNELS[:-1]:
            n_ch = int((got & (c.true_cause == ch)).sum())
            row[f"cac_{ch}"] = c[f"spend_{ch}"].sum() / n_ch if n_ch else np.nan
        rows.append(row)
    return pd.DataFrame(rows).set_index("horizon_days")


# ---------------------------------------------------------------- chart
INK, INK2, MUTED = "#0b0b0b", "#52514e", "#898781"
GRID, AXIS, SURFACE, SERIES1 = "#e1e0d9", "#c3c2b7", "#fcfcfb", "#2a78d6"
COHORT_LINE = "#c3c2b7"
MIN_COHORT_FOR_LINE = 200
WINDOW_RAMP = {7: "#86b6ef", 30: "#3987e5", 90: "#1c5cab", 180: "#0d366b"}   # ordinal blue, steps 250-700


def _axes(ax):
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    ax.grid(color=GRID, linewidth=0.6)
    ax.set_axisbelow(True)


def _curve(ax, lags_by_cohort, pooled_lags, base_by_cohort, pooled_base, title, ylabel):
    from matplotlib.ticker import PercentFormatter
    x = np.arange(0, 366)
    for k, lags in lags_by_cohort.items():
        if base_by_cohort[k] < MIN_COHORT_FOR_LINE:                  # tiny cohorts are noise; still in the pooled curve
            continue
        s = np.sort(lags.dropna().to_numpy())
        ax.plot(x, np.searchsorted(s, x, side="right") / base_by_cohort[k], color=COHORT_LINE, linewidth=0.6, alpha=0.6)
    s = np.sort(pooled_lags.dropna().to_numpy())
    y = np.searchsorted(s, x, side="right") / pooled_base
    ax.plot(x, y, color=SERIES1, linewidth=2, zorder=3)
    for d in CHECKPOINTS:
        v = y[d]
        ax.scatter([d], [v], s=40, color=SERIES1, edgecolor=SURFACE, linewidth=1.2, zorder=4)
        ax.annotate(f"{v:.1%}", (d, v), textcoords="offset points", xytext=(4, -12), fontsize=8, color=INK2)
    ax.set_xticks(CHECKPOINTS)
    ax.set_xlim(0, 380)
    ax.yaxis.set_major_formatter(PercentFormatter(xmax=1, decimals=0))
    ax.set_xlabel("days since cohort start")
    ax.set_ylabel(ylabel)
    ax.set_title(title, loc="left", color=INK, fontsize=10, fontweight="bold")
    _axes(ax)


def _visible(ax, vis, order, title):
    from matplotlib.ticker import PercentFormatter
    vis = vis.reindex(order).dropna(how="all")
    ys = np.arange(len(vis))[::-1]
    for d in CHECKPOINTS[:-1]:
        ax.scatter(vis[d], ys, s=46, color=WINDOW_RAMP[d], edgecolor=SURFACE, linewidth=1.2, zorder=4,
                   label=f"by day {d}")
    ax.set_yticks(ys)
    ax.set_yticklabels(vis.index)
    ax.set_xlim(0, 1.02)
    ax.xaxis.set_major_formatter(PercentFormatter(xmax=1, decimals=0))
    ax.set_xlabel("share of the channel's 365-day orders already visible")
    ax.tick_params(axis="y", length=0)
    ax.set_title(title, loc="left", color=INK, fontsize=10, fontweight="bold")
    _axes(ax)
    ax.spines["left"].set_visible(False)


def chart(p, vis_first, vis_true, path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams.update({"font.family": ["Segoe UI", "DejaVu Sans"], "font.size": 9, "axes.edgecolor": AXIS,
                         "axes.labelcolor": INK2, "xtick.color": MUTED, "ytick.color": INK2,
                         "axes.facecolor": SURFACE, "figure.facecolor": SURFACE, "savefig.facecolor": SURFACE})
    fig, axes = plt.subplots(2, 2, figsize=(14, 9.5))
    c = p[complete(p.first_week)]
    _curve(axes[0, 0], {k: g.lag_first for k, g in c.groupby("first_week")}, c.lag_first,
           c.groupby("first_week").size(), len(c),
           "A. Orders per person, by first-click week", "cumulative conversion (orders / people)")
    q = p[p.quote_day.notna() & complete(p.quote_week.fillna(10 ** 6))]
    _curve(axes[0, 1], {k: g.lag_quote for k, g in q.groupby("quote_week")}, q.lag_quote,
           q.groupby("quote_week").size(), len(q),
           "B. Orders per quote request, by quote week", "cumulative conversion (orders / quotes)")
    _visible(axes[1, 0], vis_first, CHANNELS, "C. Share of orders visible, by first-click channel")
    order_true = [c_ for c_ in CHANNELS[:-1]] + ["baseline"]
    _visible(axes[1, 1], vis_true, order_true, "D. Share of orders visible, by true causing channel (validation only)")
    handles, labels = axes[1, 1].get_legend_handles_labels()
    fig.legend(handles, labels, loc="center", bbox_to_anchor=(0.5, 0.465), ncol=4, frameon=False, fontsize=9,
               labelcolor=INK2)
    fig.suptitle("A 30-day view misses most orders; lead-path orders keep arriving for a year", x=0.01, ha="left",
                 color=INK, fontsize=13, fontweight="bold")
    fig.text(0.01, 0.945, f"Complete cohorts only (365 days of follow-up). Grey lines: weekly cohorts with at least "
             f"{MIN_COHORT_FOR_LINE} people / quotes; blue: all cohorts pooled. Clock starts at the first click (A, C, D) "
             "or the quote request (B). Full paths. Simulated data, fictional brand.", color=INK2, fontsize=9.5)
    fig.tight_layout(rect=(0, 0, 1, 0.93), h_pad=4)
    fig.savefig(REPO / path, dpi=150)
    plt.close(fig)


# ---------------------------------------------------------------- text
def results_text(p, fc_pooled, fc_weekly, q_pooled, q_weekly, vis_first, vis_true, cac) -> str:
    c = p[complete(p.first_week)]
    q = p[p.quote_day.notna() & complete(p.quote_week.fillna(10 ** 6))]
    pct = lambda v: f"{v:.1%}"

    def table(frame, fmt, lw=16, w=11):
        head = f"{'':<{lw}}" + "".join(f"{str(col):>{w}}" for col in frame.columns)
        return "\n".join([head] + [f"{str(i):<{lw}}" + "".join(f"{fmt(v):>{w}}" for v in r) for i, r in frame.iterrows()])

    fc = fc_pooled.T.copy()
    fc.columns = [f"{d}d" for d in fc.columns]
    share = (fc_pooled / fc_pooled.loc[365]).T
    share.columns = [f"{d}d" for d in share.columns]
    wk = (fc_weekly[30] / fc_weekly[365])
    qs = pd.DataFrame({"conversion": q_pooled, "share_of_365d": q_pooled / q_pooled[365]}).T
    qs.columns = [f"{d}d" for d in qs.columns]
    vf = vis_first.reindex(CHANNELS).dropna(how="all").copy()        # Email is never a first click (needs a prior visit)
    vt = vis_true.reindex(CHANNELS[:-1] + ["baseline"]).copy()
    for v in (vf, vt):
        v.columns = [f"{x}d" if isinstance(x, (int, np.integer)) else x for x in v.columns]
    cac_t = cac[["orders", "blended_cac_eur", "cm_per_order_eur", "payback_ratio"]].T
    cac_t.columns = [f"{d}d" for d in cac_t.columns]
    ch_cac = cac[[f"cac_{ch}" for ch in CHANNELS[:-1]]].T
    ch_cac.index = CHANNELS[:-1]
    ch_cac.columns = [f"{d}d" for d in ch_cac.columns]
    ch_cac["30d/365d"] = ch_cac["30d"] / ch_cac["365d"]
    return f"""Conversion-lag cohorts (simulated journeys, fictional brand "Nordvik Outdoor")
Source: data/simulated_journeys.csv.gz. Complete cohorts only: last cohort day + 365 days inside the data (ends 2026-10-25).
First-click cohorts: weeks {week_start(c.first_week.min())} to {week_start(c.first_week.max())} ({c.first_week.nunique()} weeks, {len(c):,} people, {int(c.order_day.notna().sum()):,} orders).
Quote cohorts: weeks {week_start(q.quote_week.min())} to {week_start(q.quote_week.max())} ({q.quote_week.nunique()} weeks, {len(q):,} quote requests).

1. Cumulative conversion by first-click week (orders / people), pooled over complete cohorts
{table(fc, lambda v: f"{v:.2%}")}

   Share of the 365-day orders already visible
{table(share, pct)}
   Across weekly cohorts, the share visible at day 30 ranges from {wk.min():.1%} to {wk.max():.1%} (median {wk.median():.1%}).

2. Cumulative conversion by quote week (orders / quote requests), pooled
{table(qs, pct)}

3. Share of each channel's 365-day orders visible by day 7 / 30 / 90 / 180 (clock: first click)
   a) by first-click channel (what an analyst can see)
{table(vf, lambda v: f"{v:,.0f}" if v > 1.5 else pct(v), w=13)}
   b) by true causing channel (validation only; baseline = would have bought anyway)
{table(vt, lambda v: f"{v:,.0f}" if v > 1.5 else pct(v), w=13)}

4. Payback: blended CAC measured 30 / 90 / 365 days after the first click (complete cohorts)
   Spend on these cohorts' touches: EUR {cac.spend_eur.iloc[0]:,.0f}. Payback ratio = contribution margin per order (55%) / CAC.
{table(cac_t, lambda v: f"{v:,.2f}" if abs(v) < 100 else f"{v:,.0f}", lw=18, w=12)}

   Per-channel incremental CAC (channel spend / orders it truly caused by that day; validation only)
{table(ch_cac, lambda v: f"{v:,.2f}" if abs(v) < 100 else f"{v:,.0f}", lw=18, w=12)}

Notes
- Lags: self-serve orders arrive log-normal from the causing touch (median 31 days, truncated at 91 days); lead-path
  orders arrive after a quote_request with a tail of up to 365 days. Measured from the FIRST click, the median is
  longer ({p.loc[p.path_type == "self_serve", "lag_first"].median():.0f} days self-serve, {p.lag_first.median():.0f} overall, all orders), because the causing touch is often not the first one.
- The repo's weekly dataset truncates the lag at 91 days; the 365-day tail applies to the lead path in this extension only.
- GA4's maximum lookback window is 90 days.
"""


def main() -> None:
    p = load_people()
    fc_pooled, fc_weekly = first_click_cohorts(p)
    q_pooled, q_weekly = quote_cohorts(p)
    vis_first = visible_share(p, "first_channel")
    vis_true = visible_share(p[p.true_cause.notna()], "true_cause")
    cac = cac_by_horizon(p)
    chart(p, vis_first, vis_true, PNG_OUT)
    txt = results_text(p, fc_pooled, fc_weekly, q_pooled, q_weekly, vis_first, vis_true, cac)
    (REPO / TXT_OUT).write_text(txt, encoding="utf-8")
    print(txt)


if __name__ == "__main__":
    main()
