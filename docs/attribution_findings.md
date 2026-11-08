# Attribution and conversion lag: findings

> **Simulated data, fictional brand ("Nordvik Outdoor").** 250,000 simulated people, one-year cohort (first touches 28 Oct 2024 to 26 Oct 2025, orders followed to 25 Oct 2026), 30,214 orders. The true effect of each channel comes from counterfactual reruns with common random numbers (`generate_journeys.py`, `docs/answer_key_attribution.md`). Details: `analysis/attribution_results.txt`, `analysis/conversion_lag_results.txt`.

## The table

Share of orders credited to each channel (observed paths after consent loss, 90-day lookback) vs the true incremental share.

| Channel | **True** | Last click | Last non-direct | First click | Linear | Time decay 7d | Time decay 30d | U-shaped | W-shaped | Credited ÷ true |
|---|---|---|---|---|---|---|---|---|---|---|
| Google | **29.2%** | 21.7% | 30.2% | 24.0% | 22.6% | 21.6% | 22.2% | 22.8% | 23.0% | 0.74 to 1.03 |
| Meta | **8.9%** | 5.2% | 12.4% | 14.5% | 14.2% | 9.4% | 12.8% | 11.2% | 11.4% | 0.59 to 1.63 |
| Affiliates | **7.1%** | 1.5% | 3.7% | 4.2% | 3.5% | 2.6% | 3.3% | 3.0% | 3.1% | 0.21 to 0.60 |
| TikTok | **1.1%** | 1.2% | 2.9% | 6.2% | 4.6% | 2.4% | 3.9% | 4.0% | 4.1% | 1.10 to 5.67 |
| SEO | **7.8%** | 10.0% | 13.2% | 14.0% | 10.8% | 9.7% | 10.3% | 11.6% | 11.7% | 1.24 to 1.79 |
| Email | **4.9%** | 7.7% | 10.8% | 1.3% | 5.5% | 7.4% | 6.3% | 4.8% | 4.8% | 0.26 to 2.21 |
| Direct_Other | **41.0%** | 52.7% | 26.9% | 35.9% | 38.7% | 47.0% | 41.3% | 42.5% | 42.0% | 0.66 to 1.29 |

**Most model-sensitive** (highest ÷ lowest share across the 8 variants): **Email 8.6x, TikTok 5.2x, Affiliates 2.9x, Meta 2.8x**. These are the channels to test. Google and SEO are stable across models (1.4x), but stable is not the same as right: SEO is over-credited by every model.

Charts: `analysis/attribution_by_model.png` (main chart, true share as a black line), `analysis/attribution_by_window.png`, `analysis/conversion_lag_cohorts.png`.

## Three findings

### 1. Attribution errs in both directions, and channel totals can hide sub-channel bias
- **Over-credited:** TikTok and SEO by every model (TikTok up to 5.7x). Email under last-click-type models (2.2x under last non-direct).
- **Under-credited:** Affiliates by every model (0.21x to 0.60x). Google by every model except last non-direct.
- **Inside the channels**, the bias is larger than the totals suggest:

  | Campaign type | True | Last click | Last non-direct | First click | Linear |
  |---|---|---|---|---|---|
  | Google brand | 6.8% | 17.9% (2.6x) | 21.3% (3.1x) | 1.9% | 8.3% |
  | Google generic | 22.4% | 3.8% (0.17x) | 8.8% (0.39x) | 22.1% | 14.3% |
  | Meta prospecting | 6.0% | 2.6% | 6.2% | 13.4% (2.2x) | 9.6% |
  | Meta retargeting | 2.8% | 2.6% | 6.1% (2.2x) | 1.1% | 4.5% |

  Last non-direct puts Google almost exactly on its true share (1.03x), but only because brand (3.1x) and generic (0.39x) errors cancel out. Brand search reaches people who would buy anyway and takes the last click; generic search does the work earlier in the journey.
- **Affiliates in this simulation behave like content/review partners:** few, mid-journey, high-impact touches. They have the fewest touches of any channel and the highest lift per touch, and their touches sit a median 35 days before the order. Position-based models cannot see how much one touch does, so every model under-credits them. **Voucher/cashback affiliates typically behave the opposite way:** late touches just before checkout, over-credited by last click. Which kind of affiliate you have matters more than which model you pick.
- **Design choice that drives the last-click results:** 70% of orders have a zero-lift *navigational* session just before purchase (Direct 45%, Google brand 30%, SEO 15%, Email 10%). This is why last click gives Direct_Other 52.7% and Google brand 2.6x its true share. The pattern is realistic, but its size is an assumption of the simulation.

### 2. A model choice can flip the profit verdict
Break-even ROAS is 1.82.
- **Meta:** true iROAS **1.46** (loss-making). Five of the 8 variants put it above break-even: last non-direct 1.99, first click 2.31, linear 2.27, 30-day time decay 2.03, W-shaped 1.83. Only last click (0.83), 7-day time decay (1.47) and U-shaped (1.79) put it below.
- **TikTok:** true **0.70**. First click shows 3.62 and linear 2.68.
- **Affiliates**, the reverse: true **2.92** (profitable), but **all 8 variants put it below break-even** (0.59 to 1.70).

The same data, read with a different model, gives the opposite budget decision. So verdicts on Meta, TikTok and Affiliates need incrementality tests, not a better attribution model.

### 3. Short windows hide most orders, and they hide them unevenly
- **Lag:** from the first click, a 30-day view sees **26%** of a cohort's 365-day orders (self-serve 32%, lead path **9%**). 90 days sees 81%. Lead-path orders keep arriving until day 365: quote to order has a median of 58 days, and 11% of these orders come more than 180 days after the quote.
- **Payback:** blended CAC measured 30 days after the first click is **€2,789** (payback ratio 0.62, which looks loss-making). After 90 days it is €903, and after 365 days **€729** (2.72).
- **Uneven by channel:** by *true causing* channel, the share of orders visible at day 30 is Email 2%, Affiliates 9%, Meta 14%, Google 17%, TikTok 18%, SEO 21% and baseline 42%. Late-path channels look worst on short windows. Their 30-day incremental CAC is 42x (Email) and 11x (Affiliates) their 365-day CAC. By *first-click* channel, all channels look alike (24% to 28%), and **email never starts a journey** (it needs an earlier visit), so it does not appear as a first-click channel at all.
- **Lookback and consent move credit too:** under last non-direct, Direct_Other gets 56% with a 7-day lookback and 24% with 365 days. Consent loss alone moves Direct_Other from 4% (full paths) to 27% (observed paths).

## Method notes
- 8 model variants (7 models; time decay at 7- and 30-day half-lives) × lookback windows of 7, 30, 90 and 365 days × observed and full paths. Every order hands out exactly 100% of its credit; tested for every combination. **GA4's maximum lookback window is 90 days**; 365 days is shown for comparison only.
- W-shaped: 30/30/30 + 10. The middle anchor is the last touch at or before the `quote_request`; self-serve orders fall back to U-shaped.
- **S-shape is mentioned in practice, but no standard definition was found**, so it is left out.
- Lags: median 31 days from the *causing* touch (as in the weekly dataset); from the *first* click, 43 days self-serve and 50 days overall. The 365-day tail applies to the lead path only (`assumptions.md`, section 5).

## Limits
- Simulated: the truth is built in, with one seed (42). The results depend on design choices: how strongly each channel reaches people who would buy anyway, the 70% navigational sessions, the affiliate type, and per-person consent loss.
- Clicks only: no view-through, no cross-device. No halo: removing Meta does not reduce later brand searches, so channel effects add up exactly. In reality channels interact.
- True iROAS is an average at year-1 spend; there are no diminishing returns at user level, so the table says nothing about the *next* euro.
- One-year cohort, not the 104-week weekly dataset: compare the ROAS here with the journey truth, not with the weekly simulation's iROAS.
- **Not in this version:** a data-driven proxy (Markov removal effect). That is the next step. Shapley values are out of scope.

## What I would do at a real company
1. **Use attribution to manage within a channel, not to split the budget across channels.** Report ROAS under two or three models side by side, and treat channels that move a lot between models (here Email, TikTok, Affiliates and Meta) as unknown until tested.
2. **Rank incrementality tests by model sensitivity × spend:** Meta first (large spend, and the verdict flips with the model), then TikTok and Affiliates, plus a brand-search holdout for Google brand.
3. **Report by campaign type and partner type before drawing conclusions:** brand vs generic, prospecting vs retargeting, content/review vs voucher/cashback affiliates.
4. **Judge spend changes on cohorts with at least 90 days of follow-up** (365 days for quote-led products). Always state the measurement horizon next to CAC, and track quote-to-order separately.
5. **Measure consent loss per market** and model the untracked share explicitly, instead of letting it fall into Direct.
6. **Next step:** build the Markov removal-effect model and validate it against this simulation's truth before using it on real data.
