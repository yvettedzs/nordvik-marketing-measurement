"""
Step 3: simulated weekly dataset for a fictional premium D2C outdoor-living brand ("Nordvik Outdoor").

ALL DATA IS SIMULATED. See docs/assumptions.md for the business assumptions.
Grain: one row per week x market x channel.   Seed fixed for reproducibility.

Outputs
  data/simulated_weekly_data.csv   the dataset used for analysis
  data/events_calendar.csv         the test/promo DESIGN (dates, markets), not the effect sizes
  docs/answer_key.md               planted effects + true values. Do not open until Step 4 is done.
"""
import numpy as np, pandas as pd
from datetime import date, timedelta

SEED = 42
rng = np.random.default_rng(SEED)

# ---------------------------------------------------------------- calendar
N_WEEKS = 104
LAST_MONDAY = date(2026, 10, 19)
START = LAST_MONDAY - timedelta(weeks=N_WEEKS - 1)
WEEKS = [START + timedelta(weeks=i) for i in range(N_WEEKS)]
T = np.arange(N_WEEKS)
woy = np.array([w.isocalendar()[1] for w in WEEKS])

# ---------------------------------------------------------------- business assumptions
ANNUAL_NET_REVENUE = 115e6          # across the 6 simulated markets
SPEND_RATIO = 0.20                  # marketing spend / net revenue
GROSS_MARGIN = 0.70                 # product-level gross margin (net revenue less COGS)
VAR_COST = 0.15                     # delivery, payment fees, returns handling (% of regular net revenue)
CM = GROSS_MARGIN - VAR_COST        # contribution margin before marketing
BREAK_EVEN_ROAS = 1 / CM
MARKETS = {                          # revenue share, VAT
    "DE": (0.40, 0.19), "AT": (0.12, 0.20), "FR": (0.16, 0.20),
    "NL": (0.14, 0.21), "UK": (0.10, 0.20), "SE": (0.08, 0.25),
}
PRICE_OF, PRICE_SH = 3500.0, 9000.0  # regular prices incl. VAT: outdoor furniture, summer house
MIX_OF = 0.85                        # share of orders that are outdoor furniture

# channel: spend share, TRUE average incremental ROAS (net revenue / spend),
#          platform-REPORTED ROAS, diminishing-returns exponent, session->order conversion
CH = {
    "Google":     dict(share=0.40, iroas=3.6,  rep=5.0,  beta=0.60, cvr=0.012, noise=0.07),
    "Meta":       dict(share=0.30, iroas=1.5,  rep=2.4,  beta=0.50, cvr=0.005, noise=0.07),
    "Affiliates": dict(share=0.12, iroas=3.0,  rep=4.2,  beta=0.70, cvr=0.015, noise=0.07),
    "TikTok":     dict(share=0.08, iroas=0.7,  rep=2.0,  beta=0.50, cvr=0.003, noise=0.07),
    "SEO":        dict(share=0.08, iroas=4.8,  rep=None, beta=0.80, cvr=0.010, noise=0.03),
    "Email":      dict(share=0.02, iroas=12.0, rep=17.0, beta=0.70, cvr=0.030, noise=0.03),
}
BASE_CVR = 0.015                     # Direct_Other (non-marketing) session->order conversion
# click -> order delay: right-skewed log-normal, median 31 days, ~95% of orders within 90 days (truncated at 91 days)
LAG_MEDIAN_DAYS, LAG_SIGMA, MAX_LAG_WEEKS = 31, 0.65, 13
def _lag_kernel():
    from math import erf, log, sqrt
    cdf = lambda x: 0.0 if x <= 0 else 0.5 * (1 + erf((log(x) - log(LAG_MEDIAN_DAYS)) / (LAG_SIGMA * sqrt(2))))
    w = [cdf(7 * (k + 1)) - cdf(7 * k) for k in range(MAX_LAG_WEEKS)]
    tot = sum(w)
    return {k: v / tot for k, v in enumerate(w)}
LAG_KERNEL = _lag_kernel()

# ---------------------------------------------------------------- planted events (the "answer key")
PROMO_MARKETS = ["DE", "AT", "FR", "NL"]   # UK and SE run no promo (natural control)
PROMO_WEEKS = range(70, 74)                # 4 weeks, outdoor furniture only
PROMO_ORDER_LIFT = 1.30                    # orders x1.30 during promo
PROMO_DIP_WEEKS = range(74, 78)            # pull-forward dip afterwards
PROMO_DIP = 0.90                           # orders x0.90
PROMO_REALISED_DISCOUNT = 0.25             # avg realised discount on outdoor-furniture orders in promo weeks (headline 40%)
HOLDOUT_MARKET, HOLDOUT_CHANNEL = "DE", "Meta"
HOLDOUT_WEEKS = range(80, 92)              # 12 weeks, Meta spend = 0 (long, because the 30-90 day buying window delays the effect; early enough that the lagged effect stays inside the data)

mk = list(MARKETS); chs = list(CH); M, C = len(mk), len(chs)
w_m = np.array([MARKETS[m][0] for m in mk]); vat = np.array([MARKETS[m][1] for m in mk])
share = np.array([CH[c]["share"] for c in chs]); iroas = np.array([CH[c]["iroas"] for c in chs])
beta = np.array([CH[c]["beta"] for c in chs]); cvr = np.array([CH[c]["cvr"] for c in chs])

# net prices and blended net order value per market
p_of = PRICE_OF / (1 + vat); p_sh = PRICE_SH / (1 + vat)
AOV = MIX_OF * p_of + (1 - MIX_OF) * p_sh

# ---------------------------------------------------------------- demand drivers
season = 1 + 0.35 * np.cos(2 * np.pi * (woy - 21) / 52); season /= season.mean()   # peak ~late May
trend = 1.08 ** (T / 52); trend /= trend.mean()

inc_share = SPEND_RATIO * float((share * iroas).sum())           # share of revenue from marketing
S_ref = (ANNUAL_NET_REVENUE * SPEND_RATIO / 52) * w_m[:, None] * share[None, :]      # (M,C) weekly ref spend

# noise (drawn once so counterfactual runs share it)
spend_noise = np.exp(rng.normal(0, 1, (M, C, N_WEEKS)) * np.array([CH[c]["noise"] for c in chs])[None, :, None])
resp_noise = np.exp(rng.normal(0, 0.12, (M, C, N_WEEKS)))
base_noise = np.exp(rng.normal(0, 0.04, (M, N_WEEKS)))
sess_noise = np.exp(rng.normal(0, 0.08, (M, C + 1, N_WEEKS)))
price_noise_of = np.exp(rng.normal(0, 0.05, (M, C + 1, N_WEEKS)))
price_noise_sh = np.exp(rng.normal(0, 0.05, (M, C + 1, N_WEEKS)))
rep_noise = np.exp(rng.normal(0, 0.10, (M, C, N_WEEKS)))

def expected(promo=True, holdout=True):
    """Deterministic expectations given the noise draws above."""
    spend = S_ref[:, :, None] * (season ** 0.5 * trend)[None, None, :] * spend_noise
    if holdout:
        spend[mk.index(HOLDOUT_MARKET), chs.index(HOLDOUT_CHANNEL), list(HOLDOUT_WEEKS)] = 0.0
    demand = (season[None, None, :] ** (1 - 0.5 * beta[None, :, None])) * (trend[None, None, :] ** (1 - beta[None, :, None]))
    inc_rev = iroas[None, :, None] * S_ref[:, :, None] * (spend / S_ref[:, :, None]) ** beta[None, :, None] * demand * resp_noise
    pot_orders = inc_rev / AOV[:, None, None]
    # click week -> order week (edge padding for the first weeks)
    PAD = MAX_LAG_WEEKS
    pad = np.concatenate([np.repeat(pot_orders[:, :, :1], PAD, axis=2), pot_orders], axis=2)
    lagged = sum(wt * pad[:, :, PAD - k: PAD - k + N_WEEKS] for k, wt in LAG_KERNEL.items())
    base_rev = ANNUAL_NET_REVENUE * (1 - inc_share) / 52 * w_m[:, None] * season[None, :] * trend[None, :] * base_noise
    base_orders = base_rev / AOV[:, None]
    orders = np.concatenate([lagged, base_orders[:, None, :]], axis=1)             # (M, C+1, T)
    mult = np.ones((M, N_WEEKS)); flag = np.zeros((M, N_WEEKS))
    if promo:
        for m in PROMO_MARKETS:
            i = mk.index(m)
            mult[i, list(PROMO_WEEKS)] = PROMO_ORDER_LIFT; mult[i, list(PROMO_DIP_WEEKS)] = PROMO_DIP
            flag[i, list(PROMO_WEEKS)] = 1
    o_of = MIX_OF * orders * mult[:, None, :]; o_sh = (1 - MIX_OF) * orders
    rev = (o_of * p_of[:, None, None] * (1 - PROMO_REALISED_DISCOUNT * flag[:, None, :]) * price_noise_of
           + o_sh * p_sh[:, None, None] * price_noise_sh)
    return dict(spend=spend, inc_rev=inc_rev, orders_of=o_of, orders_sh=o_sh, rev=rev, base_orders=base_orders, pot_orders=pot_orders)

obs = expected(True, True)
# ---------------------------------------------------------------- observed (add sampling noise)
orders_of = rng.poisson(obs["orders_of"]); orders_sh = rng.poisson(obs["orders_sh"])
rev = obs["rev"] * (orders_of + orders_sh + 1e-9) / (obs["orders_of"] + obs["orders_sh"] + 1e-9)
sessions = np.concatenate([obs["pot_orders"] / cvr[None, :, None], (obs["base_orders"] / BASE_CVR)[:, None, :]], axis=1) * sess_noise
spend = np.concatenate([obs["spend"], np.zeros((M, 1, N_WEEKS))], axis=1)
rep = np.full((M, C + 1, N_WEEKS), np.nan)
for j, c in enumerate(chs):
    if CH[c]["rep"] is not None:
        rep[:, j, :] = obs["spend"][:, j, :] * CH[c]["rep"] * rep_noise[:, j, :]

channels_all = chs + ["Direct_Other"]
rows = []
for i, m in enumerate(mk):
    for j, c in enumerate(channels_all):
        for t in range(N_WEEKS):
            rows.append((WEEKS[t].isoformat(), m, c, round(spend[i, j, t], 2), int(round(sessions[i, j, t])),
                         int(orders_of[i, j, t] + orders_sh[i, j, t]), int(orders_of[i, j, t]), int(orders_sh[i, j, t]),
                         round(rev[i, j, t], 2), None if np.isnan(rep[i, j, t]) else round(rep[i, j, t], 2), "simulated"))
df = pd.DataFrame(rows, columns=["week_start", "market", "channel", "spend_eur", "sessions", "orders",
                                 "orders_outdoor_furniture", "orders_summer_house", "net_revenue_eur",
                                 "platform_reported_revenue_eur", "data_origin"])
df.to_csv("data/simulated_weekly_data.csv", index=False)

cal = pd.DataFrame([
    dict(event="promo", markets=",".join(PROMO_MARKETS), channel="", product="outdoor_furniture",
         start_week=WEEKS[PROMO_WEEKS[0]].isoformat(), end_week=WEEKS[PROMO_WEEKS[-1]].isoformat(), note="headline 40% off selected lines"),
    dict(event="meta_holdout", markets=HOLDOUT_MARKET, channel=HOLDOUT_CHANNEL, product="all",
         start_week=WEEKS[HOLDOUT_WEEKS[0]].isoformat(), end_week=WEEKS[HOLDOUT_WEEKS[-1]].isoformat(), note="Meta paused (spend = 0)"),
])
cal.to_csv("data/events_calendar.csv", index=False)

# ---------------------------------------------------------------- answer key (true effects from the model, no sampling noise)
cf_promo = expected(promo=False, holdout=True); cf_hold = expected(promo=True, holdout=False)
def tot(d, key, mkts, weeks, ch=None):
    ii = [mk.index(x) for x in mkts]; w = list(weeks)
    a = d[key][ii][:, :, w] if ch is None else d[key][ii][:, chs.index(ch):chs.index(ch)+1, w]
    return float(a.sum())
fr = [HOLDOUT_MARKET]
HW_LONG = range(HOLDOUT_WEEKS[0], min(HOLDOUT_WEEKS[-1] + MAX_LAG_WEEKS, N_WEEKS))
cf_hold_rev = tot(cf_hold, "rev", fr, HW_LONG)
true_hold_rev = cf_hold_rev - tot(obs, "rev", fr, HW_LONG)
hold_window_rev = tot(obs, "rev", fr, HOLDOUT_WEEKS)
promo_win = range(PROMO_WEEKS[0], PROMO_DIP_WEEKS[-1] + 1)
orders_obs = tot(obs, "orders_of", PROMO_MARKETS, promo_win); orders_cf = tot(cf_promo, "orders_of", PROMO_MARKETS, promo_win)
rev_obs = tot(obs, "rev", PROMO_MARKETS, promo_win); rev_cf = tot(cf_promo, "rev", PROMO_MARKETS, promo_win)
def cm_of(d, weeks, flag_disc):
    ii = [mk.index(x) for x in PROMO_MARKETS]; w = list(weeks)
    o = d["orders_of"][ii][:, :, w].sum(axis=1)              # (markets, weeks)
    price = p_of[ii][:, None]
    per_order = price * ((1 - PROMO_REALISED_DISCOUNT * flag_disc) - (1 - GROSS_MARGIN) - VAR_COST)
    return float((o * per_order).sum())
cm_obs = cm_of(obs, PROMO_WEEKS, 1) + cm_of(obs, PROMO_DIP_WEEKS, 0)
cm_cf = cm_of(cf_promo, PROMO_WEEKS, 0) + cm_of(cf_promo, PROMO_DIP_WEEKS, 0)
promo_only_o = tot(obs, "orders_of", PROMO_MARKETS, PROMO_WEEKS) - tot(cf_promo, "orders_of", PROMO_MARKETS, PROMO_WEEKS)
dip_o = tot(obs, "orders_of", PROMO_MARKETS, PROMO_DIP_WEEKS) - tot(cf_promo, "orders_of", PROMO_MARKETS, PROMO_DIP_WEEKS)

tot_rev = df.net_revenue_eur.sum() / (N_WEEKS / 52); tot_spend = df.spend_eur.sum() / (N_WEEKS / 52)
by_ch = df.groupby("channel").agg(spend=("spend_eur", "sum"), rev=("net_revenue_eur", "sum"), rep=("platform_reported_revenue_eur", "sum"))
orders_year = df.orders.sum() / (N_WEEKS / 52)

clear_list = ', '.join(c for c in chs if CH[c]['iroas'] >= BREAK_EVEN_ROAS)
fail_list = ' and '.join(c for c in chs if CH[c]['iroas'] < BREAK_EVEN_ROAS)
key = f"""# Answer key (DO NOT OPEN until Step 4 is finished)

Planted effects in `data/simulated_weekly_data.csv`. Seed {SEED}. Values below are the model's true effects (expected values, no sampling noise).

## 1. Meta geo holdout ({HOLDOUT_MARKET}, weeks {WEEKS[HOLDOUT_WEEKS[0]]} to {WEEKS[HOLDOUT_WEEKS[-1]]}, 12 weeks)
- Meta spend set to zero in {HOLDOUT_MARKET}; all other markets run Meta as normal.
- True average incremental ROAS of Meta: **{CH['Meta']['iroas']}** (net revenue / spend). Platform-reported ROAS: **{CH['Meta']['rep']}**. Platform overstatement: about {CH['Meta']['rep']/CH['Meta']['iroas']-1:.0%}.
- Diminishing returns exponent (beta): {CH['Meta']['beta']} (the marginal euro earns about half the average).
- Orders from clicks arrive after a right-skewed log-normal delay (median {LAG_MEDIAN_DAYS} days, sigma {LAG_SIGMA}, truncated at {MAX_LAG_WEEKS} weeks, about {sum(LAG_KERNEL[k] for k in range(5)):.0%} of orders within 5 weeks). The revenue drop therefore builds quickly but fades slowly and continues for up to {MAX_LAG_WEEKS-1} weeks after restart. Measure the effect over weeks {WEEKS[HOLDOUT_WEEKS[0]]} to {WEEKS[HW_LONG[-1]]}.
- True revenue lost in {HOLDOUT_MARKET} from the pause (holdout window + {MAX_LAG_WEEKS-1} weeks): about **EUR {true_hold_rev:,.0f}**, about {true_hold_rev / cf_hold_rev:.1%} of revenue in that period.

## 2. Discount (outdoor furniture only)
- Markets with promo: {', '.join(PROMO_MARKETS)}. No promo in UK and SE (natural control).
- Weeks {WEEKS[PROMO_WEEKS[0]]} to {WEEKS[PROMO_WEEKS[-1]]} (4 weeks): outdoor-furniture orders x{PROMO_ORDER_LIFT}; realised average discount {PROMO_REALISED_DISCOUNT:.0%} (headline 40% on selected lines).
- Weeks {WEEKS[PROMO_DIP_WEEKS[0]]} to {WEEKS[PROMO_DIP_WEEKS[-1]]} (4 weeks): pull-forward dip, orders x{PROMO_DIP}.
- True extra outdoor-furniture orders during promo: **{promo_only_o:,.0f}**; lost in the dip: **{dip_o:,.0f}**; net over 8 weeks: **{promo_only_o + dip_o:,.0f}** ({(orders_obs/orders_cf-1):+.1%} vs no promo).
- True net revenue effect over the 8 weeks (promo markets): **EUR {rev_obs - rev_cf:,.0f}** ({(rev_obs/rev_cf-1):+.1%}) because of the {PROMO_REALISED_DISCOUNT:.0%} price cut.
- True outdoor-furniture **contribution margin** effect over the 8 weeks (promo markets, before marketing): **EUR {cm_obs - cm_cf:,.0f}** ({(cm_obs/cm_cf-1):+.1%}). The extra orders earn far less margin each, so the promo destroys value even though orders rise.

## 3. Channel truth (average incremental ROAS vs platform-reported ROAS)
| Channel | Spend share | True iROAS | Reported ROAS |
|---|---|---|---|
""" + "\n".join(f"| {c} | {CH[c]['share']:.0%} | {CH[c]['iroas']} | {CH[c]['rep'] if CH[c]['rep'] else 'n/a'} |" for c in chs) + f"""

Break-even ROAS on contribution margin: 1 / {CM:.2f} = about {BREAK_EVEN_ROAS:.1f}. {clear_list} clear it on a true incremental basis; {fail_list} do not. Meta's reported ROAS ({CH['Meta']['rep']}) sits above break-even, so the dashboard says 'profitable' while the truth says 'loss-making'.

## 4. Other design choices
- Attribution: platform_reported_revenue is dated by click week; orders and revenue are dated by order week.
- Direct_Other is the non-marketing base (brand, direct, word of mouth), about {1-inc_share:.0%} of revenue.
- No tracking errors are planted yet. They are added in the tracking-quality step.

## 5. Calibration check (annualised)
Net revenue EUR {tot_rev/1e6:,.1f}M; marketing spend EUR {tot_spend/1e6:,.2f}M ({tot_spend/tot_rev:.1%}); MER {tot_rev/tot_spend:.2f}; orders about {orders_year:,.0f} per year.
"""
open("docs/answer_key.md", "w").write(key)

# console summary for calibration
print(f"rows {len(df)}  rev/yr {tot_rev/1e6:.1f}M  spend/yr {tot_spend/1e6:.2f}M  MER {tot_rev/tot_spend:.2f}  orders/yr {orders_year:,.0f}")
print("avg net order value:", round(df.net_revenue_eur.sum() / df.orders.sum()))
g = by_ch.copy(); g["rev_share"] = g.rev / g.rev.sum(); g["spend_share"] = g.spend / g.spend.sum()
g["reported_ROAS"] = g.rep / g.spend
print(g.round(3))
print("holdout true loss:", round(true_hold_rev), " promo net orders:", round(promo_only_o + dip_o), " promo rev effect:", round(rev_obs - rev_cf))
print("promo order lift (naive, promo vs 4 pre weeks) and holdout check later")
