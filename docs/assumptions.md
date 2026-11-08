# Assumptions

**Project:** "Where should the next euro go?" A measurement and budget-decision case study for a premium D2C outdoor-living brand.

> **All data in this project is simulated.** The brand is fictional ("Nordvik Outdoor") and is not meant to be identifiable as any real company.  

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

## 2. Markets  

| Market | Share of revenue | VAT | Consent behaviour (assumed) |
|---|---|---|---|
| DE | 40% | 19% | Strict, ~30% of sessions untracked |
| FR | 16% | 20% | Moderate, ~20% untracked |
| NL | 14% | 21% | Moderate, ~20% untracked |
| AT | 12% | 20% | Strict, ~30% untracked |
| UK | 10% | 20% | Moderate, ~15% untracked |
| SE | 8% | 25% | Lenient, ~10% untracked |

## 3. Channels and baseline budget (assumed)

Marketing spend is **20% of net revenue (~€23M per year)**.  
Baseline split: **Google 40%** (Search, Shopping, PMax), **Meta 30%**, **Affiliates 12%**, **TikTok 8%**, **SEO 8%** (content and agency), **Email 2%** (tooling). A seventh row, **Direct_Other**, holds revenue not driven by marketing (brand, direct, word of mouth), about 41% of the total.

## 4. Unit economics

| Item | Assumption | Basis |
|---|---|---|
| Gross margin | **70%** of net revenue | Treated as **product-level** (net revenue less cost of goods only), with delivery and returns costs shown separately below. 70% implies a premium, own-design brand |
| Variable costs | **15%** (delivery, payment fees, returns handling) | Bulky delivered goods |
| **Contribution margin before marketing** | **55%** (~€1,980 per order) | 70% - 15% |
| Cancellations / refunds | **5% combined**, both products | Pre-delivery cancellations 2 to 5% (buyer's remorse, planning hurdles) and post-delivery refunds 1 to 2%. Made-to-order, installed items return far less than common outdoor furniture. **Revenue in the dataset is already net of cancellations** |
| Repeat purchase | **0%**: each order is a new customer | Orders are high-ticket, one-off purchases, and the net order value (~€3,600) already blends outdoor furniture and summer houses. So orders = new customers, CAC = marketing spend / orders, and lifetime value equals first-order value |
| Conversion | ~1% of sessions order; ~3% request a quote or use the configurator | |

## 5. Customer journey

- High-ticket buying window: **30 to 90 days** from click to order. Orders follow a right-skewed (log-normal) curve, not an even spread: **median 31 days** from the click that triggers the order, about 95% of orders within 90 days, and a long tail of late buyers. The weekly dataset truncates this lag at 91 days.
- Compare attribution windows of 7, 30 and 90 days. A 7-day window misses most orders.

**Attribution extension (user-journey simulation, `generate_journeys.py`).** Simulated people with several touches each, used to compare attribution models with a counterfactual truth (`docs/attribution_findings.md`). Its journey assumptions:
- **Causing touch vs first click.** The 31-day median runs from the *causing* touch (the touch that triggers the order). Measured from the *first* click, the median is longer: about **43 days for self-serve orders and 50 days overall**, because the causing touch is often not the first one. About 90% of self-serve orders and 81% of all orders arrive within 90 days of the first click.
- **Two path types.** *Self-serve*: click → order, lag as above (truncated at 91 days). *Lead path*: click → `quote_request` → order (all summer houses and about 11% of outdoor furniture). The quote-to-order delay has a long tail of **up to 365 days** (median about 60 days). **Only the lead path in the journey simulation uses the 365-day tail; the 91-day truncation still applies everywhere else, and the weekly dataset is unchanged.**
- **Consent loss is per person** at the rates in section 2 (DE/AT 30%, FR/NL 20%, UK 15%, SE 10%): all touches of an untracked person are missing from the observed paths. Orders and quote requests are always recorded (server-side / CRM).
- **Cohort.** First touches in the first 52 weeks (28 Oct 2024 to 26 Oct 2025), orders followed to 25 Oct 2026. Spend is the weekly dataset's year-1 spend; true iROAS follows the planted values in direction.

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
| `net_revenue_eur` | Net of VAT and cancellations, by order week. By channel, this is the revenue the channel **caused** (the simulation's truth); a real analytics tool could not split revenue this way |
| `platform_reported_revenue_eur` | What the ad platform claims, by **click week** (blank for SEO and Direct_Other) |
| `data_origin` | Always `simulated` here |

## 10. Out of scope

Live ad accounts, real customer data, creative-level analysis, and the full 14-market footprint.
