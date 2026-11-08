# Where should the next euro go? Marketing measurement case study

A portfolio project on a **fictional premium D2C outdoor-living brand ("Nordvik Outdoor")**. It asks where marketing spend should go across channels and markets, using incrementality tests, a metric dictionary and a budget memo.

> **All data is simulated.** The brand, markets, prices and results are fictional and not drawn from any real company. Effect sizes are planted in the data on purpose, so the methods can be checked against a known answer.

## Headline findings (simulated data)

| Question | Method | Result |
|---|---|---|
| Is Meta's reported ROAS real? | 12-week geo holdout in Germany, synthetic control, outcome = orders | Pausing Meta cut German orders by about 7% (95% interval 3% to 11%). Incremental ROAS 2.45 (range 1.0 to 3.9) against break-even 1.8, so Meta is real but **not proven profitable** |
| Did the spring discount pay off? | Promo vs no-promo markets, outcome = orders, then contribution margin | Real lift about +24% (naive pre/post showed +49%), then a -10% pull-forward dip. It needed about +77% to break even, and cost roughly **EUR 1.2M of margin** over 8 weeks |
| Do attribution models agree with incrementality? | User-journey simulation with counterfactual truth (250,000 people, one-year cohort); 8 attribution model variants x lookback windows of 7 to 365 days | No. They disagree with each other and with the truth **in both directions**: TikTok and SEO are over-credited by every model, Affiliates under-credited by every model, and channel totals hide sub-channel bias (Google brand 2.6x its true share under last click, Google generic 0.17x). Email, TikTok, Affiliates and Meta are the most model-sensitive, so they are the ones to test. A 30-day window sees only 26% of a cohort's orders. See `docs/attribution_findings.md` |
| Where should the next euro go? | Budget memo | Trim Meta and TikTok, reinvest part in Google non-brand and Affiliates in small steps, stop broad discounting, and run follow-up tests |

## Repository contents

| Path | What it is |
|---|---|
| `docs/assumptions.md` | Business, market and unit-economics assumptions |
| `docs/metric_dictionary.md` | CAC, ROAS, MER, contribution margin, payback, with a worked example of misleading platform ROAS |
| `docs/budget_memo.md` | One-page recommendation to marketing leadership |
| `docs/answer_key.md` | The planted effects, kept to validate the analysis afterwards |
| `docs/attribution_extension_spec.md` | Specification of the attribution and conversion-lag extension |
| `docs/attribution_findings.md` | One-page findings: attribution models vs incrementality, conversion lag and payback |
| `docs/answer_key_attribution.md` | The journey simulation's planted truth and calibration check |
| `generate_data.py` | Creates the simulated weekly dataset (seed 42) |
| `generate_journeys.py` | Creates the simulated user journeys with counterfactual truth (seed 42) |
| `data/` | `simulated_weekly_data.csv` (week x market x channel), `events_calendar.csv`, `simulated_journeys.csv.gz` (user-level touches, quote requests and purchases) and `journey_truth_by_channel.csv` |
| `analysis/` | Meta holdout and discount analyses; attribution models vs truth (`03_attribution_models.py`) and conversion-lag cohorts (`04_conversion_lag_cohorts.py`), with charts and result text |
| `sql/` | Four tracking-quality SQL checks on the weekly dataset (DuckDB), also callable through the MCP server |
| `mcp_server/` | Read-only MCP server so Claude answers with the agreed metric definitions and data (6 tools, tested in `tests/`) |

## How to reproduce

```
pip install -r requirements.txt
python generate_data.py                   # regenerates data/ and docs/answer_key.md
python analysis/01_meta_holdout.py        # Meta geo holdout
python analysis/02_discount_prepost.py    # discount analysis
python generate_journeys.py               # user journeys + truth, docs/answer_key_attribution.md (~1-2 min)
python analysis/03_attribution_models.py  # attribution models x lookback windows vs truth
python analysis/04_conversion_lag_cohorts.py   # conversion-lag cohorts and payback
python -m pytest tests                    # all tests (add -m "not slow" to skip the slow ones)
```
Run all commands from the repository root.

## Related

- Tracking demo (GTM + GA4, fictional shop): https://github.com/yvettedzs/nordvik-tracking-demo

## Limits

Simulated data, one noisy holdout, assumed diminishing returns and no live ad accounts. See the budget memo for the risks.
