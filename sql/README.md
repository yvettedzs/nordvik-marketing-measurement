# SQL data-quality checks

Four checks on the simulated weekly dataset (`data/simulated_weekly_data.csv`), written for DuckDB. Each file starts with a comment saying what it checks, the rule and what to do with a flag.

| File | Question | What it returns on this dataset |
|---|---|---|
| `01_platform_vs_analytics_gap.sql` | How much more revenue do the ad platforms claim than analytics records? | TikTok and Meta FAIL (platform claims 2.8x and 1.6x the analytics revenue). Google, Affiliates and Email WARN (about 1.4x) |
| `02_weekly_volume_anomalies.sql` | Did any market's orders drop sharply against its own recent level? | A few autumn weeks in small markets are flagged. They match no planted event and look like seasonal dips plus random noise. A flag is a prompt to investigate, not proof of a tracking break |
| `03_spend_vs_sessions_sanity.sql` | Do spend and sessions move together for paid channels? | One cost-per-session outlier (AT, Google). No spend-without-sessions or sessions-without-spend rows |
| `04_revenue_reconciliation.sql` | Do orders and revenue reconcile? | Components add up. March 2026 revenue per order is low in the four promo markets, as expected from discounted outdoor furniture |

## Run
From the repository root:
```
pip install duckdb pandas
python sql/run_checks.py
```
The paths are relative, so run from the root folder.

## Notes
- Check 02 catches sudden breaks, not gradual effects. I tested it by cutting one week of German orders by 60% in a copy of the data, and it flagged that week.
- Event-level checks (duplicate `transaction_id`, missing or inconsistent UTMs) need event-level data, which this dataset does not have. They are planned for the tracking demo repo and do not exist yet.

