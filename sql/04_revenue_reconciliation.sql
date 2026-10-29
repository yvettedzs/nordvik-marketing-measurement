-- 04_revenue_reconciliation.sql
-- CHECK: do orders and revenue reconcile?
--   1) outdoor-furniture orders + summer-house orders must equal total orders
--   2) monthly net revenue per order, by market, should be close to the expected value:
--      (85% x 3,500 + 15% x 9,000) / (1 + VAT)  (regular prices, incl. VAT)
-- RULE:  component mismatch = FAIL; revenue per order more than 10% from expected = WARN.
-- NOTE:  months with a promotion pull revenue per order below expected on purpose (discounted outdoor furniture).
WITH d AS (SELECT * FROM read_csv_auto('data/simulated_weekly_data.csv')),
vat AS (SELECT * FROM (VALUES ('DE',0.19),('AT',0.20),('FR',0.20),('NL',0.21),('UK',0.20),('SE',0.25)) t(market, vat_rate)),
check1 AS (
    SELECT 'component mismatch' AS check_name, week_start::VARCHAR AS period, market,
           orders AS value_a, orders_outdoor_furniture + orders_summer_house AS value_b, 'FAIL' AS status
    FROM d WHERE orders <> orders_outdoor_furniture + orders_summer_house
),
monthly AS (
    SELECT date_trunc('month', d.week_start) AS month, d.market,
           SUM(net_revenue_eur) / NULLIF(SUM(orders), 0) AS revenue_per_order,
           (0.85 * 3500 + 0.15 * 9000) / (1 + MAX(vat.vat_rate)) AS expected_per_order
    FROM d JOIN vat USING (market)
    GROUP BY 1, 2
),
check2 AS (
    SELECT 'revenue per order vs expected', month::VARCHAR, market,
           ROUND(revenue_per_order) AS value_a, ROUND(expected_per_order) AS value_b, 'WARN'
    FROM monthly
    WHERE ABS(revenue_per_order / expected_per_order - 1) > 0.10
)
SELECT * FROM check1
UNION ALL SELECT * FROM check2
ORDER BY check_name, period, market;
