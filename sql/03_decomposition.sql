-- 03_decomposition.sql
-- Splits the change in wins per month (Q1 vs Q2) into volume, SKU mix and SKU conversion.
-- Free CRM has no Q1 conversion, so I used its Q2 rate for both periods.


CREATE OR REPLACE TABLE kitagawa AS
WITH sku_by_period AS (
    SELECT period,
           product,
           COUNT(*) / 3.0    AS signups_mo,              -- Monthly average, 3 months per period
           SUM(is_win) / 3.0 AS wins_mo
    FROM signup_outcomes
    GROUP BY period, product
),
all_combinations AS (
    -- Added a Q1 row for Free CRM so every SKU shows up in both periods
    SELECT p.period, k.product
    FROM (VALUES ('Q1'), ('Q2')) AS p(period)
    CROSS JOIN (SELECT DISTINCT product FROM signup_outcomes) AS k
),
filled AS (
    SELECT a.period,
           a.product,
           COALESCE(b.signups_mo, 0) AS signups_mo,
           COALESCE(b.wins_mo, 0)    AS wins_mo
    FROM all_combinations a
    LEFT JOIN sku_by_period b ON b.period = a.period AND b.product = a.product
),
shares_and_rates AS (
    SELECT period,
           product,
           signups_mo / SUM(signups_mo) OVER (PARTITION BY period) AS mix,
           wins_mo / NULLIF(signups_mo, 0)                         AS rate
    FROM filled
),
side_by_side AS (
    SELECT q1.product,
           q1.mix                     AS mix_q1,
           q2.mix                     AS mix_q2,
           COALESCE(q1.rate, q2.rate) AS rate_q1,         -- Free CRM assumption
           q2.rate                    AS rate_q2
    FROM shares_and_rates q1
    JOIN shares_and_rates q2 ON q2.product = q1.product
    WHERE q1.period = 'Q1' AND q2.period = 'Q2'
),
period_totals AS (
    SELECT period,
           SUM(signups_mo)                AS n,
           SUM(wins_mo)                   AS w,
           SUM(wins_mo) / SUM(signups_mo) AS r
    FROM filled
    GROUP BY period
),
t AS (
    SELECT q1.n AS n1, q2.n AS n2, q1.w AS w1, q2.w AS w2, q1.r AS r1, q2.r AS r2
    FROM period_totals q1
    JOIN period_totals q2 ON q1.period = 'Q1' AND q2.period = 'Q2'
)
SELECT 'Q1 wins / month' AS step, NULL AS product, w1 AS wins FROM t
UNION ALL
SELECT 'Volume effect', NULL, (n2 - n1) * (r1 + r2) / 2 FROM t
UNION ALL
SELECT 'Mix effect', s.product,
       (t.n1 + t.n2) / 2 * (s.mix_q2 - s.mix_q1) * (s.rate_q1 + s.rate_q2) / 2
FROM side_by_side s CROSS JOIN t
UNION ALL
SELECT 'Rate effect', s.product,
       (t.n1 + t.n2) / 2 * (s.mix_q1 + s.mix_q2) / 2 * (s.rate_q2 - s.rate_q1)
FROM side_by_side s CROSS JOIN t
UNION ALL
SELECT 'Q2 wins / month', NULL, w2 FROM t;


-- Waterfall (volume + mix + rate adds up to Q2 - Q1)
SELECT step, ROUND(SUM(wins), 1) AS wins_per_month
FROM kitagawa
GROUP BY step
ORDER BY CASE step WHEN 'Q1 wins / month' THEN 1
                   WHEN 'Volume effect'   THEN 2
                   WHEN 'Mix effect'      THEN 3
                   WHEN 'Rate effect'     THEN 4
                   ELSE 5 END;
