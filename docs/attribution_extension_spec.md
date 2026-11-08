# Attribution & conversion-lag extension – specification

Status: plan, to be implemented with Claude Code. Builds on the existing simulated data and assumptions in this project.

## 1. Core idea
Simulate **user-level journeys** in which the true causal effect of each channel is known. Then:
- apply attribution models as an analyst would;
- compare them with the truth.

**The headline result:** a table showing that attribution models disagree with each other and with incrementality, and showing which channels are the most "model-sensitive". Those channels are the ones to test.

## 2. How the simulation creates "truth" (the key design choice)
- Each simulated person has a **baseline purchase propensity**. Some would buy anyway (brand, direct, word of mouth).
- Channels add **exposures** (touchpoints with timestamps). Each touch adds a **true incremental lift** to the person's probability of buying.
- **Selection bias is built in on purpose:** retargeting and brand search reach people who already have a high propensity. This is what makes attribution over-credit them, as happens in reality.
- **True incremental orders per channel** come from counterfactual reruns: simulate again with that channel's touches removed, using the *same random numbers* (common random numbers), and take the difference. This is the defensible "ground truth".

## 3. Calibration (keep it consistent with the existing repo)
- Same 6 markets, same channels, same spend split, and the same true iROAS ranking (Google 3.6, Meta 1.5, Affiliates 3.0, TikTok 0.7, SEO 4.8, Email 12.0). Aim for the same *direction*, not exact values.
- **Two path types:**
  - **Self-serve:** click → order. Log-normal lag, median 31 days, sigma 0.65, as in the current repo.
  - **Lead path:** click → `quote_request` → order. The lead-to-order delay has a long tail of up to 365 days.

  ⚠️ The current repo truncates the lag at 91 days. The extension needs the 365-day tail for the lead path only. State this clearly in the docs.
- **Consent loss:** remove about 30% of touches in DE and AT, 20% in FR and NL, 15% in UK and 10% in SE from the *observed* paths. These are the existing Nordvik assumptions. The truth still uses the full paths.
- **Sample size:** about 100–300k simulated people, so it runs in under a minute on a laptop. Fixed seed: 42.

## 4. Attribution models to implement (Python, one function each)
1. Last click
2. Last non-direct click (GA4 "paid and organic last click" logic)
3. First click
4. Linear
5. Time decay (configurable half-life; show 7 vs 30 days)
6. U-shaped (40/20/40)
7. W-shaped (30/30/30 + 10; the middle anchor is the `quote_request` touch)
8. Not in this version: a data-driven proxy (Markov removal effect). List it as a next step in the findings.

**S-shape:** leave it out, and add a note in the findings: "S-shape is mentioned in practice, but no standard definition was found."

Every model is run with **lookback windows of 7, 30, 90 and 365 days**. Add a note that GA4's maximum is 90 days.

## 5. Cohort / lag analysis
- Cumulative conversion curves by **first-click week** and by **lead (quote) week**, at 7, 30, 90, 180 and 365 days.
- **Per channel:** the share of a cohort's final orders that is visible at day 30 vs day 365. This shows which channels look worse with short windows.
- **Payback note:** what CAC looks like when measured 30 days after spend vs 365 days after.

## 6. Outputs
| File | Content |
|---|---|
| `generate_journeys.py` | Journey simulation + counterfactual truth; writes `data/simulated_journeys.parquet` (or CSV) and `docs/answer_key_attribution.md` |
| `analysis/03_attribution_models.py` | All models × windows → `analysis/attribution_comparison.csv` + chart |
| `analysis/04_conversion_lag_cohorts.py` | Cohort curves → chart + results text |
| `docs/attribution_findings.md` | One-page write-up: the table, three findings, limits, "what I would do at a real company" |
| `tests/test_attribution.py` | Each model's credits add up to 100% of orders; known toy paths give hand-checked results |

**Main chart:** for each channel, credit share under each model, with true incremental share as a black marker.

## 7. Explicitly out of scope
Real data, any Markov or Shapley model, cross-device simulation, MMM, a Looker dashboard.

## Integration with the MCP server
- `compare_roas` in `mcp_server/server.py` has an `attributed_roas` placeholder. Once the models exist, fill it with ROAS by model and lookback window, reading from `analysis/attribution_comparison.csv`.
- Add tests that check these values against the CSV.
- Keep the existing rules: channel-level `net_revenue_eur` is incremental revenue, never "attributed".
