# Metric Dictionary

**Purpose:** one agreed definition for each metric, so every dashboard and recommendation in this project uses the same numbers.
**Scope:** a high-ticket D2C brand selling outdoor furniture (~€3,500) and summer houses (~€9,000). All figures are simulated and illustrative, see `assumptions.md`.
**Conventions:** revenue is **net of VAT and after cancellations**. Spend is excluding VAT. Weekly grain, EUR.

## Base reference numbers (from `assumptions.md`)

| Item | Value |
|---|---|
| Net revenue | ~€115M per year |
| Marketing spend | ~€23M per year (20% of net revenue) |
| Orders | ~32,000 per year; every order is a new customer (no repeat purchases) |
| Net order value | ~€3,600 |
| Gross margin | 70% (product-level) |
| Contribution margin before marketing | 55% (~€1,980 per order) |

## 1. CAC (Customer Acquisition Cost)

- **Definition:** total marketing spend / number of **new** customers.
- **Includes:** media, agency and content fees, marketing tools. **Excludes:** sales staff salaries and discounts (reported separately).
- **Two versions:** *blended CAC* (all spend, all new customers) and *paid CAC* (paid media spend, new customers from paid channels).
- **Example:** €23M / 32,000 new customers = **~€720**.
- **High-ticket note:** a customer who clicks today orders within a **30 to 90 day** window (median 31 days, long right tail). Match spend to the orders it produces later, or CAC looks too high in growth weeks and too low in quiet ones.
- **Common misuse:** comparing CAC to revenue instead of contribution margin.

## 2. ROAS (Return on Ad Spend)

- **Definition:** attributed net revenue / ad spend, for one channel.
- **Source:** the ad platform's own report, restated to net revenue (platforms usually report gross of VAT and cancellations).
- **Example:** €418k attributed revenue on €174k spend = **2.4**.
- **Break-even ROAS** = 1 / contribution margin % before marketing = 1 / 0.55 = **~1.8**. Below this, the channel loses money on each order.
- **Limits:** each platform credits itself, windows and view-through rules differ, and platform numbers overlap. ROAS shows what a platform *claims*, not what it *caused*.

## 3. MER (Marketing Efficiency Ratio)

- **Definition:** total net revenue / total marketing spend, all channels, no attribution.
- **Example:** €115M / €23M = **~5.0** (the inverse is the 20% spend-to-revenue ratio).
- **Strength:** can't be double-counted, so it's the sanity check for platform numbers.
- **Limit:** it's an average, not a marginal result. It also includes sales that would happen without ads (SEO, direct, brand), so it can't tell you where the *next* euro should go.

## 4. Contribution Margin

- **Definition:** net revenue - COGS - variable costs (delivery, payment fees, returns handling).
- **Before marketing:** 55% of net revenue (70% gross margin less 15% variable costs), **~€1,980 per order**.
- **After marketing:** 55% - 20% = **35%**. Blended, per order: €1,980 - €720 = **~€1,260**.
- **Excludes:** fixed costs (salaries, rent, software).
- **Why it matters:** revenue-based metrics hide the fact that a €9,000 summer house and a €3,500 outdoor furniture set carry different margins, and that discounts cut margin far more than revenue.

## 5. Payback

- **Ratio:** contribution margin on the first order / CAC = €1,980 / €720 = **~2.8x**.
- **Time:** days from the first paid touch until cumulative contribution margin covers CAC. For this product the first order covers CAC, so payback time is mostly the **click-to-order lag (median 31 days)**, plus any delay before cash is collected.
- **High-ticket note:** there are no repeat purchases in this model (0%), so payback is purely a first-order question and lifetime value equals first-order value.

## Supporting metric: Incremental ROAS (iROAS)

- **Definition:** change in net revenue caused by a spend change / the spend change, measured by a holdout, geo test or pre/post analysis.
- **Why it's here:** it's the only metric that answers "what did the *extra* euro do?" The incrementality tests in Step 4 produce it.

## Worked example: why platform ROAS can mislead

**Situation:** the Meta dashboard shows ROAS 2.4, above the 1.8 break-even. The team raises Meta spend by 30% for one month.

| | Month A | Month B (Meta +30%) | Change |
|---|---|---|---|
| Meta spend | €580k | €754k | +€174k |
| Meta platform ROAS | 2.4 | 2.4 | none |
| Meta platform-attributed revenue | €1.39M | €1.81M | **+€418k** |
| Total marketing spend | €1,920k | €2,094k | +€174k |
| Total net revenue (all channels) | €9.60M | €9.72M | **+€120k** |
| MER | 5.00 | 4.64 | -0.36 |

**What each metric says**
- **Platform ROAS:** "Meta is at 2.4, above break-even. Spending more is clearly working."
- **MER:** efficiency fell from 5.00 to 4.64. A warning sign, but it doesn't say which channel is responsible.
- **iROAS (the truth):** extra revenue / extra spend = €120k / €174k = **0.7**, far below the 1.8 break-even.
- **Profit effect:** extra contribution margin = €120k x 55% = €66k, minus €174k extra spend = **about -€108k**. The "successful" scale-up lost money.

**Why platform ROAS missed it:** Meta claimed credit for sales that were already coming through Google, SEO, email and direct. Total revenue rose by less than a third of what Meta claimed.

**Lesson:** use platform ROAS to *manage* a channel day to day, MER to *monitor* the business, and iROAS from tests to *decide* where the next euro goes.

**Timing note:** because of the 30 to 90 day buying window, the revenue effect of a spend change has to be measured over about 90 days, not just the month of the change. A one-month view understates the lagged revenue and cannot see the full picture either way.

*The figures above are illustrative and are not the planted effects in the dataset. The real analysis in Step 4 uses the simulated data.*
