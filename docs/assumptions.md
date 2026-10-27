# Assumptions

**Project:** "Where should the next euro go?" A measurement and budget-decision case study for a premium D2C outdoor-living brand.

> **All data in this project is simulated.** The brand is fictional ("Nordvik Outdoor") and is not meant to be identifiable as any real company. Per-market revenue is not public, so every market weight and cost figure below is an illustrative assumption unless a source is given.

## 1. Business

| Item | Assumption |
|---|---|
| Brand | Nordvik Outdoor (fictional) |
| Products | **Outdoor furniture** (85% of orders) and **summer house** (15%) |
| Regular price, incl. VAT | Outdoor furniture €3,500; summer house €9,000 |
| Blended order value | ~€4,325 incl. VAT, ~€3,600 net of VAT |
| Scale | ~€115M net revenue per year across 6 markets (~€200M total across 14, DACH-weighted), ~32,000 orders per year (~615 per week) |
| Period | 104 weeks of weekly data, 28 Oct 2024 to 19 Oct 2026 |
| Currency | EUR everywhere (no FX effects) |
| Seasonality and growth | Peak March to July, trough December to January; ~8% annual growth |

## 2. Markets (6 of the real 14, to keep the simulation manageable)

| Market | Share of revenue | VAT | Consent behaviour (assumed) |
|---|---|---|---|
| DE | 40% | 19% | Strict, ~30% of sessions untracked |
| FR | 16% | 20% | Moderate, ~20% untracked |
| NL | 14% | 21% | Moderate, ~20% untracked |
| AT | 12% | 20% | Strict, ~30% untracked |
| UK | 10% | 20% | Moderate, ~15% untracked |
| SE | 8% | 25% | Lenient, ~10% untracked |

## 3. Channels and baseline budget (assumed, not sourced)

Marketing spend is **20% of net revenue (~€23M per year)**, set by you after checking several sources. Baseline split: **Google 40%** (Search, Shopping, PMax), **Meta 30%**, **Affiliates 12%**, **TikTok 8%**, **SEO 8%** (content and agency), **Email 2%** (tooling). A seventh row, **Direct_Other**, holds revenue not driven by marketing (brand, direct, word of mouth), about 41% of the total.

## 4. Unit economics

| Item | Assumption | Basis |
|---|---|---|
| Gross margin | **70%** of net revenue | Set by you after checking several sources. Treated as **product-level** (net revenue less cost of goods only), with delivery and returns costs shown separately below. The generic home-goods benchmarks I found were lower (about 30 to 56%, [Eightx](https://eightx.co/blog/home-goods-financial-benchmark)), so 70% implies a premium, own-design brand |
| Variable costs | **15%** (delivery, payment fees, returns handling) | Judgement: bulky delivered goods |
| **Contribution margin before marketing** | **55%** (~€1,980 per order) | 70% - 15% |
| Cancellations / refunds | **5% combined**, both products | Set by you: pre-delivery cancellations 2 to 5% (buyer's remorse, planning hurdles) and post-delivery refunds 1 to 2%. Generic online furniture returns run much higher (~22.7%, [Eightx](https://eightx.co/blog/average-furniture-and-home-return-rate-benchmarks)), but made-to-order, installed items return far less. **Revenue in the dataset is already net of cancellations** |
| Repeat purchase | **0%**: each order is a new customer | Set by you. Orders are high-ticket, one-off purchases, and the net order value (~€3,600) already blends outdoor furniture and summer houses. So orders = new customers, CAC = spend / orders, and lifetime value equals first-order value |
| Conversion | ~1% of sessions order; ~3% request a quote or use the configurator | Judgement |

## 5. Customer journey

- High-ticket buying window: **30 to 90 days** from first click to order. Orders follow a right-skewed (log-normal) curve, not an even spread: **median 31 days**, about 95% of orders within 90 days, and a long tail of late buyers.
- Compare attribution windows of 7, 30 and 90 days. A 7-day window misses most orders.

## 6. Conventions

- **Revenue is net of VAT and after cancellations.** Spend is excluding VAT.
- **ROAS** = platform-attributed net revenue / spend. **MER** = total net revenue / total marketing spend. **CAC** = spend / new customers. Details in `metric_dictionary.md`.
- Weekly grain, Monday start, one row per market, channel and week.
- Event names and parameters follow GA4 e-commerce naming where possible.
- `data_origin` marks each table as `simulated`, `sample` or `own`.
- Fixed random seed (42), so results are reproducible.

## 7. Questions the project answers (ranked)

1. Where should the next euro of media spend go across channels and markets?
2. Is Meta's reported ROAS overstated, and by how much, once measured incrementally?
3. Did the discount create real extra demand, or mostly pull forward and discount sales?
4. How does the long buying window distort channel performance and payback?
5. How much of reported performance is a tracking artifact, and does it change the decisions above?

## 8. Planted events

Two events are built into the data: a **spring discount on outdoor furniture** (headline 40% off selected lines) and a **Meta holdout** in one market. Their dates and markets are in `data/events_calendar.csv`. Their true effect sizes are in `docs/answer_key.md`, which stays unopened until the analysis (Step 4) is finished. Tracking errors are added in a later step.

## 9. Dataset (`data/simulated_weekly_data.csv`, 4,368 rows)

| Column | Meaning |
|---|---|
| `week_start` | Monday of the week |
| `market`, `channel` | 6 markets; 6 marketing channels plus `Direct_Other` |
| `spend_eur` | Media or channel spend, ex-VAT |
| `sessions` | Visits attributed to the channel, by visit week |
| `orders`, `orders_outdoor_furniture`, `orders_summer_house` | Orders by **order week** |
| `net_revenue_eur` | Net of VAT and cancellations, by order week |
| `platform_reported_revenue_eur` | What the ad platform claims, by **click week** (blank for SEO and Direct_Other) |
| `data_origin` | Always `simulated` here |

## 10. Out of scope

Live ad accounts, real customer data, creative-level analysis, and the full 14-market footprint.
