# Answer key (DO NOT OPEN until Step 4 is finished)

Planted effects in `data/simulated_weekly_data.csv`. Seed 42. Values below are the model's true effects (expected values, no sampling noise).

## 1. Meta geo holdout (DE, weeks 2026-05-11 to 2026-07-27, 12 weeks)
- Meta spend set to zero in DE; all other markets run Meta as normal.
- True average incremental ROAS of Meta: **1.5** (net revenue / spend). Platform-reported ROAS: **2.4**. Platform overstatement: about 60%.
- Diminishing returns exponent (beta): 0.5 (the marginal euro earns about half the average).
- Orders from clicks arrive after a right-skewed log-normal delay (median 31 days, sigma 0.65, truncated at 13 weeks, about 60% of orders within 5 weeks). The revenue drop therefore builds quickly but fades slowly and continues for up to 12 weeks after restart. Measure the effect over weeks 2026-05-11 to 2026-10-19.
- True revenue lost in DE from the pause (holdout window + 12 weeks): about **EUR 1,322,211**, about 5.2% of revenue in that period.

## 2. Discount (outdoor furniture only)
- Markets with promo: DE, AT, FR, NL. No promo in UK and SE (natural control).
- Weeks 2026-03-02 to 2026-03-23 (4 weeks): outdoor-furniture orders x1.3; realised average discount 25% (headline 40% on selected lines).
- Weeks 2026-03-30 to 2026-04-20 (4 weeks): pull-forward dip, orders x0.9.
- True extra outdoor-furniture orders during promo: **545**; lost in the dip: **-208**; net over 8 weeks: **337** (+8.6% vs no promo).
- True net revenue effect over the 8 weeks (promo markets): **EUR -739,194** (-4.5%) because of the 25% price cut.
- True outdoor-furniture **contribution margin** effect over the 8 weeks (promo markets, before marketing): **EUR -1,183,927** (-18.9%). The extra orders earn far less margin each, so the promo destroys value even though orders rise.

## 3. Channel truth (average incremental ROAS vs platform-reported ROAS)
| Channel | Spend share | True iROAS | Reported ROAS |
|---|---|---|---|
| Google | 40% | 3.6 | 5.0 |
| Meta | 30% | 1.5 | 2.4 |
| Affiliates | 12% | 3.0 | 4.2 |
| TikTok | 8% | 0.7 | 2.0 |
| SEO | 8% | 4.8 | n/a |
| Email | 2% | 12.0 | 17.0 |

Break-even ROAS on contribution margin: 1 / 0.55 = about 1.8. Google, Affiliates, SEO, Email clear it on a true incremental basis; Meta and TikTok do not. Meta's reported ROAS (2.4) sits above break-even, so the dashboard says 'profitable' while the truth says 'loss-making'.

## 4. Other design choices
- Attribution: platform_reported_revenue is dated by click week; orders and revenue are dated by order week.
- Direct_Other is the non-marketing base (brand, direct, word of mouth), about 41% of revenue.
- No tracking errors are planted yet. They are added in the tracking-quality step.

## 5. Calibration check (annualised)
Net revenue EUR 114.3M; marketing spend EUR 22.47M (19.7%); MER 5.09; orders about 31,904 per year.
