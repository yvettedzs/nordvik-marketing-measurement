# Where should the next euro go? Marketing measurement case study

A portfolio project on a **fictional premium D2C outdoor-living brand ("Nordvik Outdoor")**. It asks where marketing spend should go across channels and markets, using incrementality tests, a metric dictionary and a budget memo.

> **All data is simulated.** The brand, markets, prices and results are fictional and not drawn from any real company. Effect sizes are planted in the data on purpose, so the methods can be checked against a known answer.

## Headline findings (simulated data)

| Question | Method | Result |
|---|---|---|
| Is Meta's reported ROAS real? | 12-week geo holdout in Germany, synthetic control, outcome = orders | Pausing Meta cut German orders by about 7% (95% interval 3% to 11%). Incremental ROAS 2.45 (range 1.0 to 3.9) against break-even 1.8, so Meta is real but **not proven profitable** |
| Did the spring discount pay off? | Promo vs no-promo markets, outcome = orders, then contribution margin | Real lift about +24% (naive pre/post showed +49%), then a -10% pull-forward dip. It needed about +77% to break even, and cost roughly **EUR 1.2M of margin** over 8 weeks |
| Where should the next euro go? | Budget memo | Trim Meta and TikTok, reinvest part in Google non-brand and Affiliates in small steps, stop broad discounting, and run follow-up tests |

## Repository contents

| Path | What it is |
|---|---|
| `docs/assumptions.md` | Business, market and unit-economics assumptions |
| `docs/metric_dictionary.md` | CAC, ROAS, MER, contribution margin, payback, with a worked example of misleading platform ROAS |
| `docs/budget_memo.md` | One-page recommendation to marketing leadership |
| `docs/answer_key.md` | The planted effects, kept to validate the analysis afterwards |
| `generate_data.py` | Creates the simulated weekly dataset (seed 42) |
| `data/` | `simulated_weekly_data.csv` (week x market x channel) and `events_calendar.csv` |
| `analysis/` | Meta holdout and discount analyses, with charts and result text |
| `sql/` | Tracking-quality SQL checks (in progress) |

## How to reproduce

```
pip install -r requirements.txt
python generate_data.py                   # regenerates data/ and docs/answer_key.md
python analysis/01_meta_holdout.py        # Meta geo holdout
python analysis/02_discount_prepost.py    # discount analysis
```
Run all commands from the repository root.

## Related

- Tracking demo (GTM + GA4, fictional shop): https://github.com/yvettedzs/nordvik-tracking-demo

## Limits

Simulated data, one noisy holdout, assumed diminishing returns and no live ad accounts. See the budget memo for the risks.
