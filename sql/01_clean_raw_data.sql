-- 01_clean_raw_data.sql
-- Queries to clean the raw datasets (sessions, signups, opportunities)
--
-- Data fixes:
-- sessions       channel written 12 ways             -> standardized to 7 channels    (1,284 rows)
-- sessions       135 versions of ~20 URLs            -> cleaned, grouped in 7 types   (all rows)
-- sessions       missing visitor_id                  -> kept, flagged                 (300)
-- signups        exact duplicates                    -> removed                       (66)
-- signups        company_size -5 / 999,999           -> set to null                   (30)
-- signups        same lead twice                     -> kept most complete row        (4 leads)
-- signups        signup dated in July                -> replaced with session date    (8)
-- signups        session_id not in sessions          -> kept, flagged                 (25)
-- signups        geo = 'N/A'                         -> set to null                   (25)
-- opportunities  exact duplicates                    -> removed                       (18)
-- opportunities  amount 35,000 / 110,000             -> divided by 1,000              (6)
-- opportunities  $0 deals                            -> flagged, not counted as wins  (30)
-- opportunities  negative days_to_close              -> recalculated from dates       (10)
-- opportunities  lead_id not in signups              -> kept, flagged                 (15)


-- Sessions --------------------------------------------------------------

CREATE OR REPLACE TABLE sessions_clean AS
WITH urls AS (
    SELECT
        s.*,
        -- Did this to clean up the url (no query string, country prefix or trailing slash)
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
    -- Standardized the channel names
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
    -- Grouped the urls into page types
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
    CASE WHEN visitor_id IS NULL THEN 1 ELSE 0 END AS is_visitor_missing   -- Kept, flagged visits with no visitor_id
FROM urls;


-- Signups ---------------------------------------------------------------

CREATE OR REPLACE TABLE signups_clean AS
WITH dedup AS (
    SELECT DISTINCT * FROM signups                                          -- Removed exact duplicates
),
fixed AS (
    SELECT
        lead_id,
        visitor_id,
        session_id,
        CAST(created_dt AS DATE) AS created_dt,
        mktg_channel,
        product_code,
        NULLIF(TRIM(geo), 'N/A') AS geo,                                    -- 'N/A' as text -> null
        CASE WHEN company_size < 1 OR company_size >= 999999 THEN NULL      -- Fake sizes (-5, 999,999) -> null
             ELSE company_size END AS company_size
    FROM dedup
),
ranked AS (
    -- Some leads show up twice, kept the row with more fields filled in
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
    -- A few signups are dated in July, used the session date instead
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
    CASE WHEN s.session_id IS NULL THEN 1 ELSE 0 END AS is_session_orphan  -- Flagged signups whose session_id is not in sessions
FROM ranked r
LEFT JOIN sessions_clean s ON s.session_id = r.session_id
WHERE r.rn = 1;


-- Opportunities ---------------------------------------------------------

CREATE OR REPLACE TABLE opportunities_clean AS
WITH dedup AS (
    SELECT DISTINCT * FROM opportunities                                    -- Removed exact duplicates
)
SELECT
    o.opp_id,
    o.lead_id,
    CAST(o.close_dt AS DATE) AS close_dt,
    o.plan,
    CASE WHEN o.amount IN (35000, 110000) THEN o.amount / 1000              -- Amounts 1,000x too high
         ELSE o.amount END AS amount,
    CASE WHEN o.amount = 0 THEN 1 ELSE 0 END AS is_zero_amount,             -- Flagged $0 deals, never a win
    -- Recalculated days to close from the dates (abs() when the lead is missing)
    COALESCE(CAST(o.close_dt AS DATE) - g.created_dt, ABS(o.days_to_close)) AS days_to_close,
    CASE WHEN g.lead_id IS NULL THEN 1 ELSE 0 END AS is_lead_orphan        -- Flagged deals whose lead_id is not in signups
FROM dedup o
LEFT JOIN signups_clean g ON g.lead_id = o.lead_id;
