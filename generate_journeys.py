"""
Attribution extension, step 1: user-level journey simulation with a counterfactual "truth".

ALL DATA IS SIMULATED (fictional brand "Nordvik Outdoor").
Spec: docs/attribution_extension_spec.md.  Business assumptions: docs/assumptions.md.

How the truth is created (common random numbers, exact additivity)
  Each person draws one uniform U once. On the line [0, 1]:
    [0, p0)                      belongs to the baseline (would buy anyway: brand, direct, word of mouth)
    then, in time order, each touch k owns the next stretch of length lift_k.
  The person buys if U falls in any stretch; that stretch is the TRUE CAUSE. The order date is the
  cause's time plus a lag that was drawn in advance. A counterfactual rerun deletes one channel's
  stretches WITHOUT moving the others (same U, same lags), so P(buy) = p0 + sum of remaining lifts, and
  the orders lost are exactly the buyers whose U fell in that channel's stretches.

Lift cap: if p0 + sum(lifts) > 1 for a person, all of that person's touch lifts are scaled by the same
  factor so that p0 + sum(lifts) = 1 exactly. Done before the stretches are laid out; reported in the key.

Cohort: first touches in the first 52 weeks of the repo (2024-10-28 to 2025-10-26); every order is
  followed to the end of the repo's data (2026-10-25). Orders later than that are censored, in the
  factual and in every counterfactual alike.

Outputs
  data/simulated_journeys.csv.gz       event table: touch, quote_request, purchase (+ true_* columns)
  data/journey_truth_by_channel.csv    true incremental orders / revenue / iROAS per channel (from reruns)
  docs/answer_key_attribution.md       parameters, truth table, calibration check
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.special import expit, ndtr, ndtri

REPO = Path(__file__).resolve().parent
DATA_REL = "data/simulated_weekly_data.csv"
EVENTS_REL = "data/simulated_journeys.csv.gz"
TRUTH_REL = "data/journey_truth_by_channel.csv"
KEY_REL = "docs/answer_key_attribution.md"

SEED = 42
N_PEOPLE = 250_000
ORIGIN = pd.Timestamp("2024-10-28")                          # day 0 = first Monday of the repo data
N_ACQ_WEEKS = 52                                             # first touches in weeks 1-52
HORIZON_END_DAY = (pd.Timestamp("2026-10-26") - ORIGIN).days  # exclusive: data ends Sunday 2026-10-25
JOURNEY_DAYS = 90                                            # later touches fall within 90 days of entry

# ---------------------------------------------------------------- repo assumptions (copied from generate_data.py)
MARKETS = ["DE", "AT", "FR", "NL", "UK", "SE"]
VAT = np.array([0.19, 0.20, 0.20, 0.21, 0.20, 0.25])
PRICE_OF, PRICE_SH = 3500.0, 9000.0                          # incl. VAT
CHANNELS = ["Google", "Meta", "Affiliates", "TikTok", "SEO", "Email"]
DIRECT = "Direct"                                            # non-marketing touches: zero lift, no cost
ALL_TOUCH_CHANNELS = CHANNELS + [DIRECT]
PLANTED_IROAS = {"Google": 3.6, "Meta": 1.5, "Affiliates": 3.0, "TikTok": 0.7, "SEO": 4.8, "Email": 12.0}
CONSENT_LOSS = {"DE": 0.30, "AT": 0.30, "FR": 0.20, "NL": 0.20, "UK": 0.15, "SE": 0.10}   # per PERSON

# ---------------------------------------------------------------- journey design parameters
P0_SIGMA = 1.3                     # baseline propensity p0 = expit(a + P0_SIGMA * z); `a` calibrated
FREQ_DECAY = 0.7                   # j-th touch of the same channel adds FREQ_DECAY**(j-1) of the first's lift
LEAD_SHARE = 0.15 + 0.85 * 0.11    # lead path: all summer houses + 11% of outdoor furniture
SH_SHARE_OF_LEAD = 0.15 / LEAD_SHARE
LEAD_TO_ORDER_TARGET = 0.27        # share of quote requests that end in an order (sets non-buyer quote rate)
LAG_SELF = (31.0, 0.65, 91.0)      # median, sigma, cap (days): causing touch -> order (as in generate_data.py)
LAG_QUOTE = (7.0, 0.8, 60.0)       # lead path: causing touch -> quote_request
LAG_LEAD = (60.0, 1.0, 365.0)      # lead path: quote_request -> order (long tail up to 365 days)
TIMING = {"upper": (1.0, 2.5), "lower": (2.0, 2.0)}   # offset after entry = JOURNEY_DAYS * Beta(a, b)


@dataclass(frozen=True)
class TouchType:
    channel: str
    campaign_type: str
    mu: float        # mean extra touches per person
    gamma: float     # selection on propensity: touches ~ Poisson(mu * exp(gamma*z - gamma^2/2))
    timing: str


TOUCH_TYPES = [
    TouchType("Google", "generic", 0.9, 0.15, "upper"),
    TouchType("Google", "brand", 0.5, 0.80, "lower"),
    TouchType("Meta", "prospecting", 0.8, 0.00, "upper"),
    TouchType("Meta", "retargeting", 0.6, 0.70, "lower"),
    TouchType("Affiliates", "affiliate", 0.3, 0.50, "lower"),
    TouchType("TikTok", "prospecting", 0.4, 0.00, "upper"),
    TouchType("SEO", "organic", 0.6, 0.30, "upper"),
    TouchType("Email", "newsletter", 0.5, 0.80, "lower"),
    TouchType(DIRECT, "direct", 0.8, 0.80, "lower"),
]
TT_KEY = {(t.channel, t.campaign_type): i for i, t in enumerate(TOUCH_TYPES)}
ENTRY_MIX = {("Google", "generic"): 0.30, ("Meta", "prospecting"): 0.20, ("TikTok", "prospecting"): 0.10,
             ("SEO", "organic"): 0.20, (DIRECT, "direct"): 0.15, ("Affiliates", "affiliate"): 0.05}
# zero-lift "navigational" session at the moment of purchase (observed paths only; paid ones cost money)
NAV_PROB = 0.70
NAV_MIX = {(DIRECT, "direct"): 0.45, ("Google", "brand"): 0.30, ("SEO", "organic"): 0.15, ("Email", "newsletter"): 0.10}
NAV_OFFSET_DAYS = 0.01             # navigational session ~15 minutes before the order


def trunc_lognormal(u, median, sigma, cap):
    """Inverse-CDF draw from a log-normal truncated at `cap` (keeps common random numbers)."""
    u = np.clip(u, 1e-12, 1 - 1e-12)
    return np.exp(np.log(median) + sigma * ndtri(u * ndtr((np.log(cap) - np.log(median)) / sigma)))


def _mix(d):
    keys = list(d)
    return np.array([TT_KEY[k] for k in keys]), np.array([d[k] for k in keys]) / sum(d.values())


# ---------------------------------------------------------------- world (all random draws happen here, once)
def build_world(seed: int = SEED, n: int = N_PEOPLE) -> dict:
    rng = np.random.default_rng(seed)
    csv = pd.read_csv(REPO / DATA_REL, parse_dates=["week_start"])
    weeks = np.sort(csv.week_start.unique())[:N_ACQ_WEEKS]
    assert pd.Timestamp(weeks[0]) == ORIGIN
    y1 = csv[csv.week_start.isin(weeks)]
    paid = y1[y1.channel.isin(CHANNELS)]
    spend_mc = paid.pivot_table(index="market", columns="channel", values="spend_eur", aggfunc="sum").loc[MARKETS, CHANNELS]
    orders_m = y1.groupby("market").orders.sum().loc[MARKETS].to_numpy(float)
    week_w = paid.pivot_table(index="market", columns="week_start", values="spend_eur", aggfunc="sum").loc[MARKETS].to_numpy()
    s = n / N_PEOPLE                     # n < N_PEOPLE: a 1:k sample (used by tests); s = 1 leaves everything as is
    spend_mc = spend_mc * s
    base_rev_target = float(y1.loc[y1.channel == "Direct_Other", "net_revenue_eur"].sum()) * s
    inc_rev_target = {c: PLANTED_IROAS[c] * float(spend_mc[c].sum()) for c in CHANNELS}

    # people
    M = len(MARKETS)
    mkt = rng.choice(M, size=n, p=orders_m / orders_m.sum())
    z = rng.standard_normal(n)
    u_buy = rng.random(n)
    lead = rng.random(n) < LEAD_SHARE
    summer = lead & (rng.random(n) < SH_SHARE_OF_LEAD)
    loss = np.array([CONSENT_LOSS[m] for m in MARKETS])
    tracked = rng.random(n) >= loss[mkt]
    entry_week = np.empty(n, dtype=int)
    for i in range(M):
        idx = np.flatnonzero(mkt == i)
        entry_week[idx] = rng.choice(N_ACQ_WEEKS, size=idx.size, p=week_w[i] / week_w[i].sum())
    entry_day = entry_week * 7 + rng.random(n) * 7
    base_u1, base_u2 = rng.random(n), rng.random(n)
    u_nav, u_nav_type = rng.random(n), rng.random(n)
    u_quote, u_quote_pick = rng.random(n), rng.random(n)
    p_of, p_sh = PRICE_OF / (1 + VAT), PRICE_SH / (1 + VAT)
    value = np.where(summer, p_sh[mkt], p_of[mkt])

    # touches: one entry touch per person (day 0) + Poisson extras per touch type
    e_types, e_p = _mix(ENTRY_MIX)
    persons, types, offsets = [np.arange(n)], [e_types[rng.choice(len(e_types), size=n, p=e_p)]], [np.zeros(n)]
    for ti, tt in enumerate(TOUCH_TYPES):
        k = rng.poisson(tt.mu * np.exp(tt.gamma * z - tt.gamma ** 2 / 2))
        pid = np.repeat(np.arange(n), k)
        persons.append(pid)
        types.append(np.full(pid.size, ti))
        offsets.append(JOURNEY_DAYS * rng.beta(*TIMING[tt.timing], size=pid.size))
    t_person = np.concatenate(persons)
    t_type = np.concatenate(types)
    t_day = entry_day[t_person] + np.concatenate(offsets)
    t_u1, t_u2 = rng.random(t_person.size), rng.random(t_person.size)

    order = np.lexsort((t_day, t_person))
    t_person, t_type, t_day, t_u1, t_u2 = (a[order] for a in (t_person, t_type, t_day, t_u1, t_u2))
    ch_of_type = np.array([ALL_TOUCH_CHANNELS.index(t.channel) for t in TOUCH_TYPES])
    t_ch = ch_of_type[t_type]
    j = pd.DataFrame({"p": t_person, "c": t_ch}).groupby(["p", "c"]).cumcount().to_numpy()

    # lags (pre-drawn) and candidate order / quote times
    t_lead = lead[t_person]
    self_lag = trunc_lognormal(t_u1, *LAG_SELF)
    q_lag = trunc_lognormal(t_u1, *LAG_QUOTE)
    l_lag = trunc_lognormal(t_u2, *LAG_LEAD)
    t_quote = np.where(t_lead, t_day + q_lag, np.nan)
    t_cand = np.where(t_lead, t_day + q_lag + l_lag, t_day + self_lag)
    b_quote = np.where(lead, entry_day + trunc_lognormal(base_u1, *LAG_QUOTE), np.nan)
    b_cand = np.where(lead, b_quote + trunc_lognormal(base_u2, *LAG_LEAD), entry_day + trunc_lognormal(base_u1, *LAG_SELF))

    w = dict(n=n, mkt=mkt, z=z, u_buy=u_buy, lead=lead, summer=summer, tracked=tracked, entry_day=entry_day,
             value=value, u_nav=u_nav, u_nav_type=u_nav_type, u_quote=u_quote, u_quote_pick=u_quote_pick,
             t_person=t_person, t_type=t_type, t_ch=t_ch, t_day=t_day, t_j=j, t_quote=t_quote, t_cand=t_cand,
             t_self_lag=self_lag, b_quote=b_quote, b_cand=b_cand,
             spend_mc=spend_mc, base_rev_target=base_rev_target, inc_rev_target=inc_rev_target,
             csv_y1=y1)
    _calibrate(w)
    return w


# ---------------------------------------------------------------- calibration (deterministic, no extra randomness)
def _calibrate(w: dict) -> None:
    n, z, value = w["n"], w["z"], w["value"]
    # 1) baseline propensity: expected baseline revenue (within horizon) = CSV year-1 Direct_Other revenue
    b_in = w["b_cand"] < HORIZON_END_DAY
    lo, hi = -10.0, 0.0
    for _ in range(60):
        a = (lo + hi) / 2
        if (expit(a + P0_SIGMA * z) * value * b_in).sum() < w["base_rev_target"]:
            lo = a
        else:
            hi = a
    p0 = expit((lo + hi) / 2 + P0_SIGMA * z)

    # 2) per-channel lift scale lambda_c: expected incremental revenue = planted iROAS x year-1 spend
    tp, tch = w["t_person"], w["t_ch"]
    is_mkt = tch < len(CHANNELS)
    shape = np.where(is_mkt, (1 - p0[tp]) * FREQ_DECAY ** w["t_j"], 0.0)
    t_val_in = value[tp] * (w["t_cand"] < HORIZON_END_DAY)
    lam = np.full(len(CHANNELS), 0.01)
    targets = np.array([w["inc_rev_target"][c] for c in CHANNELS])
    raw_of = lambda lam_: np.where(is_mkt, lam_[np.minimum(tch, len(CHANNELS) - 1)] * shape, 0.0)
    for _ in range(100):
        lift, _, _ = apply_cap(p0, raw_of(lam), tp, n)
        achieved = np.bincount(tch[is_mkt], weights=(lift * t_val_in)[is_mkt], minlength=len(CHANNELS))
        if np.max(np.abs(achieved / targets - 1)) < 1e-10:
            break
        lam *= targets / achieved
    w.update(p0=p0, lam=lam)
    set_lifts(w, raw_of(lam))


def apply_cap(p0, raw, t_person, n):
    """Lift cap: if p0 + sum(raw lifts) > 1 for a person, scale all of that person's lifts by
    (1 - p0) / sum(raw lifts), so p0 + sum(lifts) = 1 exactly. Returns (lift, per-person scale, uncapped total)."""
    tot = np.bincount(t_person, weights=raw, minlength=n)
    scale = np.minimum(1.0, np.divide(1 - p0, tot, out=np.ones(n), where=tot > 0))
    return raw * scale[t_person], scale, p0 + tot


def set_lifts(w: dict, raw: np.ndarray) -> None:
    """Apply the cap, then lay out the stretches on [0, 1]: baseline [0, p0) first, then each touch in time
    order. The layout is frozen: counterfactual reruns delete stretches but never move them."""
    n, tp, p0 = w["n"], w["t_person"], w["p0"]
    lift, scale, uncapped = apply_cap(p0, raw, tp, n)
    cs = np.cumsum(lift)
    counts = np.bincount(tp, minlength=n)
    first = np.r_[0, np.cumsum(counts)[:-1]]
    before = (cs - lift)[first]                      # cumulative lift before each person's first touch
    t_start = p0[tp] + (cs - lift) - np.repeat(before, counts)
    w.update(raw_lift=raw, lift=lift, t_start=t_start, cap_scale=scale, uncapped_total=uncapped,
             touch_counts=counts, touch_first=first)


# ---------------------------------------------------------------- outcome (factual or counterfactual rerun)
def simulate(w: dict, removed: tuple[str, ...] | list[str] = ()) -> dict:
    """Outcome with the touches of `removed` channels deleted. Same random numbers, stretches not moved."""
    n = w["n"]
    rem_idx = [ALL_TOUCH_CHANNELS.index(c) for c in removed]
    active = ~np.isin(w["t_ch"], rem_idx) & (w["lift"] > 0)
    u = w["u_buy"][w["t_person"]]
    hit = active & (u >= w["t_start"]) & (u < w["t_start"] + w["lift"])
    cause = np.full(n, -2)                                    # -2 no cause, -1 baseline, >=0 touch index
    cause[w["u_buy"] < w["p0"]] = -1
    assert not np.any(cause[w["t_person"][hit]] != -2), "stretches overlap"
    cause[w["t_person"][hit]] = np.flatnonzero(hit)
    has = cause >= 0
    order_day = np.full(n, np.nan)
    order_day[cause == -1] = w["b_cand"][cause == -1]
    order_day[has] = w["t_cand"][cause[has]]
    buy = (cause > -2) & (order_day < HORIZON_END_DAY)
    cause_ch = np.full(n, -1)                                 # -1 baseline / none
    cause_ch[has] = w["t_ch"][cause[has]]
    return dict(cause=cause, cause_ch=cause_ch, order_day=order_day, buy=buy)


def true_effects(w: dict, factual: dict) -> pd.DataFrame:
    """True incremental orders / revenue per channel from counterfactual reruns (one channel removed each)."""
    rows = []
    spend = w["spend_mc"].sum()
    base_orders, base_rev = factual["buy"].sum(), (w["value"] * factual["buy"]).sum()
    for c in CHANNELS:
        cf = simulate(w, [c])
        d_orders = int(factual["buy"].sum() - cf["buy"].sum())
        d_rev = float((w["value"] * factual["buy"]).sum() - (w["value"] * cf["buy"]).sum())
        lab = factual["buy"] & (factual["cause_ch"] == ALL_TOUCH_CHANNELS.index(c))
        rows.append(dict(channel=c, spend_eur=float(spend[c]), true_incremental_orders=d_orders,
                         true_incremental_revenue_eur=d_rev, true_iroas=d_rev / float(spend[c]),
                         planted_iroas=PLANTED_IROAS[c], label_orders=int(lab.sum()),
                         label_revenue_eur=float((w["value"] * lab).sum())))
    off = simulate(w, CHANNELS)
    rows.append(dict(channel="Direct_Other", spend_eur=0.0, true_incremental_orders=int(off["buy"].sum()),
                     true_incremental_revenue_eur=float((w["value"] * off["buy"]).sum()), true_iroas=np.nan,
                     planted_iroas=np.nan, label_orders=int((factual["buy"] & (factual["cause"] == -1)).sum()),
                     label_revenue_eur=float((w["value"] * factual["buy"] * (factual["cause"] == -1)).sum())))
    t = pd.DataFrame(rows)
    t["true_share_of_orders"] = t.true_incremental_orders / base_orders
    t["true_share_of_revenue"] = t.true_incremental_revenue_eur / base_rev
    return t


# ---------------------------------------------------------------- observed event table
def build_events(w: dict, f: dict) -> pd.DataFrame:
    n, tp = w["n"], w["t_person"]
    buy, order_day = f["buy"], f["order_day"]
    keep = ~buy[tp] | (w["t_day"] < order_day[tp])           # buyers: only touches before the order
    # navigational session at purchase (zero lift)
    nav_types, nav_p = _mix(NAV_MIX)
    nav_pick = nav_types[np.searchsorted(np.cumsum(nav_p), w["u_nav_type"], side="right").clip(max=len(nav_p) - 1)]
    nav = buy & (w["u_nav"] < NAV_PROB)
    # quotes: lead persons with a cause get the cause's quote; lead persons without one quote w.p. q
    lead, cause = w["lead"], f["cause"]
    q_day = np.full(n, np.nan)
    q_day[lead & (cause == -1)] = w["b_quote"][lead & (cause == -1)]
    lc = lead & (cause >= 0)
    q_day[lc] = w["t_quote"][cause[lc]]
    lead_orders = (lead & buy).sum()
    n_cause_quotes = ((lead & (cause > -2)) & (q_day < HORIZON_END_DAY)).sum()
    nocause = lead & (cause == -2)
    q = np.clip((lead_orders / LEAD_TO_ORDER_TARGET - n_cause_quotes) / nocause.sum(), 0, 1)
    pick = w["touch_first"] + np.floor(w["u_quote_pick"] * w["touch_counts"]).astype(int)
    rq = nocause & (w["u_quote"] < q)
    q_day[rq] = w["t_quote"][pick[rq]]
    has_q = ~np.isnan(q_day) & (q_day < HORIZON_END_DAY)

    # cost per paid touch: year-1 spend per market x channel spread evenly over that cell's observed-world touches
    tt_ch = np.array([t.channel for t in TOUCH_TYPES], dtype=object)
    tt_ct = np.array([t.campaign_type for t in TOUCH_TYPES], dtype=object)
    touch_mkt = np.r_[w["mkt"][tp[keep]], w["mkt"][nav]]
    touch_ch = np.r_[w["t_ch"][keep], np.array([ALL_TOUCH_CHANNELS.index(TOUCH_TYPES[k].channel) for k in nav_pick[nav]], dtype=int)]
    cnt = np.zeros((len(MARKETS), len(ALL_TOUCH_CHANNELS)))
    np.add.at(cnt, (touch_mkt, touch_ch), 1)
    cpt = np.zeros_like(cnt)
    cpt[:, :len(CHANNELS)] = w["spend_mc"].to_numpy() / cnt[:, :len(CHANNELS)]

    # assemble with small-dtype numpy arrays (memory-lean), then one categorical DataFrame
    NONE = len(TOUCH_TYPES)                                    # "no touch type" code for quote / purchase rows
    kidx = np.flatnonzero(keep).astype(np.int32)
    nav_ids = np.flatnonzero(nav).astype(np.int32)
    q_ids = np.flatnonzero(has_q).astype(np.int32)
    b = np.flatnonzero(buy).astype(np.int32)
    nk, nn, nq, nb = kidx.size, nav_ids.size, q_ids.size, b.size
    person = np.concatenate([tp[kidx].astype(np.int32), nav_ids, q_ids, b])
    day = np.concatenate([w["t_day"][kidx], order_day[nav_ids] - NAV_OFFSET_DAYS, q_day[q_ids], order_day[b]])
    ecode = np.concatenate([np.zeros(nk + nn, np.int8), np.ones(nq, np.int8), np.full(nb, 2, np.int8)])
    ttype = np.concatenate([w["t_type"][kidx].astype(np.int8), nav_pick[nav_ids].astype(np.int8),
                            np.full(nq + nb, NONE, np.int8)])
    navflag = np.concatenate([np.zeros(nk, np.int8), np.ones(nn, np.int8), np.zeros(nq + nb, np.int8)])
    cost = np.concatenate([cpt[w["mkt"][tp[kidx]], w["t_ch"][kidx]], cpt[w["mkt"][nav_ids], touch_ch[nk:]],
                           np.full(nq + nb, np.nan)])
    lift = np.concatenate([w["lift"][kidx], np.zeros(nn), np.full(nq + nb, np.nan)])
    tidx = np.concatenate([kidx, np.full(nn + nq + nb, -1, np.int32)])
    ctouch = np.concatenate([np.full(nk + nn + nq, -3, np.int32), f["cause"][b].astype(np.int32)])
    # cause name code: 0..6 = ALL_TOUCH_CHANNELS, 7 = baseline, 8 = (not a purchase)
    cname = np.concatenate([np.full(nk + nn + nq, 8, np.int8),
                            np.where(f["cause"][b] == -1, 7, f["cause_ch"][b]).astype(np.int8)])
    prod = np.concatenate([np.full(nk + nn + nq, 2, np.int8), np.where(w["summer"][b], 1, 0).astype(np.int8)])
    val = np.concatenate([np.full(nk + nn + nq, np.nan), w["value"][b]])

    order = np.lexsort((ecode, day, person))
    person, day, ecode, ttype, navflag, cost, lift, tidx, ctouch, cname, prod, val = (
        a[order] for a in (person, day, ecode, ttype, navflag, cost, lift, tidx, ctouch, cname, prod, val))
    inv = np.full(w["t_person"].size, -1, np.int64)
    is_t = tidx >= 0
    inv[tidx[is_t]] = np.flatnonzero(is_t)
    cause_eid = np.where(ctouch >= 0, inv[np.maximum(ctouch, 0)], -1)
    assert np.all(cause_eid[ctouch >= 0] >= 0), "a causing touch is missing from the event table"

    tt_ch_codes = np.array([ALL_TOUCH_CHANNELS.index(t.channel) for t in TOUCH_TYPES] + [-1])
    ct_names = sorted({t.campaign_type for t in TOUCH_TYPES})
    tt_ct_codes = np.array([ct_names.index(t.campaign_type) for t in TOUCH_TYPES] + [-1])
    cat = pd.Categorical.from_codes
    ev = pd.DataFrame({
        "event_id": np.arange(person.size, dtype=np.int32),
        "person_id": person,
        "market": cat(w["mkt"][person], MARKETS),
        "path_type": cat(w["lead"][person].astype(np.int8), ["self_serve", "lead"]),
        "tracked": w["tracked"][person].astype(np.int8),
        "day": day,
        "event": cat(ecode, ["touch", "quote_request", "purchase"]),
        "channel": cat(tt_ch_codes[ttype], ALL_TOUCH_CHANNELS),
        "campaign_type": cat(tt_ct_codes[ttype], ct_names),
        "navigational": navflag,
        "cost_eur": cost,
        "product": cat(np.where(prod == 2, -1, prod), ["outdoor_furniture", "summer_house"]),
        "order_value_eur": val,
        "true_lift": lift,
        "true_cause_channel": cat(np.where(cname == 8, -1, cname), ALL_TOUCH_CHANNELS + ["baseline"]),
        "true_cause_event_id": pd.array(np.where(cause_eid >= 0, cause_eid, 0), dtype="Int64"),
    })
    ev.loc[cause_eid < 0, "true_cause_event_id"] = pd.NA
    return ev, dict(cpt=cpt, cnt=cnt, quote_rate_nocause=float(q))


# ---------------------------------------------------------------- calibration report
def _q(x, p):
    return float(np.quantile(x, p)) if len(x) else float("nan")


def calibration(w, f, truth, ev, extra) -> dict:
    buy = f["buy"]
    y1 = w["csv_y1"]
    spend_sim = ev.groupby("channel").cost_eur.sum()
    spend_csv = w["spend_mc"].sum()
    pur = ev[ev.event == "purchase"]
    first_touch = ev[ev.event == "touch"].groupby("person_id").day.min()
    lag_first = pur.day.to_numpy() - first_touch.reindex(pur.person_id).to_numpy()
    selfp = (pur.path_type == "self_serve").to_numpy()
    has = f["cause"] >= 0
    cause_self = buy & has & ~w["lead"]
    self_lag_cause = f["order_day"][cause_self] - w["t_day"][f["cause"][cause_self]]
    leadb = pur[pur.path_type == "lead"]
    qd = ev[ev.event == "quote_request"].set_index("person_id").day
    q_to_o = leadb.day.to_numpy() - qd.reindex(leadb.person_id).to_numpy()
    obs_touch = ev[(ev.event == "touch") & (ev.tracked == 1)]
    obs_len = obs_touch[obs_touch.person_id.isin(pur.person_id)].groupby("person_id").size().reindex(pur.person_id, fill_value=0)
    censored = int(((f["cause"] > -2) & ~buy).sum())
    mkt_share = pd.Series(w["mkt"][buy]).map(dict(enumerate(MARKETS))).value_counts(normalize=True).reindex(MARKETS)
    csv_mkt = y1.groupby("market").orders.sum().reindex(MARKETS); csv_mkt /= csv_mkt.sum()
    trk = pd.DataFrame({"m": np.array(MARKETS)[w["mkt"]], "t": w["tracked"]}).groupby("m").t.mean().reindex(MARKETS)
    return dict(
        spend=pd.DataFrame({"csv_year1": spend_csv, "simulated": spend_sim.reindex(CHANNELS)}),
        orders=int(buy.sum()), revenue=float((w["value"] * buy).sum()),
        csv_y1_orders=int(y1.orders.sum()), csv_y1_revenue=float(y1.net_revenue_eur.sum()),
        csv_y1_spend=float(spend_csv.sum()),
        base_share_orders=float(truth.set_index("channel").loc["Direct_Other", "true_share_of_orders"]),
        base_share_revenue=float(truth.set_index("channel").loc["Direct_Other", "true_share_of_revenue"]),
        csv_base_share_revenue=float(w["base_rev_target"] / y1.net_revenue_eur.sum()),
        summer_share=float((pur["product"] == "summer_house").mean()),
        lead_share=float((pur.path_type == "lead").mean()),
        market_share=pd.DataFrame({"simulated": mkt_share, "csv_year1": csv_mkt}),
        tracked=pd.DataFrame({"tracked_share": trk, "target": [1 - CONSENT_LOSS[m] for m in MARKETS]}, index=MARKETS),
        self_lag_cause=dict(median=_q(self_lag_cause, .5), p95=_q(self_lag_cause, .95), max=float(self_lag_cause.max())),
        self_first_click=dict(median=_q(lag_first[selfp], .5), p95=_q(lag_first[selfp], .95), within90=float((lag_first[selfp] <= 90).mean())),
        lead_q_to_o=dict(median=_q(q_to_o, .5), p90=_q(q_to_o, .9), max=float(np.nanmax(q_to_o)),
                         over90=float((q_to_o > 90).mean()), over180=float((q_to_o > 180).mean())),
        all_first_click=dict(median=_q(lag_first, .5), within90=float((lag_first <= 90).mean()), within365=float((lag_first <= 365).mean())),
        quotes=int((ev.event == "quote_request").sum()), lead_orders=int(len(leadb)),
        quote_rate_nocause=extra["quote_rate_nocause"],
        touches_per_person=float((ev.event == "touch").sum() / w["n"]),
        obs_path_len=dict(mean=float(obs_len.mean()), median=float(obs_len.median()), empty=float((obs_len == 0).mean())),
        nav_share=float(ev[(ev.event == "touch")].navigational.sum() / len(pur)),
        capped_people=int((w["uncapped_total"] > 1 + 1e-12).sum()),
        max_total=float((w["p0"] + np.bincount(w["t_person"], weights=w["lift"], minlength=w["n"])).max()),
        max_uncapped=float(w["uncapped_total"].max()),
        p0=dict(mean=float(w["p0"].mean()), p50=_q(w["p0"], .5), p99=_q(w["p0"], .99), max=float(w["p0"].max())),
        lam=dict(zip(CHANNELS, w["lam"])),
        censored=censored,
        rerun_vs_label=int((truth.true_incremental_orders - truth.label_orders).abs().max()),
    )


# ---------------------------------------------------------------- answer key
def write_key(w, truth, cal, sizes, runtime) -> str:
    t = truth.set_index("channel")
    rows = "\n".join(
        f"| {c} | {t.loc[c,'spend_eur']/1e6:.2f} | {t.loc[c,'true_incremental_orders']:,} | "
        f"{t.loc[c,'true_incremental_revenue_eur']/1e6:.2f} | {t.loc[c,'true_iroas']:.2f} | {PLANTED_IROAS[c]} | "
        f"{t.loc[c,'true_share_of_orders']:.1%} |" for c in CHANNELS)
    b = t.loc["Direct_Other"]
    tt = "\n".join(f"| {x.channel} | {x.campaign_type} | {x.mu} | {x.gamma} | {x.timing} |" for x in TOUCH_TYPES)
    return f"""# Answer key: attribution extension (journey simulation)

ALL DATA IS SIMULATED (fictional brand "Nordvik Outdoor"). Generated by `generate_journeys.py`, seed {SEED}.
Spec: `docs/attribution_extension_spec.md`. These are the planted truths the attribution models are compared against.

## 1. True incremental effect per channel (counterfactual reruns, common random numbers)
Cohort: first touches 2024-10-28 to 2025-10-26, orders followed to 2026-10-25. Spend = CSV year-1 spend.

| Channel | Spend EUR M | True incremental orders | True incremental revenue EUR M | True iROAS | Planted iROAS | Share of orders |
|---|---|---|---|---|---|---|
{rows}
| Direct_Other (baseline, all marketing off) | 0 | {int(b.true_incremental_orders):,} | {b.true_incremental_revenue_eur/1e6:.2f} | n/a | n/a | {b.true_share_of_orders:.1%} |

Total orders {cal['orders']:,}; net revenue EUR {cal['revenue']/1e6:.1f}M. Channel effects plus baseline add up to the total exactly
(the stretches never move between reruns). Largest gap between rerun differences and per-order `true_cause_channel` labels: {cal['rerun_vs_label']}.

## 2. How the truth is built
- Each person draws one uniform U. [0, p0) is the baseline; each touch owns the next stretch of length `lift`, in time order.
  The stretch U falls into is the true cause. A rerun deletes one channel's stretches without moving the others.
- Baseline propensity p0 = expit(a + {P0_SIGMA} z), z ~ N(0,1); `a` calibrated so expected baseline revenue = CSV year-1 Direct_Other revenue.
  p0 mean {cal['p0']['mean']:.3f}, median {cal['p0']['p50']:.3f}, 99th pct {cal['p0']['p99']:.3f}.
- Touch lift = lambda_c x (1 - p0) x {FREQ_DECAY}^(j-1), j = j-th touch of that channel for the person. Direct touches have zero lift.
  lambda: {', '.join(f'{c} {v:.4f}' for c, v in cal['lam'].items())}.
- **Lift cap:** if p0 + sum(lifts) > 1, all of that person's lifts are scaled by (1 - p0) / sum(lifts), so the total is exactly 1.
  People capped: {cal['capped_people']:,} of {w['n']:,}. Largest uncapped total: {cal['max_uncapped']:.3f}; largest total after the cap: {cal['max_total']:.6f}.
- Selection bias: extra touches ~ Poisson(mu x exp(gamma z - gamma^2/2)), so high-gamma types reach high-propensity people.

| Channel | Campaign type | mu | gamma | Timing in journey |
|---|---|---|---|---|
{tt}

- Every person has one entry touch at day 0 (mix: {', '.join(f'{k[0]} {k[1]} {v:.0%}' for k, v in ENTRY_MIX.items())}).
- Zero-lift navigational session just before {NAV_PROB:.0%} of orders ({', '.join(f'{k[0]} {k[1]} {v:.0%}' for k, v in NAV_MIX.items())}). Paid ones (Google brand, Email, SEO) carry cost.
- Cost per touch = year-1 spend of that market x channel / that cell's touches (including paid navigational clicks).

## 3. Paths and lags
- Self-serve: causing touch -> order, log-normal median {LAG_SELF[0]:.0f} days, sigma {LAG_SELF[1]}, truncated at {LAG_SELF[2]:.0f} days (as in `generate_data.py`).
- Lead path ({LEAD_SHARE:.1%} of people: all summer houses + 11% of outdoor furniture): touch -> quote_request log-normal median {LAG_QUOTE[0]:.0f}d, sigma {LAG_QUOTE[1]}, cap {LAG_QUOTE[2]:.0f}d;
  quote_request -> order median {LAG_LEAD[0]:.0f}d, sigma {LAG_LEAD[1]}, **truncated at {LAG_LEAD[2]:.0f} days** (the repo's 91-day cap does not apply here).
- Lead people with no cause request a quote with probability {cal['quote_rate_nocause']:.3f}, so about {LEAD_TO_ORDER_TARGET:.0%} of quotes end in an order.
- Orders censored by the data end (2026-10-25): {cal['censored']:,} in the factual run (the same cut-off applies in every rerun).

## 4. Consent loss (observed paths only)
Per person: DE/AT 30%, FR/NL 20%, UK 15%, SE 10% untracked. An untracked person's touches are all missing from observed
paths (`tracked = 0`); purchases and quote requests are always recorded (server-side / CRM). The truth uses full paths.

## 5. Files
{chr(10).join(f'- `{k}`: {v/1e6:.2f} MB' if v >= 1e5 else f'- `{k}`: {v/1e3:.1f} KB' for k, v in sizes.items())}
- Runtime: {runtime:.0f} s.
"""


# ---------------------------------------------------------------- main
def main() -> None:
    t0 = time.time()
    w = build_world()
    f = simulate(w)
    truth = true_effects(w, f)
    ev, extra = build_events(w, f)
    cal = calibration(w, f, truth, ev, extra)

    ev_out = ev                       # rounded in place (this laptop has little free memory)
    ev_out["day"] = ev_out.day.round(3)
    ev_out["cost_eur"] = ev_out.cost_eur.round(6)   # one cost per market x channel: 2 dp would bias totals by ~EUR 1k
    ev_out["order_value_eur"] = ev_out.order_value_eur.round(2)
    ev_out["true_lift"] = ev_out.true_lift.round(6)
    ev_out.loc[ev_out.event != "touch", "cost_eur"] = np.nan
    ev_out.to_csv(REPO / EVENTS_REL, index=False, compression={"method": "gzip", "compresslevel": 9})
    truth.drop(columns=["label_orders", "label_revenue_eur"]).round(6).to_csv(REPO / TRUTH_REL, index=False)
    runtime = time.time() - t0
    sizes = {p: (REPO / p).stat().st_size for p in (EVENTS_REL, TRUTH_REL)}
    (REPO / KEY_REL).write_text(write_key(w, truth, cal, sizes, runtime), encoding="utf-8")
    sizes[KEY_REL] = (REPO / KEY_REL).stat().st_size

    pd.set_option("display.width", 200)
    print(f"runtime {runtime:.1f}s   events {len(ev):,}   people {w['n']:,}")
    print("sizes MB:", {k: round(v / 1e6, 2) for k, v in sizes.items()})
    print(truth.round(3).to_string(index=False))
    for k, v in cal.items():
        print(f"\n{k}:\n{v}" if isinstance(v, pd.DataFrame) else f"{k}: {v}")


if __name__ == "__main__":
    main()
