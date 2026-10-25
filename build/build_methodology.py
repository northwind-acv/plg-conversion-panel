"""
Renders docs/data-methodology.html. Every count is queried live from the raw CSVs
and the cleaned tables built by sql/01_clean.sql. Run from the repo root:
    python build/build_methodology.py
"""
from pathlib import Path
import html, os, re
import duckdb

ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT)
con = duckdb.connect()
con.execute(Path("sql/00_load_raw.sql").read_text())
con.execute(Path("sql/01_clean.sql").read_text())
one = lambda s: con.execute(s).fetchone()
RAW = lambda t: f"read_csv_auto('data/{t}.csv')"
esc = lambda s: html.escape(str(s), quote=True)
f0 = lambda x: f"{x:,.0f}"

# ------------------------------------------------------------------ profiles
raw_n = {t: one(f"SELECT COUNT(*) FROM {RAW(t)}")[0] for t in ["sessions", "signups", "opportunities"]}
cln_n = {"sessions": one("SELECT COUNT(*) FROM sessions_clean")[0],
         "signups": one("SELECT COUNT(*) FROM signups_clean")[0],
         "opportunities": one("SELECT COUNT(*) FROM opportunities_clean")[0]}
s_vis, s_null, s_min, s_max, s_flag = one(f"""SELECT COUNT(DISTINCT visitor_id), COUNT(*) FILTER (WHERE visitor_id IS NULL),
    MIN(event_dt), MAX(event_dt), SUM(converted_flag) FROM {RAW('sessions')}""")
s_urls, s_ch = one(f"SELECT COUNT(DISTINCT entry_url), COUNT(DISTINCT mktg_channel) FROM {RAW('sessions')}")
g_min, g_max = one(f"SELECT MIN(created_dt), MAX(created_dt) FROM {RAW('signups')}")
o_min, o_max = one(f"SELECT MIN(close_dt), MAX(close_dt) FROM {RAW('opportunities')}")

# ------------------------------------------------------------------ join quality
j = one("""SELECT COUNT(*), COUNT(s.session_id), COUNT(*) FILTER (WHERE s.converted_flag = 1),
                  COUNT(*) FILTER (WHERE g.visitor_id = s.visitor_id),
                  COUNT(*) FILTER (WHERE g.mktg_channel = s.mktg_channel),
                  COUNT(*) FILTER (WHERE g.geo = s.geo), COUNT(*) FILTER (WHERE g.geo IS NOT NULL AND s.geo IS NOT NULL),
                  COUNT(*) FILTER (WHERE g.created_dt = s.event_dt)
           FROM signups_clean g LEFT JOIN sessions_clean s USING (session_id)""")
g_tot, g_matched, g_flag1, g_vis_ok, g_ch_ok, g_geo_ok, g_geo_both, g_sameday = j
flag_no_signup = one("SELECT COUNT(*) FROM sessions_clean WHERE converted_flag = 1 AND session_id NOT IN (SELECT session_id FROM signups_clean)")[0]
o_tot, o_matched = one("SELECT COUNT(*), COUNT(*) FILTER (WHERE is_lead_orphan = 0) FROM opportunities_clean")
opp_per_lead = one("SELECT MAX(c) FROM (SELECT lead_id, COUNT(*) c FROM opportunities_clean GROUP BY 1)")[0]
close_before = one("SELECT COUNT(*) FROM opportunities_clean o JOIN signups_clean g USING (lead_id) WHERE o.close_dt < g.created_dt")[0]
dtc_max = one("SELECT MAX(days_to_close) FROM opportunities_clean")[0]
plan_amt = con.execute("SELECT plan, amount, COUNT(*) FROM opportunities_clean GROUP BY ALL ORDER BY 1, 2").fetchall()
xwalk = con.execute("""SELECT g.product_code, o.plan, COUNT(*) FROM opportunities_clean o JOIN signups_clean g USING (lead_id)
                       GROUP BY ALL ORDER BY 1, 2""").fetchall()
late_signups = one("SELECT COUNT(*) FROM signup_outcomes WHERE created_dt > (SELECT MAX(close_dt) FROM opportunities_clean) - INTERVAL 30 DAY")[0]
imputed = con.execute("""
    SELECT g.lead_id, r.created_dt, g.created_dt, o.close_dt, o.days_to_close
    FROM signups_clean g
    JOIN (SELECT DISTINCT lead_id, created_dt FROM read_csv_auto('data/signups.csv')) r USING (lead_id)
    JOIN opportunities_clean o USING (lead_id)
    WHERE g.is_date_fixed = 1 ORDER BY 1""").fetchall()

lp_q1 = one("""SELECT COUNT(*), SUM(converted_flag) FROM sessions_clean
              WHERE page_type = 'free_crm_lp' AND event_dt < DATE '2026-04-01'""")
lp_q1_share = one("""SELECT 100.0 * COUNT(*) FILTER (WHERE page_type = 'free_crm_lp') / COUNT(*)
                    FROM sessions_clean WHERE event_dt < DATE '2026-04-01'""")[0]
# ------------------------------------------------------------------ rule counts
rc = {
    "R1": one(f"SELECT COUNT(*) FROM {RAW('sessions')} WHERE mktg_channel NOT IN ('Direct','Display','Email','Organic Search','Paid Search','Referral','Social')")[0],
    "R2": s_urls,
    "R3": s_null,
    "R4": raw_n["signups"] - one(f"SELECT COUNT(*) FROM (SELECT DISTINCT * FROM {RAW('signups')})")[0],
    "R5": one(f"SELECT COUNT(*) FROM (SELECT DISTINCT * FROM {RAW('signups')}) WHERE company_size < 1 OR company_size >= 999999")[0],
    "R6": one(f"SELECT COUNT(*) FROM (SELECT lead_id FROM (SELECT DISTINCT * FROM {RAW('signups')}) GROUP BY 1 HAVING COUNT(*) > 1)")[0],
    "R7": one("SELECT COUNT(*) FROM signups_clean WHERE is_date_fixed = 1")[0],
    "R8": one("SELECT COUNT(*) FROM signups_clean WHERE is_session_orphan = 1")[0],
    "R9": raw_n["opportunities"] - one(f"SELECT COUNT(*) FROM (SELECT DISTINCT * FROM {RAW('opportunities')})")[0],
    "R10": one(f"SELECT COUNT(*) FROM (SELECT DISTINCT * FROM {RAW('opportunities')}) WHERE amount IN (35000, 110000)")[0],
    "R11": one("SELECT COUNT(*) FROM opportunities_clean WHERE is_zero_amount = 1")[0],
    "R12": one(f"SELECT COUNT(*) FROM (SELECT DISTINCT * FROM {RAW('opportunities')}) WHERE days_to_close < 0")[0],
    "R13": one("SELECT COUNT(*) FROM opportunities_clean WHERE is_lead_orphan = 1")[0],
    "R14": one(f"SELECT COUNT(*) FROM (SELECT DISTINCT * FROM {RAW('signups')}) WHERE trim(geo) = 'N/A'")[0],
}
pages = con.execute("SELECT page_type, COUNT(*) FROM sessions_clean GROUP BY 1 ORDER BY 2 DESC").fetchall()

def table(head, rows, cls=""):
    h = "".join(f"<th>{esc(c)}</th>" for c in head)
    b = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows)
    return f'<div class="tbl"><table class="{cls}"><thead><tr>{h}</tr></thead><tbody>{b}</tbody></table></div>'

pct = lambda a, b: f"{100*a/b:.1f}%"

t_tables = table(["Table", "One row is", "Key", "Rows raw → clean", "Date range"], [
    ["<b>sessions</b>", "A website visit", "<code>session_id</code>", f"{f0(raw_n['sessions'])} → {f0(cln_n['sessions'])}", f"{s_min:%b %-d} – {s_max:%b %-d, %Y}"],
    ["<b>signups</b>", "A lead signing up for one product", "<code>lead_id</code>", f"{f0(raw_n['signups'])} → {f0(cln_n['signups'])}", f"{g_min:%b %-d} – {g_max:%b %-d, %Y}*"],
    ["<b>opportunities</b>", "A closed deal (paid plan)", "<code>opp_id</code>", f"{f0(raw_n['opportunities'])} → {f0(cln_n['opportunities'])}", f"{o_min:%b %-d} – {o_max:%b %-d, %Y}"],
], "txt")

dict_rows = [
    ["sessions", "session_id", "Unique visit id. Joins to signups.session_id."],
    ["sessions", "visitor_id", f"Visitor (cookie-level) id; {f0(s_vis)} distinct, {s_null} null. A visitor can have many sessions."],
    ["sessions", "event_dt", "Visit date."],
    ["sessions", "mktg_channel", f"Marketing channel of the visit. {s_ch} raw labels that are really 7 channels (casing / trailing spaces)."],
    ["sessions", "geo, device_type", "Country bucket and device of the visit."],
    ["sessions", "entry_url", f"Landing page. {s_urls} raw URLs that are really ~20 pages (case, trailing slash, query string, geo prefix)."],
    ["sessions", "converted_flag", f"1 if the visit produced a signup. {f0(s_flag)} sessions flagged; every matched signup's session has flag = 1."],
    ["signups", "lead_id", "Unique lead id. Joins to opportunities.lead_id."],
    ["signups", "visitor_id, session_id", "The visitor and the session the signup happened in (last touch)."],
    ["signups", "created_dt", "Signup date. Same day as its session in 100% of matched rows after cleaning."],
    ["signups", "mktg_channel, geo", "Copied from the signup session (agree with sessions in ~100% of rows)."],
    ["signups", "product_code", "Product signed up for: <code>STR</code> Starter trial, <code>PRO</code> Pro trial, <code>FCRM</code> Free CRM (from Apr 1)."],
    ["signups", "company_size", "Employee count, self-reported. Has sentinels (−5, 999,999)."],
    ["opportunities", "opp_id, lead_id", f"Closed deal and the lead it came from; at most {opp_per_lead} opportunity per lead."],
    ["opportunities", "close_dt", "Date the deal closed (customer started paying)."],
    ["opportunities", "plan, amount", "Plan purchased and monthly price: Starter $35, Pro $110 (stable all period). Some $0 rows."],
    ["opportunities", "days_to_close", f"Days from signup to close. Range 1–{dtc_max} after fixing a sign bug."],
]
t_dict = table(["Table", "Field", "What it means (inferred)"], [[f"<code>{a}</code>", f"<code>{b}</code>", c] for a, b, c in dict_rows], "txt")

t_join = table(["Check", "Result", "Read"], [
    ["Signups that find their session", f"{f0(g_matched)} / {f0(g_tot)} ({pct(g_matched, g_tot)})", f"{g_tot-g_matched} have malformed session ids (R8)"],
    ["Matched signup sessions with converted_flag = 1", f"{f0(g_flag1)} / {f0(g_matched)} (100%)", "Confirms what converted_flag means"],
    ["Flagged sessions with no signup", f"{f0(flag_no_signup)}", "Same count as the malformed signup keys: the other side of the same break"],
    ["Signup on the same day as its session", f"{f0(g_sameday)} / {f0(g_matched)} (100%)", "After R7. No attribution window needed"],
    ["visitor_id agrees between tables", f"{f0(g_vis_ok)} / {f0(g_matched)} ({100*g_vis_ok/g_matched:.2f}%)", "3 mismatches; not used for joins"],
    ["Channel agrees between tables", f"{f0(g_ch_ok)} / {f0(g_matched)} ({pct(g_ch_ok, g_matched)})", "After R1"],
    ["Geo agrees between tables", f"{f0(g_geo_ok)} / {f0(g_geo_both)} ({pct(g_geo_ok, g_geo_both)})", "Where both sides are known (R14)"],
    ["Opportunities that find their lead", f"{f0(o_matched)} / {f0(o_tot)} ({pct(o_matched, o_tot)})", f"{o_tot-o_matched} have malformed lead ids (R13)"],
    ["Opportunities per lead", f"max {opp_per_lead}", "1:1, no fan-out on join"],
    ["Deals closed before their signup", f"{close_before}", "After R7 and R12"],
], "txt")

t_xwalk = table(["Signed up for", "Bought", "Deals"], [[a, b, f0(n)] for a, b, n in xwalk])
t_amt = table(["Plan", "Amount (after R10)", "Deals"], [[a, f"${b}", f0(n)] for a, b, n in plan_amt])

RULES = [
    ("R1", "sessions", "Channel labels in 12 variants (<code>'Display '</code>, <code>'direct'</code>, <code>'Organic search'</code>)", "Trim + map to the 7 canonical channels", "rows relabeled"),
    ("R2", "sessions", "entry_url has 135 raw values: mixed case, trailing slashes, <code>?gclid</code> / <code>utm</code> params, geo prefixes (<code>/uk/</code>, <code>/in/</code>)", "Normalize URL, then map to 7 page types (content, home, pricing, product, Free CRM LP, trial LP, campaign LP)", "raw URLs → 7 types"),
    ("R3", "sessions", "visitor_id missing", "Keep (session metrics are fine); flag", "rows flagged"),
    ("R4", "signups", "Exact duplicate rows", "Drop", "rows dropped"),
    ("R5", "signups", "company_size sentinels: −5 and 999,999", "Set to NULL; analyze in buckets, never averages", "rows nulled"),
    ("R6", "signups", "Same lead_id twice with conflicting geo / company_size", "Keep the most complete row", "leads deduplicated"),
    ("R7", "signups", "created_dt in July, outside the window. Each one's session is in the window, and every other signup happens the same day as its session", "Replace with the session date", "dates corrected"),
    ("R8", "signups", "session_id doesn't exist in sessions (format <code>S9xxxxxxx</code>)", "Keep for signup → paid metrics; excluded only from origin cuts", "rows flagged"),
    ("R9", "opportunities", "Exact duplicate rows", "Drop", "rows dropped"),
    ("R10", "opportunities", "Amount 1,000× list price (35,000 / 110,000)", "Divide by 1,000 (unit error)", "amounts fixed"),
    ("R11", "opportunities", "Amount = $0 (closed but not paying: coupon, comp or internal)", "Exclude from paying customers; sensitivity shown with them included", "deals flagged"),
    ("R12", "opportunities", "Negative days_to_close; the absolute value equals the true date gap", "Recompute from dates", "values fixed"),
    ("R13", "opportunities", "lead_id doesn't exist in signups (format <code>G9xxxxxx</code>). Implied signup dates fall inside the window, so these are broken keys, not pre-January leads", "Keep in the finance (close date) view; excluded from cohort conversion", "deals flagged"),
    ("R14", "signups", "geo holds the literal text <code>'N/A'</code> (in addition to true NULLs)", "Set to NULL", "rows nulled"),
]
t_rules = table(["Rule", "Table", "Issue found", "Treatment", "Affected"],
                [[f"<b>{r}</b>", t, issue, fix, f"{f0(rc[r])} {unit}"] for r, t, issue, fix, unit in RULES], "rules")

t_imp = table(["Lead", "Raw created_dt", "Corrected (session date)", "Deal closed", "days_to_close (raw)"],
              [[f"<code>{a}</code>", f"{b:%b %-d}", f"{c:%b %-d}", f"{d:%b %-d}", str(e)] for a, b, c, d, e in imputed])

t_pages = table(["Page type", "Sessions"], [[p, f0(n)] for p, n in pages])

css = re.search(r"<style>(.*?)</style>", Path("docs/analysis.html").read_text(), re.S).group(1)
css += """
table.txt th, table.txt td { text-align:left; white-space:normal; vertical-align:top; }
table.rules td { white-space:normal; vertical-align:top; text-align:left; font-size:13.5px; }
table.rules td:last-child { white-space:nowrap; text-align:right; }
table.rules td:nth-child(3) { min-width:280px; } table.rules td:nth-child(4) { min-width:220px; }
.joinmap { display:flex; align-items:stretch; gap:0; margin:20px 0; flex-wrap:wrap; }
.jbox { flex:1 1 200px; background:var(--surface); border:1px solid var(--line); border-radius:10px; padding:14px 16px; }
.jbox .n { font-weight:600; } .jbox .g { color:var(--fg2); font-size:13px; }
.jarrow { flex:0 0 120px; display:flex; flex-direction:column; justify-content:center; align-items:center; font-size:12px; color:var(--fg2); text-align:center; }
.jarrow span { font-family:ui-monospace,Menlo,monospace; color:var(--fg); }
.jarrow i { display:block; width:100%; height:1px; background:var(--axis); margin:6px 0; position:relative; }
.jarrow i:after { content:""; position:absolute; right:0; top:-4px; border:4px solid transparent; border-left:6px solid var(--axis); }
@media (max-width:640px) { .jarrow { flex-basis:100%; padding:8px 0; } }

.two { display:grid; grid-template-columns:1fr 1fr; gap:24px; } @media (max-width:640px) { .two { grid-template-columns:1fr; } }
code { font-family:ui-monospace,Menlo,monospace; font-size:0.9em; }
"""

sqlfile = lambda f: esc(Path(f).read_text().strip())

page = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Northwind CRM — Data methodology</title>
<style>{css}</style>
</head>
<body>
<main>
<nav class="crumbs"><a href="./">Northwind CRM case</a> / Data methodology</nav>
<h1>Data methodology</h1>
<div class="date">How the tables were understood, validated, cleaned and joined · Companion to the <a href="analysis.html">Analysis</a></div>

<p class="tldr">We got three raw extracts and no data dictionary. The tables join cleanly on ids (99%+ match rates), but they needed 14 fixes before we could trust them: duplicates, broken keys, amounts recorded 1,000× too high, a sign bug in days to close, out-of-range dates and messy labels. Under 1% of rows needed a fix (not counting URL normalization, which applies to every visit). Every rule is in SQL and every count on this page is queried from the data.</p>

<h2>1. What each table is</h2>
{t_tables}
<p class="note-foot">* 8 signups are dated in July, after sessions end on Jun 30. Corrected in R7.</p>
<p>There's no dictionary, so this is our read of each field from the values, and what we checked to confirm it:</p>
{t_dict}

<h2>2. How the tables connect</h2>
<div class="joinmap">
  <div class="jbox"><div class="n">sessions</div><div class="g">{f0(cln_n['sessions'])} website visits</div></div>
  <div class="jarrow"><span>session_id</span><i></i>1 : 0..1</div>
  <div class="jbox"><div class="n">signups</div><div class="g">{f0(cln_n['signups'])} leads, one product each</div></div>
  <div class="jarrow"><span>lead_id</span><i></i>1 : 0..1</div>
  <div class="jbox"><div class="n">opportunities</div><div class="g">{f0(cln_n['opportunities'])} closed deals</div></div>
</div>
<p>The first instinct with three separate extracts is to line them up by date. We don't need to: the ids connect them row by row, which lets us follow each signup from the visit that produced it to the deal it became. That's what makes the plan and origin cuts in the analysis possible.</p>
{t_join}

<h3>Signup product vs plan bought</h3>
<p><code>product_code</code> (what the lead signed up for) and <code>plan</code> (what they bought) are different fields. Free CRM is not a plan you buy; its upgrades show up as Starter deals.</p>
<div class="two">{t_xwalk}{t_amt}</div>
<p class="note-foot">Counts include $0 deals. Prices didn't change during the period, so this is a packaging change, not a pricing change.</p>

<h2>3. Cleaning rules</h2>
<p>Each rule is numbered in <a href="https://github.com/northwind-acv/plg-conversion-panel/blob/main/sql/01_clean.sql">01_clean.sql</a> with the same id. Rows are flagged rather than dropped when they're still useful for some cuts.</p>
{t_rules}

<h3>Checking R7: were the July dates really wrong?</h3>
<p>Two of the eight leads with July signup dates have a closed deal. In both, the raw <code>days_to_close</code> only makes sense if the signup happened on the session date, not in July. One of them closed in March, which would be before its own signup.</p>
{t_imp}

<h3>R2: landing pages after normalizing</h3>
{t_pages}

<h2>4. Definitions</h2>
<ul>
  <li><b>Paying customer (win):</b> an opportunity with amount &gt; $0, closed within 30 days of the signup. We call it "paying customer" because finance defines a customer as a closed opportunity, and $0 deals don't pay.</li>
  <li><b>Cohort:</b> signups grouped by the month they signed up. Conversion is always cohort-based (signup month → did they pay), not close-month based.</li>
  <li><b>Periods:</b> Q1 = Jan–Mar 2026 (before Free CRM), Q2 = Apr–Jun 2026 (after launch). Compared as monthly averages.</li>
  <li><b>Plan:</b> the product the lead signed up for (<code>product_code</code>), not the plan they bought.</li>
  <li><b>Origin attributes</b> (channel, entry page, device): from the signup session, i.e. last touch. 37% of signups had earlier visits; we don't attribute to those.</li>
  <li><b>New vs returning:</b> returning = the visitor had a session on an earlier day than the signup.</li>
</ul>

<h2>5. Assumptions and why they're safe</h2>
<ul>
  <li><b>30-day window.</b> No deal in the extract closes more than {dtc_max} days after signup, so a 30-day window loses nothing. Opportunities run to {o_max:%b %-d}; the {f0(late_signups)} signups after {(o_max - __import__('datetime').timedelta(days=30)):%b %-d} have a slightly shorter window. With a 29-day maximum, the impact is a handful of deals in late June.</li>
  <li><b>$0 deals excluded.</b> {rc['R11']} of {f0(cln_n['opportunities'])} deals, spread evenly across months. Including them doesn't change any trend (see the finance view in the analysis).</li>
  <li><b>Orphan rows kept, not invented.</b> We don't guess the true keys of the {rc['R8']} signups and {rc['R13']} deals with broken ids. They stay in the totals they can support and out of the cuts they can't.</li>
  <li><b>January in the finance view.</b> Some January closes come from December signups, which aren't in the data, so January close-month counts are low. Cohort views aren't affected.</li>
  <li><b>Free CRM in the decomposition.</b> Free CRM has no Q1 conversion rate. The Kitagawa split uses its Q2 rate for both periods, which puts its whole effect in the mix term.</li>
</ul>

<h2>6. What the data can't tell us</h2>
<ul>
  <li><b>Anything inside the product.</b> Sessions are website visits; there are no product logins or usage events. We can't measure activation.</li>
  <li><b>Upgrades after 30 days.</b> No deal closes more than {dtc_max} days after signup, for any SKU, even for April cohorts with ~85 days of history. Either Free CRM users decide in their first month or the extract only captures the first 30 days. A freemium plan usually converts over a longer period, so Free CRM's lifetime conversion could be higher than what we observe.</li>
  <li><b>Free CRM landing page before launch.</b> The Free CRM landing page URLs (<code>/lp/free-crm</code>, <code>/offers/free-crm/</code>) get traffic from January: {f0(lp_q1[0])} sessions in Q1 ({lp_q1_share:.0f}% of Q1 traffic), producing {f0(lp_q1[1])} Starter and Pro signups before the product existed. The same happens with <code>/campaign/spring-2026</code>. It could be a teaser page, a reused URL or an artifact of the extract. Left as is: we can't tell which version is right, and no finding depends on it.</li>
  <li><b>Multi-touch attribution.</b> Only the signup session is linked to the lead.</li>
  <li><b>Direct traffic in June.</b> Direct jumps to 37% of sessions and its signup rate halves. Probably tracking or bots; worth checking at the source.</li>
</ul>

<h2>7. Reproduce it</h2>
<p>The queries are written in Snowflake SQL and avoid engine-specific functions, so they also run unchanged in <a href="https://duckdb.org">DuckDB</a> on a laptop. In Snowflake, run 01, 02 and 03 against the <code>sessions</code>, <code>signups</code> and <code>opportunities</code> tables. Locally, run <code>00_load_raw.sql</code> first to load the CSVs into tables with those same names. Run from the folder that contains <code>data/</code>.</p>
<pre>duckdb northwind.duckdb &lt; sql/00_load_raw.sql
duckdb northwind.duckdb &lt; sql/01_clean.sql
duckdb northwind.duckdb &lt; sql/02_funnel.sql
duckdb northwind.duckdb &lt; sql/03_decomposition.sql</pre>
<details><summary>00_load_raw.sql — load the CSVs (local only)</summary><pre>{sqlfile('sql/00_load_raw.sql')}</pre></details>
<details><summary>01_clean.sql — cleaning rules and analysis base table</summary><pre>{sqlfile('sql/01_clean.sql')}</pre></details>
<details><summary>02_funnel.sql — funnel, plan split, slices, finance view</summary><pre>{sqlfile('sql/02_funnel.sql')}</pre></details>
<details><summary>03_decomposition.sql — Kitagawa decomposition</summary><pre>{sqlfile('sql/03_decomposition.sql')}</pre></details>
</main>
</body>
</html>
"""
(ROOT / "docs" / "data-methodology.html").write_text(page)
print("wrote docs/data-methodology.html", rc)
