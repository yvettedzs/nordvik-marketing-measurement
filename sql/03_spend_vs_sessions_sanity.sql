-- 03_spend_vs_sessions_sanity.sql
-- CHECK: spend and sessions should move together for paid channels. Three problems are tested:
--   A) spend but no sessions (broken tags or landing pages)
--   B) sessions but no spend (untagged traffic or mislabelled UTMs)
--   C) cost per session far from the channel's normal level (more than 4 standard deviations)
-- NOTE: A planned pause (see data/events_calendar.csv) shows as spend = 0 and sessions = 0 and is not an error.
WITH paid AS (
    SELECT * FROM read_csv_auto('data/simulated_weekly_data.csv')
    WHERE channel IN ('Google', 'Meta', 'TikTok', 'Affiliates')
),
problems AS (
    SELECT week_start, market, channel, spend_eur, sessions, 'A: spend but no sessions' AS problem
    FROM paid WHERE spend_eur > 0 AND sessions = 0
    UNION ALL
    SELECT week_start, market, channel, spend_eur, sessions, 'B: sessions but no spend'
    FROM paid WHERE spend_eur = 0 AND sessions > 0
),
cps AS (
    SELECT *, spend_eur / NULLIF(sessions, 0) AS cost_per_session,
           AVG(spend_eur / NULLIF(sessions, 0)) OVER (PARTITION BY market, channel) AS avg_cps,
           STDDEV(spend_eur / NULLIF(sessions, 0)) OVER (PARTITION BY market, channel) AS sd_cps
    FROM paid
)
SELECT week_start, market, channel, spend_eur, sessions, problem FROM problems
UNION ALL
SELECT week_start, market, channel, spend_eur, sessions, 'C: cost per session outlier'
FROM cps
WHERE sessions > 0 AND ABS(cost_per_session - avg_cps) > 4 * sd_cps
ORDER BY problem, week_start, market, channel;
