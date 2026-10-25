-- 01_clean.sql
-- Cleans sessions, signups and opportunities and joins them into signup_outcomes.
--
-- Data fixes:
-- R1   sessions       channel written 12 ways             -> standardized to 7 channels    (1,284 rows)
-- R2   sessions       135 versions of ~20 URLs            -> cleaned, grouped in 7 types   (all rows)
-- R3   sessions       missing visitor_id                  -> kept, flagged                 (300)
-- R4   signups        exact duplicates                    -> removed                       (66)
-- R5   signups        company_size -5 / 999,999           -> set to null                   (30)
-- R6   signups        same lead twice                     -> kept most complete row        (4 leads)
-- R7   signups        signup dated in July                -> replaced with session date    (8)
-- R8   signups        session_id not in sessions          -> kept, flagged                 (25)
-- R9   opportunities  exact duplicates                    -> removed                       (18)
-- R10  opportunities  amount 35,000 / 110,000             -> divided by 1,000              (6)
-- R11  opportunities  $0 deals                            -> flagged, not counted as wins  (30)
-- R12  opportunities  negative days_to_close              -> recalculated from dates       (10)
-- R13  opportunities  lead_id not in signups              -> kept, flagged                 (15)
-- R14  signups        geo = 'N/A'                         -> set to null                   (25)


-- Sessions --------------------------------------------------------------

CREATE OR REPLACE TABLE sessions_clean AS
WITH urls AS (
    SELECT
        s.*,
        -- R2: Did this to clean up the url (no query string, country prefix or trailing slash)
        COALESCE(
            NULLIF(
                REGEXP_REPLACE(
                    REGEXP_REPLACE(LOWER(SPLIT_PART(s.entry_url, '?', 1)),
                                   '^/(uk|in|de|au|ca)(/|$)', '/'),
                    '/+$', ''),
                ''),
            '/') AS url_clean
    FROM sessions s
)
SELECT
    session_id,
    visitor_id,
    CAST(event_dt AS DATE) AS event_dt,
    -- R1: Standardized the channel names
    CASE LOWER(TRIM(mktg_channel))
        WHEN 'direct'         THEN 'Direct'
        WHEN 'display'        THEN 'Display'
        WHEN 'email'          THEN 'Email'
        WHEN 'organic search' THEN 'Organic Search'
        WHEN 'paid search'    THEN 'Paid Search'
        WHEN 'referral'       THEN 'Referral'
        WHEN 'social'         THEN 'Social'
    END AS mktg_channel,
    geo,
    device_type,
    entry_url,
    -- R2: Grouped the urls into page types
    CASE
        WHEN url_clean LIKE '/blog%'    OR url_clean LIKE '/resources%' THEN 'content'
        WHEN url_clean IN ('/', '/home', '/index')                      THEN 'home'
        WHEN url_clean LIKE '/pricing%' OR url_clean LIKE '/plans%'     THEN 'pricing'
        WHEN url_clean IN ('/offers/free-crm', '/lp/free-crm')          THEN 'free_crm_lp'
        WHEN url_clean = '/get/starter-trial'                           THEN 'trial_lp'
        WHEN url_clean IN ('/go/crm', '/campaign/spring-2026')          THEN 'campaign_lp'
        WHEN url_clean LIKE '/product%' OR url_clean LIKE '/features%'  THEN 'product'
        ELSE 'other'
    END AS page_type,
    converted_flag,
    CASE WHEN visitor_id IS NULL THEN 1 ELSE 0 END AS is_visitor_missing   -- R3
FROM urls;


-- Signups ---------------------------------------------------------------

CREATE OR REPLACE TABLE signups_clean AS
WITH dedup AS (
    SELECT DISTINCT * FROM signups                                          -- R4
),
fixed AS (
    SELECT
        lead_id,
        visitor_id,
        session_id,
        CAST(created_dt AS DATE) AS created_dt,
        mktg_channel,
        product_code,
        NULLIF(TRIM(geo), 'N/A') AS geo,                                    -- R14
        CASE WHEN company_size < 1 OR company_size >= 999999 THEN NULL      -- R5
             ELSE company_size END AS company_size
    FROM dedup
),
ranked AS (
    -- R6: Some leads show up twice, kept the row with more fields filled in
    SELECT
        f.*,
        ROW_NUMBER() OVER (
            PARTITION BY lead_id
            ORDER BY (CASE WHEN geo IS NOT NULL THEN 1 ELSE 0 END)
                   + (CASE WHEN company_size IS NOT NULL THEN 1 ELSE 0 END) DESC
        ) AS rn
    FROM fixed f
)
SELECT
    r.lead_id,
    r.visitor_id,
    r.session_id,
    -- R7: A few signups are dated in July, used the session date instead
    CASE WHEN r.created_dt > DATE '2026-06-30' AND s.event_dt IS NOT NULL
         THEN s.event_dt ELSE r.created_dt END AS created_dt,
    CASE WHEN r.created_dt > DATE '2026-06-30' AND s.event_dt IS NOT NULL
         THEN 1 ELSE 0 END AS is_date_fixed,
    r.mktg_channel,
    r.product_code,
    CASE r.product_code
        WHEN 'STR'  THEN 'Starter'
        WHEN 'PRO'  THEN 'Pro'
        WHEN 'FCRM' THEN 'Free CRM'
    END AS product,
    r.geo,
    r.company_size,
    CASE WHEN s.session_id IS NULL THEN 1 ELSE 0 END AS is_session_orphan  -- R8
FROM ranked r
LEFT JOIN sessions_clean s ON s.session_id = r.session_id
WHERE r.rn = 1;


-- Opportunities ---------------------------------------------------------

CREATE OR REPLACE TABLE opportunities_clean AS
WITH dedup AS (
    SELECT DISTINCT * FROM opportunities                                    -- R9
)
SELECT
    o.opp_id,
    o.lead_id,
    CAST(o.close_dt AS DATE) AS close_dt,
    o.plan,
    CASE WHEN o.amount IN (35000, 110000) THEN o.amount / 1000              -- R10
         ELSE o.amount END AS amount,
    CASE WHEN o.amount = 0 THEN 1 ELSE 0 END AS is_zero_amount,             -- R11
    -- R12: Recalculated days to close from the dates (abs() when the lead is missing)
    COALESCE(CAST(o.close_dt AS DATE) - g.created_dt, ABS(o.days_to_close)) AS days_to_close,
    CASE WHEN g.lead_id IS NULL THEN 1 ELSE 0 END AS is_lead_orphan        -- R13
FROM dedup o
LEFT JOIN signups_clean g ON g.lead_id = o.lead_id;


-- Signup outcomes: one row per signup, used by every metric ---------------

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
