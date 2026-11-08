# Budget Recommendation Memo

**To:** Head of Marketing, Country Managers (DE, AT, FR, NL, UK, SE)
**From:** Marketing Analytics
**Date:** 26 October 2026
**Updated:** 8 November 2026
**Re:** Where the next euro should go (simulated data, fictional brand "Nordvik Outdoor")

## Recommendation in brief
Move about **€1.9M (8% of the €22.5M budget)** out of Meta and TikTok, put roughly half into Google non-brand and Affiliates in small steps, hold the rest as margin, and stop broad discounting. Treat all of it as a staged test, because only one channel has been measured properly.

## What the evidence says
Break-even ROAS is **1.8** (55% contribution margin before marketing). Platform numbers overstate; attribution is not incrementality.

| Channel | Spend / yr | Platform ROAS | Last non-direct ROAS (90d, journey sim)** | Simulated true iROAS* | Tested? |
|---|---|---|---|---|---|
| Google | €9.1M (41%) | 5.0 | 3.7 | 3.6 | No |
| Meta | €6.5M (29%) | 2.4 | 2.0 | 1.5 | **Yes: holdout 2.45, range 1.0 to 3.9** |
| Affiliates | €2.7M (12%) | 4.2 | 1.5 | 3.0 | No |
| TikTok | €1.8M (8%) | 2.0 | 1.7 | 0.7 | No |
| SEO | €1.8M (8%) | n/a | 8.0 | 4.8 | No |
| Email | €0.5M (2%) | 17.1 | 26.6 | 11.9 | No |

*Validation only. Realised incremental ROAS in the simulated data (planted values: Google 3.6, Meta 1.5, Affiliates 3.0, TikTok 0.7, SEO 4.8, Email 12.0). It is known only because the data is simulated; a real analyst cannot see it.

**What the analyst now sees: model-credited ROAS (credited revenue / spend) under GA4-style last non-direct click with a 90-day lookback, from the user-journey simulation (observed paths after consent loss). It covers the year-1 cohort only (first touches Oct 2024 to Oct 2025), not the two-year average in the other columns. It is **not incremental**: it is wrong in both directions (Affiliates 1.5 vs true 3.0, Email 26.6 vs 11.9), so the Google, TikTok, Affiliates, SEO and Email readings still need the tests listed below. See `docs/attribution_findings.md`.

- **Meta** is real (it drives about 7% of German orders) but unproven as profitable. Its platform ROAS (2.4) and last non-direct ROAS (2.0) read profitable, the holdout range (1.0 to 3.9) spans break-even, and the simulated true iROAS (1.5) is below it. The next euro earns less than the average one.
- **TikTok** does not clear break-even on any lens except its own dashboard.
- **Discount:** the spring promo lifted outdoor-furniture orders about 24%, but needed +77% to break even, and cost roughly **€1.2M of margin** over 8 weeks.

## Actions
| # | Action | Size | Expected effect (per year) |
|---|---|---|---|
| 1 | Cut Meta, phased over 8 weeks | -15% (-€1.0M) | +€0.3M to +€0.7M margin in most cases |
| 2 | Cut TikTok, keep a small test budget in two markets | -50% (-€0.9M) | +€0.1M to +€0.7M |
| 3 | Reinvest half of the freed budget in Google non-brand and Affiliates, in +10% steps | +€0.95M | Modest gain, unproven |
| 4 | Stop broad discounting, keep targeted offers | n/a | Avoids about €1.2M margin loss per 8-week event |
| 5 | Hold SEO and Email, fund only low-cost list and content growth | small | Highest returns, little room to scale |

**Note on action 3 (Affiliates):** the Affiliates reinvestment rests on platform ROAS (4.2) and the simulated truth (3.0). The analyst's model-credited view puts Affiliates below break-even under all 8 attribution models (0.6 to 1.7; see `docs/attribution_findings.md`, finding 1), so reinvest in Affiliates only after a test (next test 4).

## Next tests (in order)
1. Repeat the Meta holdout in two markets for longer, to narrow the 1.0 to 3.9 range.
2. Geo test on TikTok, using the cut in action 2.
3. Brand-search holdout on Google, to see how much of its return would happen anyway.
4. Affiliates test (pause content/review partners in one market).

## Assumptions and risks
- **Diminishing returns are assumed, not measured:** the effect estimates assume the marginal euro earns about 0.5 to 0.8 times the average. If returns do not diminish, the Meta cut can lose money, but only if Meta's true return is at the top of its range.
- **One noisy test:** the Meta holdout interval is wide, so judge the results of the cut after about 90 days, not after a month, because buying takes 30 to 90 days.
- **Halo effects:** Meta may feed Google and SEO searches, which the test does not isolate.
- **Tracking:** consent loss in DE and AT (about 30% of sessions untracked) may understate results there. Tracking quality has not been audited yet.
- **Timing:** it is off-season, so it is a lower-risk moment to cut.
- **Costs:** all margin figures use the 70% gross margin and 15% variable cost assumption.
