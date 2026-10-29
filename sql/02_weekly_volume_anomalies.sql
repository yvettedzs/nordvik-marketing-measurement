-- 02_weekly_volume_anomalies.sql
-- CHECK: weeks where a market's orders fall sharply below its own recent level (possible tracking break or real event).
-- METHOD: compare each week with the median of the previous 8 weeks, per market, all channels combined.
-- RULE:  FLAG when orders are more than 25% below the 8-week median AND more than 3 standard errors below it
--        (standard error approximated as the square root of the median, as for count data). The second condition
--        stops small markets being flagged for ordinary random swings.
-- NOTE:  catches sudden breaks (tag outage, broken checkout), not gradual effects such as the Meta holdout.
-- ACTION: check each flagged week against data/events_calendar.csv and the release/outage log before treating it as a tracking error.
WITH weekly AS (
    SELECT week_start, market, SUM(orders) AS orders
    FROM read_csv_auto('data/simulated_weekly_data.csv')
    GROUP BY week_start, market
),
rolling AS (
    SELECT *,
           MEDIAN(orders) OVER (PARTITION BY market ORDER BY week_start
                                ROWS BETWEEN 8 PRECEDING AND 1 PRECEDING) AS prev8_median
    FROM weekly
)
SELECT week_start, market, orders, prev8_median,
       ROUND(orders / prev8_median - 1, 3) AS change_vs_median,
       'FLAG' AS status
FROM rolling
WHERE prev8_median IS NOT NULL
  AND orders / prev8_median - 1 < -0.25
  AND orders < prev8_median - 3 * SQRT(prev8_median)
ORDER BY change_vs_median;
