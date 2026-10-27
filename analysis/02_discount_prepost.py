"""
Step 4b: discount analysis (outdoor furniture), outcome = ORDERS, then contribution margin.

Question: did the spring discount create real extra demand, or mostly pull forward / discount sales
that would have happened anyway, and did it make or lose money?

Design (data/events_calendar.csv): headline 40% off selected outdoor-furniture lines in DE, AT, FR, NL
for 4 weeks from 2026-03-02. UK and SE ran no promo, so they are the natural control.

Method
  1. Outcome = outdoor-furniture orders (the only product discounted). Promo markets vs control markets.
  2. Pre-period ratio (promo markets / control markets) captures their normal relationship, incl. seasonality.
  3. Counterfactual = pre-period ratio x control orders during the promo and the 4 weeks after.
  4. Lift = actual vs counterfactual in the promo window; pull-forward = the same in the following 4 weeks.
  5. Uncertainty from placebo windows in the pre-period. Realised discount is implied from revenue.
  6. Contribution margin: extra orders earn less margin each, so compare to the break-even lift.
"""
import numpy as np, pandas as pd
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt

d = pd.read_csv("data/simulated_weekly_data.csv", parse_dates=["week_start"])
cal = pd.read_csv("data/events_calendar.csv", parse_dates=["start_week", "end_week"])
promo = cal[cal.event == "promo"].iloc[0]
weeks = sorted(d.week_start.unique()); N = len(weeks)
P0 = weeks.index(np.datetime64(promo.start_week)); P1 = weeks.index(np.datetime64(promo.end_week))   # promo weeks
D0, D1 = P1 + 1, P1 + (P1 - P0 + 1)                                                                  # equal-length follow-up window
PM = promo.markets.split(","); CM_MKTS = ["UK", "SE"]
PRE = list(range(13, P0))                                                                            # skip the first 13 weeks (start-up weeks of the data)

# economics from assumptions.md
GM, VAR = 0.70, 0.15
VAT = {"DE": .19, "AT": .20, "FR": .20, "NL": .21, "UK": .20, "SE": .25}
P_OF, P_SH = 3500, 9000

of = d.groupby(["week_start", "market"]).orders_outdoor_furniture.sum().unstack()
A = of[PM].sum(axis=1).values; B = of[CM_MKTS].sum(axis=1).values

def window_effect(win, pre):
    r0 = A[pre].sum() / B[pre].sum()
    cf = r0 * B[win]; act = A[win]
    return act.sum(), cf.sum(), act.sum() / cf.sum() - 1

pw = list(range(P0, P1 + 1)); dw = list(range(D0, D1 + 1)); nw = pw + dw
a_p, c_p, lift = window_effect(pw, PRE)
a_d, c_d, dip = window_effect(dw, PRE)
a_n, c_n, net = window_effect(nw, PRE)

# placebo: same-length windows inside the pre-period, ratio fitted on the other pre weeks
def placebo(L):
    out = []
    for s in range(PRE[0], PRE[-1] - L + 2):
        win = list(range(s, s + L)); pre = [t for t in PRE if t not in win]
        out.append(window_effect(win, pre)[2])
    return np.array(out)
sd4 = np.sqrt(np.mean(placebo(len(pw)) ** 2)); sd8 = np.sqrt(np.mean(placebo(len(nw)) ** 2))
ci = lambda x, sd: (x - 1.96 * sd, x + 1.96 * sd)

naive = A[pw].sum() / A[range(P0 - len(pw), P0)].sum() - 1        # promo weeks vs the 4 weeks before

# realised discount implied from revenue (revenue is not split by product in the data)
tot = d.groupby(["week_start", "market"]).agg(rev=("net_revenue_eur", "sum"), sh=("orders_summer_house", "sum"), of=("orders_outdoor_furniture", "sum"))
rows = []
for m in PM:
    for t in pw:
        r = tot.loc[(weeks[t], m)]
        rows.append((r.of * P_OF / (1 + VAT[m]), r.rev - r.sh * P_SH / (1 + VAT[m])))
list_val, paid_val = np.array(rows).sum(axis=0)
disc = 1 - paid_val / list_val

# contribution margin per outdoor-furniture order (as % of the regular net price)
cm_reg = 1 - (1 - GM) - VAR; cm_promo = (1 - disc) - (1 - GM) - VAR
breakeven_lift = cm_reg / cm_promo - 1
P_net = sum(of.loc[weeks[t], m] * P_OF / (1 + VAT[m]) for m in PM for t in pw) / sum(of.loc[weeks[t], m] for m in PM for t in pw)
cm_net = (a_p * cm_promo - c_p * cm_reg) * P_net + (a_d - c_d) * cm_reg * P_net
cm_base = c_n * cm_reg * P_net
rev_eff = (a_p * (1 - disc) - c_p) * P_net + (a_d - c_d) * P_net
cm_lo = ((c_p * (1 + ci(lift, sd4)[0]) * cm_promo - c_p * cm_reg) + (c_d * (1 + ci(dip, sd4)[0] ) - c_d) * cm_reg) * P_net
cm_hi = ((c_p * (1 + ci(lift, sd4)[1]) * cm_promo - c_p * cm_reg) + (c_d * (1 + ci(dip, sd4)[1]) - c_d) * cm_reg) * P_net

res = f"""DISCOUNT RESULT (outdoor furniture, DE+AT+FR+NL vs UK+SE control, outcome = orders)
Promo window: {pd.Timestamp(weeks[P0]).date()} to {pd.Timestamp(weeks[P1]).date()}; follow-up window: {pd.Timestamp(weeks[D0]).date()} to {pd.Timestamp(weeks[D1]).date()}

Naive pre/post (promo weeks vs 4 weeks before): {naive:+.1%}   <- misleading (spring season ramp)
Promo window orders: {a_p:,.0f} actual vs {c_p:,.0f} counterfactual -> lift {lift:+.1%} (95% interval {ci(lift, sd4)[0]:+.1%} to {ci(lift, sd4)[1]:+.1%})
Follow-up window:    {a_d:,.0f} actual vs {c_d:,.0f} counterfactual -> {dip:+.1%} (95% interval {ci(dip, sd4)[0]:+.1%} to {ci(dip, sd4)[1]:+.1%})
8-week net orders:   {a_n - c_n:+,.0f} orders ({net:+.1%}, 95% interval {ci(net, sd8)[0]:+.1%} to {ci(net, sd8)[1]:+.1%})

Realised discount implied by revenue: {disc:.0%} (headline 40% on selected lines)
Contribution margin per outdoor-furniture order: {cm_reg:.0%} of regular net price -> {cm_promo:.0%} when discounted
Break-even lift (orders needed just to keep margin flat): {breakeven_lift:+.0%}  vs observed {lift:+.0%}

8-week effect vs no promo (promo markets, outdoor furniture):
  Net revenue:          EUR {rev_eff:,.0f}
  Contribution margin:  EUR {cm_net:,.0f}  ({cm_net / cm_base:+.1%} of baseline margin; range EUR {cm_lo:,.0f} to {cm_hi:,.0f} from the lift interval)
"""
print(res); open("analysis/discount_results.txt", "w").write(res)

# chart
x = np.array(pd.to_datetime(weeks)); r0 = A[PRE].sum() / B[PRE].sum(); lo, hi = max(P0 - 14, 0), min(D1 + 8, N)
fig, ax = plt.subplots(1, 2, figsize=(13, 4.6), gridspec_kw={"width_ratios": [2.2, 1]})
ax[0].plot(x[lo:hi], A[lo:hi], color="#1F3A5F", lw=1.8, label="Promo markets: actual orders")
ax[0].plot(x[lo:hi], r0 * B[lo:hi], color="#C0392B", lw=1.8, ls="--", label="Counterfactual (no promo)")
ax[0].axvspan(x[P0], x[P1], color="#F4D03F", alpha=.3, label="Promo"); ax[0].axvspan(x[D0], x[D1], color="#AAB7B8", alpha=.3, label="Follow-up (pull-forward)")
ax[0].set_title("Outdoor-furniture orders, DE+AT+FR+NL"); ax[0].legend(frameon=False, fontsize=8, loc="upper left"); ax[0].set_ylabel("orders per week")
labels = ["Promo\nweeks", "Follow-up\nweeks", "8-week\nnet"]
cmv = [(a_p * cm_promo - c_p * cm_reg) * P_net, (a_d - c_d) * cm_reg * P_net, cm_net]
ax[1].bar(labels, [v / 1e3 for v in cmv], color=["#1F3A5F" if v >= 0 else "#C0392B" for v in cmv]); ax[1].axhline(0, color="k", lw=.8)
ax[1].set_title("Contribution margin vs no promo (EUR k)")
for a in ax: a.spines[["top", "right"]].set_visible(False)
plt.tight_layout(); plt.savefig("analysis/discount.png", dpi=150)
