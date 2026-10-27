"""
Step 4a: Meta geo holdout analysis (Germany), outcome = ORDERS.

Question: how many orders did Meta really cause in Germany, and what was Meta's incremental ROAS?
Design (from data/events_calendar.csv): Meta paused in DE for 12 weeks from 2026-05-11. Orders keep
arriving for ~12 more weeks (30-90 day buying window), so the effect window runs to the end of the data.

Method
  1. Test = DE total orders (all channels). Control = AT, FR, NL, UK, SE (Meta kept running).
  2. Fit weights on the control markets so they reproduce DE's orders BEFORE the test (non-negative least squares).
  3. Counterfactual = those weights applied to the control markets DURING the test.
  4. Incremental orders = actual DE orders - counterfactual. Uncertainty from placebo tests on the pre-period.
  5. Convert to incremental ROAS = incremental net revenue / Meta spend saved.
"""
import numpy as np, pandas as pd
from scipy.optimize import nnls
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt

d = pd.read_csv("data/simulated_weekly_data.csv", parse_dates=["week_start"])
cal = pd.read_csv("data/events_calendar.csv", parse_dates=["start_week", "end_week"])
hold = cal[cal.event == "meta_holdout"].iloc[0]
weeks = sorted(d.week_start.unique())
T0 = weeks.index(np.datetime64(hold.start_week)); T1 = weeks.index(np.datetime64(hold.end_week))   # first / last paused week
N = len(weeks)                       # data ends after the lagged tail
TEST, CONTROLS = hold.markets, ["AT", "FR", "NL", "UK", "SE"]
BREAK_EVEN = 1 / 0.55                # 1 / contribution margin before marketing (assumptions.md)

orders = d.groupby(["week_start", "market"]).orders.sum().unstack().reindex(columns=[TEST] + CONTROLS)
y = orders[TEST].values; X = orders[CONTROLS].values

# promo weeks (70-77) hit DE, AT, FR, NL but not UK/SE, so keep them out of the fitting period
PROMO = set(range(70, 78))
def fit_effect(start, length):
    """Fit on weeks before `start` (excluding promo weeks), predict `length` weeks from `start`."""
    idx = [t for t in range(start) if t not in PROMO]
    w, _ = nnls(X[idx], y[idx])
    win = np.arange(start, start + length)
    cf = X[win] @ w
    return w, win, cf, y[win]

length = N - T0                      # effect window: first paused week to end of data
w, win, cf, act = fit_effect(T0, length)
inc_orders = act.sum() - cf.sum(); pct = act.sum() / cf.sum() - 1

# pre-period fit quality
idx = [t for t in range(T0) if t not in PROMO]
fit = X[idx] @ w
mape = np.mean(np.abs(y[idx] - fit) / y[idx])

# placebo tests: pretend the holdout happened earlier (windows fully before the promo), same method.
# 12-week windows give a bigger null sample; scale the spread to the effect-window length (independent weeks assumed).
placebo12 = []
for s in range(26, 58):
    _, _, c, a = fit_effect(s, 12); placebo12.append(a.sum() / c.sum() - 1)
sd12 = np.sqrt(np.mean(np.square(placebo12)))
sd = sd12 * np.sqrt(12 / length)
lo, hi = pct - 1.96 * sd, pct + 1.96 * sd

# naive comparisons for contrast
naive_prepost = y[T0:].mean() / y[T0 - length:T0].mean() - 1                 # same-length window before
did_ratio = (y[T0:].sum() / X[T0:].sum()) / (y[idx].sum() / X[idx].sum()) - 1  # simple ratio difference-in-differences

# --- incremental ROAS
meta = d[d.channel == "Meta"].pivot(index="week_start", columns="market", values="spend_eur")
rep = d[d.channel == "Meta"].pivot(index="week_start", columns="market", values="platform_reported_revenue_eur")
share_pre = meta[TEST].values[idx].sum() / meta[CONTROLS].values[idx].sum()             # DE Meta spend relative to controls
saved_spend = (share_pre * meta[CONTROLS].values[T0:T1 + 1].sum(axis=1)).sum()           # spend DE would have made in the paused weeks
rev = d.groupby(["week_start", "market"]).net_revenue_eur.sum().unstack()[TEST].values
aov = rev[idx].sum() / y[idx].sum()                                                      # DE average net order value, pre-period
inc_rev = inc_orders * aov
iroas = -inc_rev / saved_spend                                                           # orders lost -> Meta's incremental revenue
lost_pct_lo, lost_pct_hi = -hi, -lo                                                      # lost share of orders, ordered low to high
iroas_lo = (lost_pct_lo * cf.sum() * aov) / saved_spend; iroas_hi = (lost_pct_hi * cf.sum() * aov) / saved_spend
reported = rep[TEST].values[idx].sum() / meta[TEST].values[idx].sum()                    # platform ROAS in DE before the test

wtxt = {c: round(float(v), 3) for c, v in zip(CONTROLS, w)}
res = f"""META HOLDOUT RESULT (Germany, outcome = orders)
Test window: {pd.Timestamp(weeks[T0]).date()} to {pd.Timestamp(weeks[-1]).date()} ({length} weeks; Meta paused in the first {T1-T0+1})
Pre-period fit error (mean abs % error): {mape:.1%}
Control weights: {wtxt}

Orders actual vs counterfactual: {act.sum():,.0f} vs {cf.sum():,.0f}
Incremental orders from Meta: {-inc_orders:,.0f} lost when paused ({pct:+.1%}, 95% interval {lo:+.1%} to {hi:+.1%})
Naive pre/post (same-length window before): {naive_prepost:+.1%}   <- misleading (seasonality)
Simple ratio difference-in-differences:      {did_ratio:+.1%}

Meta spend saved during the pause: EUR {saved_spend:,.0f}
Incremental net revenue lost: EUR {-inc_rev:,.0f}  (avg DE net order value EUR {aov:,.0f})
Incremental ROAS: {iroas:.2f}  (95% interval {iroas_lo:.2f} to {iroas_hi:.2f})
Platform-reported ROAS in DE (pre-test): {reported:.2f}
Break-even ROAS: {BREAK_EVEN:.2f}
"""
print(res); open("analysis/meta_holdout_results.txt", "w").write(res)

# --- chart
fig, ax = plt.subplots(1, 2, figsize=(13, 4.6), gridspec_kw={"width_ratios": [2.2, 1]})
x = np.array(pd.to_datetime(weeks))
ax[0].plot(x, y, color="#1F3A5F", lw=1.6, label="Germany actual orders")
cf_full = np.full(N, np.nan); cf_full[win] = cf
pre_fit = np.full(N, np.nan); pre_fit[idx] = fit
ax[0].plot(x, pre_fit, color="#9aa5b1", lw=1, ls="--", label="Model fit (pre-test)")
ax[0].plot(x, cf_full, color="#C0392B", lw=1.8, label="Counterfactual (Meta kept on)")
ax[0].axvspan(x[T0], x[T1], color="#F4D03F", alpha=.25, label="Meta paused")
ax[0].set_title("Germany weekly orders: actual vs counterfactual"); ax[0].legend(frameon=False, fontsize=8, loc="upper left"); ax[0].set_ylabel("orders per week")
bars = ["Platform-reported", "Incremental (holdout)"]; vals = [reported, iroas]
ax[1].bar(bars, vals, color=["#9aa5b1", "#1F3A5F"]); ax[1].errorbar(1, iroas, yerr=[[iroas - iroas_lo], [iroas_hi - iroas]], color="k", capsize=5)
ax[1].axhline(BREAK_EVEN, color="#C0392B", ls="--"); ax[1].text(-0.4, BREAK_EVEN + .05, f"break-even {BREAK_EVEN:.1f}", color="#C0392B", fontsize=8)
ax[1].set_title("Meta ROAS: reported vs incremental"); ax[1].set_ylim(0, max(vals + [iroas_hi]) * 1.15)
for a in ax: a.spines[["top", "right"]].set_visible(False)
plt.tight_layout(); plt.savefig("analysis/meta_holdout.png", dpi=150)
