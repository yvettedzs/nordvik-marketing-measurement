-- 01_platform_vs_analytics_gap.sql
-- CHECK: how much more revenue do the ad platforms claim than the analytics data records?
-- DATA:  data/simulated_weekly_data.csv (platform_reported_revenue_eur is dated by click week,
--        net_revenue_eur by order week, so totals over the full period are compared).
-- RULE:  ratio > 1.50 = FAIL, ratio > 1.25 = WARN, otherwise OK. SEO and Direct_Other have no platform figure.
-- ACTION: FAIL means do not use that platform's ROAS for budget decisions without an incrementality test.
WITH by_channel AS (
    SELECT channel,
           SUM(spend_eur)                     AS spend_eur,
           SUM(platform_reported_revenue_eur) AS platform_revenue_eur,
           SUM(net_revenue_eur)               AS analytics_revenue_eur
    FROM read_csv_auto('data/simulated_weekly_data.csv')
    WHERE platform_reported_revenue_eur IS NOT NULL
    GROUP BY channel
)
SELECT channel,
       ROUND(platform_revenue_eur / spend_eur, 2)   AS platform_roas,
       ROUND(analytics_revenue_eur / spend_eur, 2)  AS analytics_roas,
       ROUND(platform_revenue_eur / analytics_revenue_eur, 2) AS claim_ratio,
       CASE WHEN platform_revenue_eur / analytics_revenue_eur > 1.50 THEN 'FAIL'
            WHEN platform_revenue_eur / analytics_revenue_eur > 1.25 THEN 'WARN'
            ELSE 'OK' END AS status
FROM by_channel
ORDER BY claim_ratio DESC;
