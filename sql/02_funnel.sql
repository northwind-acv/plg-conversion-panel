-- 02_funnel.sql
-- Queries to join the cleaned datasets for analysis
-- Runs on top of 01_clean.sql.


-- Signup outcomes: one row per signup with where it came from and whether it paid ----

CREATE OR REPLACE TABLE signup_outcomes AS
WITH first_visit AS (
    SELECT visitor_id, MIN(event_dt) AS first_visit_dt
    FROM sessions_clean
    WHERE visitor_id IS NOT NULL
    GROUP BY visitor_id
),
paid_deals AS (
    SELECT * FROM opportunities_clean WHERE is_zero_amount = 0
)
SELECT
    g.*,
    CAST(DATE_TRUNC('month', g.created_dt) AS DATE) AS signup_month,
    CASE WHEN g.created_dt < DATE '2026-04-01' THEN 'Q1' ELSE 'Q2' END AS period,
    s.device_type,
    s.page_type,
    CASE WHEN fv.first_visit_dt < g.created_dt THEN 'Returning' ELSE 'New' END AS visitor_type,
    CASE
        WHEN g.company_size IS NULL THEN 'Unknown'
        WHEN g.company_size <= 10   THEN '1-10'
        WHEN g.company_size <= 50   THEN '11-50'
        WHEN g.company_size <= 200  THEN '51-200'
        ELSE '201+'
    END AS company_size_bucket,
    o.plan   AS won_plan,
    o.amount AS won_amount,
    o.days_to_close,
    -- Win = paid deal closed within 30 days of signup
    CASE WHEN o.opp_id IS NOT NULL AND o.days_to_close <= 30 THEN 1 ELSE 0 END AS is_win
FROM signups_clean g
LEFT JOIN sessions_clean s ON s.session_id = g.session_id
LEFT JOIN first_visit fv   ON fv.visitor_id = g.visitor_id
LEFT JOIN paid_deals o     ON o.lead_id = g.lead_id;


-- Monthly funnel: sessions -> signups -> wins -> deal value ----------------

CREATE OR REPLACE TABLE monthly_funnel AS
WITH visits AS (
    SELECT CAST(DATE_TRUNC('month', event_dt) AS DATE) AS month,
           COUNT(*) AS sessions
    FROM sessions_clean
    GROUP BY 1
),
signups AS (
    SELECT signup_month AS month,
           COUNT(*)                 AS signups,
           SUM(is_win)              AS wins_30d,
           SUM(is_win * won_amount) AS deal_value_30d   -- only count value for wins
    FROM signup_outcomes
    GROUP BY 1
)
SELECT
    month,
    sessions,
    signups,
    wins_30d,
    deal_value_30d,
    ROUND(100.0 * signups  / sessions, 2) AS sess_to_signup_pct,
    ROUND(100.0 * wins_30d / signups, 1)  AS signup_to_win_pct,
    ROUND(100.0 * wins_30d / sessions, 2) AS sess_to_win_pct
FROM visits
JOIN signups USING (month)
ORDER BY month;


-- Weekly funnel --------------------------------------------------------------

CREATE OR REPLACE TABLE weekly_funnel AS
SELECT
    CAST(DATE_TRUNC('week', created_dt) AS DATE)          AS week_start,
    COUNT(*)                                              AS signups,
    SUM(CASE WHEN product = 'Free CRM' THEN 1 ELSE 0 END) AS free_crm_signups,
    SUM(is_win)                                           AS wins_30d,
    ROUND(100.0 * AVG(is_win), 1)                         AS signup_to_win_pct
FROM signup_outcomes
GROUP BY 1
HAVING MAX(created_dt) - MIN(created_dt) = 6              -- Dropped partial weeks at the start and end
ORDER BY 1;


-- Funnel by SKU ----------------------------------------------------------------

CREATE OR REPLACE TABLE product_funnel AS
SELECT
    signup_month AS month,
    product,
    COUNT(*)                                                                    AS signups,
    ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (PARTITION BY signup_month), 1) AS mix_pct,
    SUM(is_win)                                                                 AS wins_30d,
    ROUND(100.0 * AVG(is_win), 1)                                               AS signup_to_win_pct,
    SUM(is_win * won_amount)                                                    AS deal_value_30d
FROM signup_outcomes
GROUP BY signup_month, product
ORDER BY month, product;


-- Conversion by slice --------------------------------------------------------
-- Stacked every dimension so one GROUP BY covers all of them

CREATE OR REPLACE TABLE slice_conversion AS
WITH stacked AS (
    SELECT signup_month, period, is_win, product, 'channel' AS dimension, mktg_channel AS value FROM signup_outcomes
    UNION ALL
    SELECT signup_month, period, is_win, product, 'entry_page',   page_type                 FROM signup_outcomes
    UNION ALL
    SELECT signup_month, period, is_win, product, 'device',       device_type               FROM signup_outcomes
    UNION ALL
    SELECT signup_month, period, is_win, product, 'visitor_type', visitor_type              FROM signup_outcomes
    UNION ALL
    SELECT signup_month, period, is_win, product, 'company_size', company_size_bucket       FROM signup_outcomes
    UNION ALL
    SELECT signup_month, period, is_win, product, 'geo',          COALESCE(geo, 'Unknown')  FROM signup_outcomes
)
SELECT
    dimension,
    value,
    signup_month AS month,
    period,
    COUNT(*)                      AS signups,
    SUM(is_win)                   AS wins_30d,
    ROUND(100.0 * AVG(is_win), 1) AS signup_to_win_pct,
    ROUND(100.0 * AVG(CASE WHEN product = 'Free CRM' THEN 1 ELSE 0 END), 1) AS free_crm_share_pct
FROM stacked
WHERE value IS NOT NULL                                   -- Signups with no session have no page/device
GROUP BY dimension, value, signup_month, period
ORDER BY dimension, value, month;


-- Finance view: deals by close month -----------------------------------------
-- Did this to tie back to how finance counts customers

CREATE OR REPLACE TABLE finance_view AS
SELECT
    CAST(DATE_TRUNC('month', close_dt) AS DATE)         AS close_month,
    SUM(CASE WHEN is_zero_amount = 0 THEN 1 ELSE 0 END) AS paying_customers,
    COUNT(*)                                            AS all_closed_opps,
    SUM(amount)                                         AS deal_value
FROM opportunities_clean
GROUP BY 1
ORDER BY 1;
