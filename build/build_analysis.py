"""
Renders docs/analysis.html from the SQL pipeline.
All numbers come from the DuckDB tables built by sql/01-03; this script only
formats them and draws the charts (inline SVG). Run from the repo root:
    python build/build_analysis.py
"""
from pathlib import Path
import html
import duckdb

ROOT = Path(__file__).resolve().parent.parent
con = duckdb.connect()
import os
os.chdir(ROOT)
for f in ["sql/00_load_raw.sql", "sql/01_clean.sql", "sql/02_funnel.sql", "sql/03_decomposition.sql"]:
    con.execute(Path(f).read_text())

q = lambda sql: con.execute(sql).fetchall()
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun"]

# ------------------------------------------------------------------ data
funnel = q("SELECT sessions, signups, wins_30d, deal_value_30d, sess_to_signup_pct, signup_to_win_pct, sess_to_win_pct FROM monthly_funnel ORDER BY month")
prod = {}
for m, p, n, mix, w, cr, mrr in q("SELECT month, product, signups, mix_pct, wins_30d, signup_to_win_pct, deal_value_30d FROM product_funnel ORDER BY month"):
    prod.setdefault(p, {})[m.month] = dict(n=n, mix=mix, w=int(w), cr=cr, mrr=int(mrr))
PRODUCTS = ["Starter", "Pro", "Free CRM"]

def pv(p, k, mi):  # product value for month index 1..6
    return prod[p].get(mi, {}).get(k)

per = {r[0]: r[1:] for r in q("""
    SELECT period, COUNT(*)/3.0, SUM(is_win)/3.0, 100*AVG(is_win),
           SUM(is_win * won_amount)/3.0
    FROM signup_outcomes GROUP BY 1""")}
pp = {(r[0], r[1]): r[2:] for r in q("""
    SELECT period, product, COUNT(*)/3.0, 100*AVG(is_win), SUM(is_win)/3.0
    FROM signup_outcomes GROUP BY 1,2""")}
kit = q("SELECT step, product, wins FROM kitagawa")
kd = {(s, p): w for s, p, w in kit}
mix_total = sum(w for s, p, w in kit if s == "Mix effect")
rate_total = sum(w for s, p, w in kit if s == "Rate effect")

n_sessions = q('SELECT COUNT(*) FROM sessions_clean')[0][0]
n_signups = q('SELECT COUNT(*) FROM signups_clean')[0][0]
n_opps, opp_end = q('SELECT COUNT(*), MAX(close_dt) FROM opportunities_clean')[0]
traffic = q("""
WITH t AS (SELECT CASE WHEN event_dt < DATE '2026-04-01' THEN 'Q1' ELSE 'Q2' END p, mktg_channel ch,
                  COUNT(*)/3.0 sess, SUM(converted_flag)/3.0 sig
           FROM sessions_clean GROUP BY 1, 2)
SELECT ch,
       MAX(sess) FILTER (WHERE p='Q1'), MAX(sess) FILTER (WHERE p='Q2'),
       100*MAX(sig) FILTER (WHERE p='Q1')/MAX(sess) FILTER (WHERE p='Q1'),
       100*MAX(sig) FILTER (WHERE p='Q2')/MAX(sess) FILTER (WHERE p='Q2'),
       MAX(sig) FILTER (WHERE p='Q2') - MAX(sig) FILTER (WHERE p='Q1')
FROM t GROUP BY ch""")
d_sess_tot = sum(r[2] - r[1] for r in traffic); d_sig_tot = sum(r[5] for r in traffic)
low = [r for r in traffic if r[0] in ("Display", "Direct")]
low_sess_share = 100 * sum(r[2] - r[1] for r in low) / d_sess_tot
low_sig_share = 100 * sum(r[5] for r in low) / d_sig_tot
sess_q = {r[0]: r[1] for r in q("""SELECT CASE WHEN event_dt < DATE '2026-04-01' THEN 'Q1' ELSE 'Q2' END, COUNT(*)/3.0
                                   FROM sessions_clean GROUP BY 1""")}

slices = q("""
    SELECT dimension, value, period, COUNT(*) AS n, 100*AVG(is_win) AS cr,
           100*AVG((product='Free CRM')::INT) AS fshare
    FROM (SELECT * FROM signup_outcomes) so,
         LATERAL (SELECT * FROM (VALUES
            ('Channel', mktg_channel), ('Entry page', page_type), ('Device', device_type),
            ('Visitor', visitor_type), ('Company size', company_size_bucket), ('Geo', COALESCE(geo,'Unknown'))
         ) v(dimension, value)) x
    WHERE value IS NOT NULL AND value <> 'Unknown'
    GROUP BY ALL""")
sl = {}
for d, v, p, n, cr, fs in slices:
    sl.setdefault(d, {}).setdefault(v, {})[p] = (n, cr, fs)

slice_month = {}
for d, v, m, n, cr in q("SELECT dimension, value, month, signups, signup_to_win_pct FROM slice_conversion WHERE value <> 'Unknown'"):
    slice_month.setdefault(d, {}).setdefault(v, {})[m.month] = (n, cr)
PRETTY = {"content": "Content (blog, guides)", "home": "Home", "pricing": "Pricing", "product": "Product / features",
          "free_crm_lp": "Free CRM landing page", "trial_lp": "Starter trial landing page", "campaign_lp": "Campaign landing page",
          "desktop": "Desktop", "mobile": "Mobile", "tablet": "Tablet"}
lab = lambda v: PRETTY.get(v, v)
NATURAL = {"Company size": ["1-10", "11-50", "51-200", "201+"]}
def order_vals(d, items):
    if d in NATURAL: return sorted(items, key=lambda kv: NATURAL[d].index(kv[0]))
    return sorted(items, key=lambda kv: -sl[d][kv[0]]["Q1"][1])
DIM_KEYS = {"channel": "Channel", "entry_page": "Entry page", "device": "Device",
            "visitor_type": "Visitor", "company_size": "Company size", "geo": "Geo"}

fin = q("SELECT strftime(close_month,'%b'), paying_customers, all_closed_opps, deal_value FROM finance_view ORDER BY close_month")
fcrm_up = q("""SELECT COUNT(*), MIN(days_to_close), MAX(days_to_close), MEDIAN(days_to_close), MIN(won_plan), MAX(won_plan)
               FROM signup_outcomes WHERE product='Free CRM' AND is_win = 1""")[0]

# derived headline numbers
n1, w1, cr1, mrr1 = per["Q1"]
n2, w2, cr2, mrr2 = per["Q2"]
trial1 = pp[("Q1", "Starter")][0] + pp[("Q1", "Pro")][0]
trial2 = pp[("Q2", "Starter")][0] + pp[("Q2", "Pro")][0]
free_n = pp[("Q2", "Free CRM")][0]
free_cr = pp[("Q2", "Free CRM")][1]
trial_w1 = pp[("Q1", "Starter")][2] + pp[("Q1", "Pro")][2]
trial_w2 = pp[("Q2", "Starter")][2] + pp[("Q2", "Pro")][2]
lost_wins = trial_w1 - trial_w2
trial_mrr = {r[0]: r[1] for r in q("""SELECT period, SUM(is_win * won_amount)/3.0
                                      FROM signup_outcomes WHERE product <> 'Free CRM' GROUP BY 1""")}
lost_mrr = trial_mrr["Q1"] - trial_mrr["Q2"]
be_wins = 100 * lost_wins / free_n
be_mrr = 100 * (lost_mrr / 35) / free_n
net_new = n2 - n1
substitution = trial1 - trial2
traffic_growth = 100 * (sess_q["Q2"] / sess_q["Q1"] - 1)

f0 = lambda x: f"{x:,.0f}"
f1 = lambda x: f"{x:,.1f}"
pct = lambda x: f"{x:.0f}%"

# ------------------------------------------------------------------ charts
W = 680  # svg viewBox width

def esc(s): return html.escape(str(s), quote=True)

def nice_max(v, step):
    import math
    return step * math.ceil(v / step)

def col_path(x, y_top, w, y_base, r=4):
    """Column with 4px rounded top, square base."""
    h = y_base - y_top
    if h <= 0: return ""
    r = min(r, h, w / 2)
    return (f"M{x:.1f},{y_base:.1f} V{y_top + r:.1f} Q{x:.1f},{y_top:.1f} {x + r:.1f},{y_top:.1f} "
            f"H{x + w - r:.1f} Q{x + w:.1f},{y_top:.1f} {x + w:.1f},{y_top + r:.1f} V{y_base:.1f} Z")

def stacked_columns(title_id, data, colors, ymax, ystep, fmt=f0, unit=""):
    """data: list per month of [(series, value)], bottom->top"""
    H, L, R, T, B = 260, 44, 16, 12, 28
    pw, ph = W - L - R, H - T - B
    band = pw / len(MONTHS); cw = min(24 * 1.6, band * 0.5)
    y = lambda v: T + ph * (1 - v / ymax)
    out = [f'<svg viewBox="0 0 {W} {H}" role="img" aria-labelledby="{title_id}">']
    for t in range(0, int(ymax) + 1, ystep):
        out.append(f'<line class="grid" x1="{L}" x2="{W-R}" y1="{y(t):.1f}" y2="{y(t):.1f}"/>'
                   f'<text class="tick" x="{L-8}" y="{y(t)+4:.1f}" text-anchor="end">{fmt(t)}</text>')
    for i, segs in enumerate(data):
        x = L + band * i + (band - cw) / 2
        base = 0
        total = sum(v for _, v in segs)
        for j, (s, v) in enumerate(segs):
            if not v: continue
            top_seg = j == max(k for k, (_, vv) in enumerate(segs) if vv)
            yb, yt = y(base), y(base + v)
            gap = 2 if base > 0 else 0
            if top_seg:
                d = col_path(x, yt, cw, yb - gap)
            else:
                d = f"M{x:.1f},{yt:.1f} H{x+cw:.1f} V{yb-gap:.1f} H{x:.1f} Z"
            out.append(f'<path d="{d}" fill="var({colors[s]})" data-tip="{esc(MONTHS[i])} · {esc(s)}: {fmt(v)}{unit} ({100*v/total:.0f}%)"/>')
            base += v
        out.append(f'<text class="val" x="{x+cw/2:.1f}" y="{y(total)-6:.1f}" text-anchor="middle">{fmt(total)}{unit}</text>')
        out.append(f'<text class="tick" x="{x+cw/2:.1f}" y="{H-8}" text-anchor="middle">{MONTHS[i]}</text>')
    out.append(f'<line class="axis" x1="{L}" x2="{W-R}" y1="{y(0):.1f}" y2="{y(0):.1f}"/>')
    out.append("</svg>")
    return "".join(out)

def line_chart(title_id, series, colors, ymax, ystep, unit="%"):
    """series: {name: [v or None]*6}"""
    H, L, R, T, B = 260, 44, 92, 16, 28
    pw, ph = W - L - R, H - T - B
    xs = [L + pw * i / (len(MONTHS) - 1) for i in range(len(MONTHS))]
    y = lambda v: T + ph * (1 - v / ymax)
    out = [f'<svg viewBox="0 0 {W} {H}" role="img" aria-labelledby="{title_id}">']
    for t in range(0, int(ymax) + 1, ystep):
        out.append(f'<line class="grid" x1="{L}" x2="{W-R}" y1="{y(t):.1f}" y2="{y(t):.1f}"/>'
                   f'<text class="tick" x="{L-8}" y="{y(t)+4:.1f}" text-anchor="end">{t}{unit}</text>')
    # launch marker
    xl = (xs[2] + xs[3]) / 2
    out.append(f'<line class="marker" x1="{xl:.1f}" x2="{xl:.1f}" y1="{T}" y2="{T+ph}"/>'
               f'<text class="note" x="{xl+6:.1f}" y="{T+10}">Free CRM launch</text>')
    ends = []
    for name, vals in series.items():
        pts = [(xs[i], y(v), v, i) for i, v in enumerate(vals) if v is not None]
        d = "M" + " L".join(f"{px:.1f},{py:.1f}" for px, py, _, _ in pts)
        dash = ' stroke-dasharray="1 0"' if name != "Blended" else ""
        out.append(f'<path d="{d}" fill="none" stroke="var({colors[name]})" class="ln{" blended" if name=="Blended" else ""}"/>')
        for px, py, v, i in pts:
            out.append(f'<circle cx="{px:.1f}" cy="{py:.1f}" r="4" fill="var({colors[name]})" class="dot" data-tip="{esc(MONTHS[i])} · {esc(name)}: {v:.1f}%"/>')
        ends.append([pts[-1][1], name, pts[-1][2]])
    ends.sort()
    for k in range(1, len(ends)):  # keep end labels 14px apart
        if ends[k][0] - ends[k-1][0] < 14: ends[k][0] = ends[k-1][0] + 14
    for py, name, v in ends:
        out.append(f'<text class="end" x="{xs[-1]+10:.1f}" y="{py+4:.1f}">{esc(name)} {v:.1f}%</text>')
    for i, m in enumerate(MONTHS):
        out.append(f'<text class="tick" x="{xs[i]:.1f}" y="{H-8}" text-anchor="middle">{m}</text>')
    out.append(f'<line class="axis" x1="{L}" x2="{W-R}" y1="{y(0):.1f}" y2="{y(0):.1f}"/>')
    out.append("</svg>")
    return "".join(out)

def waterfall(title_id):
    steps = [
        ("Q1 wins / month", kd[("Q1 wins / month", None)], "total"),
        ("More signups (volume)", kd[("Volume effect", None)], "delta"),
        ("Mix: fewer Starter trials", kd[("Mix effect", "Starter")], "delta"),
        ("Mix: fewer Pro trials", kd[("Mix effect", "Pro")], "delta"),
        ("Mix: Free CRM upgrades", kd[("Mix effect", "Free CRM")], "delta"),
        ("Conversion within each SKU", rate_total, "delta"),
        ("Q2 wins / month", kd[("Q2 wins / month", None)], "total"),
    ]
    H, L, R, T, B = 300, 44, 16, 24, 64
    pw, ph = W - L - R, H - T - B
    ymax = 400
    y = lambda v: T + ph * (1 - v / ymax)
    band = pw / len(steps); cw = min(40, band * 0.55)
    out = [f'<svg viewBox="0 0 {W} {H}" role="img" aria-labelledby="{title_id}">']
    for t in range(0, ymax + 1, 100):
        out.append(f'<line class="grid" x1="{L}" x2="{W-R}" y1="{y(t):.1f}" y2="{y(t):.1f}"/>'
                   f'<text class="tick" x="{L-8}" y="{y(t)+4:.1f}" text-anchor="end">{t}</text>')
    run = 0
    prev_end = None
    for i, (lab, v, kind) in enumerate(steps):
        x = L + band * i + (band - cw) / 2
        if kind == "total":
            a, b = 0, v; run = v; fill = "--ink-total"
        else:
            a, b = run, run + v; run = b
            fill = "--pos" if v >= 0 else "--neg"
        lo, hi = min(a, b), max(a, b)
        yt, yb = y(hi), y(lo)
        hgt = max(yb - yt, 1.5)
        out.append(f'<rect x="{x:.1f}" y="{yt:.1f}" width="{cw:.1f}" height="{hgt:.1f}" rx="3" fill="var({fill})" '
                   f'data-tip="{esc(lab)}: {"" if kind=="total" else ("+" if v>=0 else "−")}{abs(v):.1f} wins/month"/>')
        if prev_end is not None:
            out.append(f'<line class="conn" x1="{prev_end[0]:.1f}" x2="{x:.1f}" y1="{prev_end[1]:.1f}" y2="{prev_end[1]:.1f}"/>')
        prev_end = (x + cw, y(run))
        txt = f0(v) if kind == "total" else (("+" if v >= 0 else "−") + f0(abs(v)))
        out.append(f'<text class="val" x="{x+cw/2:.1f}" y="{yt-6:.1f}" text-anchor="middle">{txt}</text>')
        words = lab.split(" ")
        lines, cur = [], ""
        for wd in words:
            if len(cur) + len(wd) > 13 and cur: lines.append(cur); cur = wd
            else: cur = (cur + " " + wd).strip()
        lines.append(cur)
        for k, ln in enumerate(lines[:3]):
            out.append(f'<text class="tick" x="{x+cw/2:.1f}" y="{H-B+16+k*13}" text-anchor="middle">{esc(ln)}</text>')
    out.append(f'<line class="axis" x1="{L}" x2="{W-R}" y1="{y(0):.1f}" y2="{y(0):.1f}"/>')
    out.append("</svg>")
    return "".join(out)

def dumbbell(title_id):
    order = ["Channel", "Entry page", "Device", "Visitor", "Company size", "Geo"]
    rows = []
    for d in order:
        vals = order_vals(d, sl[d].items())
        rows.append(("hdr", d))
        for v, per_ in vals:
            rows.append(("row", d, v, per_["Q1"], per_["Q2"]))
    rh, L, R, T = 22, 150, 20, 30
    H = T + rh * len(rows) + 24
    xmax = 40
    x = lambda v: L + (W - L - R) * v / xmax
    out = [f'<svg viewBox="0 0 {W} {H}" role="img" aria-labelledby="{title_id}">']
    for t in range(0, xmax + 1, 10):
        out.append(f'<line class="grid" x1="{x(t):.1f}" x2="{x(t):.1f}" y1="{T-8}" y2="{H-24}"/>'
                   f'<text class="tick" x="{x(t):.1f}" y="{H-8}" text-anchor="middle">{t}%</text>')
    out.append(f'<text class="tick" x="{x(cr1):.1f}" y="{T-14}" text-anchor="middle">Q1 avg {cr1:.0f}%</text>'
               f'<line class="marker" x1="{x(cr1):.1f}" x2="{x(cr1):.1f}" y1="{T-8}" y2="{H-24}"/>'
               f'<text class="tick" x="{x(cr2):.1f}" y="{T-14}" text-anchor="middle">Q2 avg {cr2:.0f}%</text>'
               f'<line class="marker" x1="{x(cr2):.1f}" x2="{x(cr2):.1f}" y1="{T-8}" y2="{H-24}"/>')
    yy = T
    for r in rows:
        if r[0] == "hdr":
            out.append(f'<text class="hdr" x="8" y="{yy+15}">{esc(r[1])}</text>')
        else:
            _, d, v, a, b = r
            cy = yy + rh / 2 + 2
            out.append(f'<text class="lab" x="{L-10}" y="{cy+4:.1f}" text-anchor="end">{esc(lab(v))}</text>')
            out.append(f'<line class="bar-conn" x1="{x(b[1]):.1f}" x2="{x(a[1]):.1f}" y1="{cy:.1f}" y2="{cy:.1f}"/>')
            tip = f"{d} · {lab(v)}: Q1 {a[1]:.1f}% → Q2 {b[1]:.1f}% ({b[1]-a[1]:+.1f}pp) · Q2 Free CRM share {b[2]:.0f}% · n={a[0]+b[0]:,}"
            out.append(f'<circle cx="{x(a[1]):.1f}" cy="{cy:.1f}" r="5" fill="var(--q1)" class="dot" data-tip="{esc(tip)}"/>')
            out.append(f'<circle cx="{x(b[1]):.1f}" cy="{cy:.1f}" r="5" fill="var(--q2)" class="dot" data-tip="{esc(tip)}"/>')
        yy += rh
    out.append("</svg>")
    return "".join(out)

def hbars(title_id, items, xmax, unit="%"):
    rh, L, R, T = 36, 230, 60, 8
    H = T + rh * len(items) + 8
    x = lambda v: L + (W - L - R) * v / xmax
    out = [f'<svg viewBox="0 0 {W} {H}" role="img" aria-labelledby="{title_id}">']
    for i, (lab, v, color) in enumerate(items):
        cy = T + rh * i + rh / 2
        w = x(v) - L
        r = min(4, w / 2)
        d = (f"M{L},{cy-10} H{L+w-r:.1f} Q{L+w:.1f},{cy-10} {L+w:.1f},{cy-10+r:.1f} V{cy+10-r:.1f} "
             f"Q{L+w:.1f},{cy+10} {L+w-r:.1f},{cy+10} H{L} Z")
        out.append(f'<text class="lab" x="{L-10}" y="{cy+4:.1f}" text-anchor="end">{esc(lab)}</text>')
        out.append(f'<path d="{d}" fill="var({color})" data-tip="{esc(lab)}: {v:.1f}{unit}"/>')
        out.append(f'<text class="val" x="{L+w+8:.1f}" y="{cy+4:.1f}">{v:.1f}{unit}</text>')
    out.append(f'<line class="axis" x1="{L}" x2="{L}" y1="{T}" y2="{H-8}"/>')
    out.append("</svg>")
    return "".join(out)


weekly = q("SELECT week_start, signups, wins_30d, signup_to_win_pct FROM weekly_funnel ORDER BY 1")

def panels_weekly(title_id):
    """Two stacked panels on one shared week axis: signups (columns) and
    signup->paid conversion (line). Two panels instead of a dual axis."""
    import datetime as dt
    n = len(weekly)
    L, R, T = 52, 70, 22
    H1, GAP, H2, B = 150, 46, 150, 30
    H = T + H1 + GAP + H2 + B
    pw = W - L - R
    band = pw / n; cw = min(14, band * 0.62)
    xc = lambda i: L + band * i + band / 2
    smax = 400
    y1 = lambda v: T + H1 * (1 - v / smax)
    cmax = 40
    top2 = T + H1 + GAP
    y2 = lambda v: top2 + H2 * (1 - v / cmax)
    out = [f'<svg viewBox="0 0 {W} {H}" role="img" aria-labelledby="{title_id}">']
    # panel titles
    out.append(f'<text class="hdr" x="{L}" y="{T-8}">Signups per week</text>')
    out.append(f'<text class="hdr" x="{L}" y="{top2-8}">Signup → paid conversion (30-day)</text>')
    for t in range(0, smax + 1, 100):
        out.append(f'<line class="grid" x1="{L}" x2="{W-R}" y1="{y1(t):.1f}" y2="{y1(t):.1f}"/>'
                   f'<text class="tick" x="{L-8}" y="{y1(t)+4:.1f}" text-anchor="end">{t}</text>')
    for t in range(0, cmax + 1, 10):
        out.append(f'<line class="grid" x1="{L}" x2="{W-R}" y1="{y2(t):.1f}" y2="{y2(t):.1f}"/>'
                   f'<text class="tick" x="{L-8}" y="{y2(t)+4:.1f}" text-anchor="end">{t}%</text>')
    # columns
    for i, (wk, sg, wn, cr) in enumerate(weekly):
        x = xc(i) - cw / 2
        tip = f"Week of {wk:%b %-d}: {sg:,} signups · {cr:.1f}% signup → paid ({int(wn)} paying)"
        out.append(f'<path d="{col_path(x, y1(sg), cw, y1(0))}" fill="var(--bar-neutral)" data-tip="{esc(tip)}"/>')
    # line
    pts = [(xc(i), y2(cr), cr, wk, sg, wn) for i, (wk, sg, wn, cr) in enumerate(weekly)]
    out.append('<path d="M' + " L".join(f"{px:.1f},{py:.1f}" for px, py, *_ in pts) + '" fill="none" stroke="var(--s1)" class="ln"/>')
    for px, py, cr, wk, sg, wn in pts:
        tip = f"Week of {wk:%b %-d}: {cr:.1f}% signup → paid · {sg:,} signups"
        out.append(f'<circle cx="{px:.1f}" cy="{py:.1f}" r="4" fill="var(--s1)" class="dot" data-tip="{esc(tip)}"/>')
    # period averages as labels on the line panel
    q1w = [r for r in weekly if r[0] < dt.date(2026, 3, 30)]
    q2w = [r for r in weekly if r[0] >= dt.date(2026, 4, 6)]
    a1 = 100 * sum(r[2] for r in q1w) / sum(r[1] for r in q1w)
    a2 = 100 * sum(r[2] for r in q2w) / sum(r[1] for r in q2w)
    out.append(f'<text class="end" x="{xc(0):.1f}" y="{y2(a1)-14:.1f}">Before launch: ~{a1:.0f}%</text>')
    out.append(f'<text class="end" x="{xc(len(weekly)-1):.1f}" y="{y2(a2)-14:.1f}" text-anchor="end">After launch: ~{a2:.0f}%</text>')
    # launch marker: Apr 1 sits 2 days into the week of Mar 30
    li = next(i for i, r in enumerate(weekly) if r[0] == dt.date(2026, 3, 30))
    xl = L + band * li + band * (2 / 7)
    out.append(f'<line class="launch" x1="{xl:.1f}" x2="{xl:.1f}" y1="{T-2}" y2="{top2+H2}"/>')
    out.append(f'<text class="note" x="{xl+6:.1f}" y="{T+10}">Free CRM launch · Apr 1</text>')
    # month labels at the first full week of each month
    seen = set()
    for i, r in enumerate(weekly):
        m = r[0].month if r[0].day <= 7 else None
        if m and m not in seen:
            seen.add(m)
            out.append(f'<text class="tick" x="{xc(i):.1f}" y="{H-10}" text-anchor="middle">{r[0]:%b %-d}</text>')
    out.append(f'<line class="axis" x1="{L}" x2="{W-R}" y1="{y1(0):.1f}" y2="{y1(0):.1f}"/>')
    out.append(f'<line class="axis" x1="{L}" x2="{W-R}" y1="{y2(0):.1f}" y2="{y2(0):.1f}"/>')
    out.append("</svg>")
    return "".join(out), a1, a2


def combo_weekly(title_id):
    """Columns = weekly signups (right axis), line = signup->paid conversion (left axis).
    Both axes start at zero so the visual relationship isn't distorted."""
    import datetime as dt
    n = len(weekly)
    L, R, T, B = 52, 56, 36, 30
    H = 330
    ph = H - T - B
    pw = W - L - R
    band = pw / n; cw = min(14, band * 0.62)
    xc = lambda i: L + band * i + band / 2
    smax, cmax = 400, 40
    ys = lambda v: T + ph * (1 - v / smax)
    yc = lambda v: T + ph * (1 - v / cmax)
    out = [f'<svg viewBox="0 0 {W} {H}" role="img" aria-labelledby="{title_id}">']
    out.append(f'<text class="axt" x="2" y="{T-14}">Conversion</text>')
    out.append(f'<text class="axt" x="{W-R+8}" y="{T-14}">Signups</text>')
    for k in range(0, 5):
        cv, sv = k * 10, k * 100
        y = yc(cv)
        out.append(f'<line class="grid" x1="{L}" x2="{W-R}" y1="{y:.1f}" y2="{y:.1f}"/>'
                   f'<text class="tick" x="{L-8}" y="{y+4:.1f}" text-anchor="end">{cv}%</text>'
                   f'<text class="tick" x="{W-R+8}" y="{y+4:.1f}">{sv}</text>')
    for i, (wk, sg, wn, cr) in enumerate(weekly):
        x = xc(i) - cw / 2
        tip = f"Week of {wk:%b %-d}: {sg:,} signups · {cr:.1f}% signup → paid ({int(wn)} paying)"
        out.append(f'<path d="{col_path(x, ys(sg), cw, ys(0))}" fill="var(--bar-neutral)" data-tip="{esc(tip)}"/>')
    pts = [(xc(i), yc(cr), cr, wk, sg) for i, (wk, sg, wn, cr) in enumerate(weekly)]
    out.append('<path d="M' + " L".join(f"{px:.1f},{py:.1f}" for px, py, *_ in pts) + '" fill="none" stroke="var(--s1)" class="ln"/>')
    for px, py, cr, wk, sg in pts:
        tip = f"Week of {wk:%b %-d}: {cr:.1f}% signup → paid · {sg:,} signups"
        out.append(f'<circle cx="{px:.1f}" cy="{py:.1f}" r="4" fill="var(--s1)" class="dot" data-tip="{esc(tip)}"/>')
    q1w = [r for r in weekly if r[0] < dt.date(2026, 3, 30)]
    q2w = [r for r in weekly if r[0] >= dt.date(2026, 4, 6)]
    a1 = 100 * sum(r[2] for r in q1w) / sum(r[1] for r in q1w)
    a2 = 100 * sum(r[2] for r in q2w) / sum(r[1] for r in q2w)
    li = next(i for i, r in enumerate(weekly) if r[0] == dt.date(2026, 3, 30))
    xl = L + band * li + band * (2 / 7)
    out.append(f'<line class="launch" x1="{xl:.1f}" x2="{xl:.1f}" y1="{T-6}" y2="{T+ph}"/>')
    out.append(f'<text class="note" x="{xl+6:.1f}" y="{T+2}">Free CRM launch · Apr 1</text>')
    out.append(f'<text class="end halo" x="{xc(1):.1f}" y="{yc(36):.1f}">Conversion before launch: ~{a1:.0f}%</text>')
    out.append(f'<text class="end halo" x="{xc(n-1):.1f}" y="{yc(19):.1f}" text-anchor="end">After launch: ~{a2:.0f}%</text>')
    seen = set()
    for i, r in enumerate(weekly):
        if r[0].day <= 7 and r[0].month not in seen:
            seen.add(r[0].month)
            out.append(f'<text class="tick" x="{xc(i):.1f}" y="{H-10}" text-anchor="middle">{r[0]:%b %-d}</text>')
    out.append(f'<line class="axis" x1="{L}" x2="{W-R}" y1="{T+ph:.1f}" y2="{T+ph:.1f}"/>')
    out.append("</svg>")
    return "".join(out), a1, a2


def gap_bars(title_id, rows):
    """Bullet bars: light track = amount needed, filled = what Free CRM delivers today."""
    L, R, T, rh = 210, 150, 10, 64
    H = T + rh * len(rows) + 4
    pw = W - L - R
    out = [f'<svg viewBox="0 0 {W} {H}" role="img" aria-labelledby="{title_id}">']
    for i, (label, have, need, fmt, have_note, need_note) in enumerate(rows):
        cy = T + rh * i + 26
        x = lambda v: L + pw * v / need
        out.append(f'<text class="lab" x="{L-12}" y="{cy+4:.1f}" text-anchor="end">{esc(label)}</text>')
        out.append(f'<rect x="{L}" y="{cy-12}" width="{pw:.1f}" height="24" rx="4" fill="var(--track)" '
                   f'data-tip="{esc(label)}: {fmt(need)} needed ({need_note})"/>')
        out.append(f'<rect x="{L}" y="{cy-12}" width="{x(have)-L:.1f}" height="24" rx="4" fill="var(--s3)" '
                   f'data-tip="{esc(label)}: {fmt(have)} today ({have_note})"/>')
        out.append(f'<text class="val" x="{L+6:.1f}" y="{cy+30:.1f}">Today: {fmt(have)} · {esc(have_note)}</text>')
        out.append(f'<text class="val" x="{W-R+10:.1f}" y="{cy+4:.1f}">Needed: {fmt(need)}</text>')
        out.append(f'<text class="tick" x="{W-R+10:.1f}" y="{cy+19:.1f}">{esc(need_note)}</text>')
    out.append("</svg>")
    return "".join(out)

def legend(items):
    return '<div class="legend">' + "".join(
        f'<span><i style="background:var({c})"></i>{esc(n)}</span>' for n, c in items) + "</div>"

PC = {"Starter": "--s1", "Pro": "--s2", "Free CRM": "--s3", "Blended": "--ink-total"}

ch_weekly, wk_a1, wk_a2 = combo_weekly("c0t")
ch_signups = stacked_columns("c1t", [[(p, pv(p, "n", i + 1) or 0) for p in PRODUCTS] for i in range(6)], PC, 1500, 500)
blended = [r[5] for r in funnel]
ch_conv = line_chart("c3t", {"Starter": [pv("Starter", "cr", i + 1) for i in range(6)],
                             "Pro": [pv("Pro", "cr", i + 1) for i in range(6)],
                             "Free CRM": [pv("Free CRM", "cr", i + 1) for i in range(6)],
                             "Blended": blended}, PC, 40, 10)
ch_water = waterfall("c4t")
ch_dumb = dumbbell("c5t")
free_w = pp[("Q2", "Free CRM")][2]
neutral_cr = 100 * (w1 - trial_w2) / free_n   # Free CRM conversion that keeps total wins flat QoQ

# ------------------------------------------------------------------ tables
def table(head, rows, cls=""):
    h = "".join(f"<th>{esc(c)}</th>" for c in head)
    b = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows)
    return f'<div class="tbl"><table class="{cls}"><thead><tr>{h}</tr></thead><tbody>{b}</tbody></table></div>'

t_funnel = table(["Signup month", "Sessions", "Signups", "Paid (30d)", "New deal value (30d)", "Session → signup", "Signup → paid", "Session → paid"],
                 [[MONTHS[i], f0(r[0]), f0(r[1]), f0(r[2]), "$" + f0(r[3]), f"{r[4]:.2f}%", f"{r[5]:.1f}%", f"{r[6]:.2f}%"] for i, r in enumerate(funnel)], "num")

def prow(p):
    a = pp.get(("Q1", p)); b = pp[("Q2", p)]
    mixa = 100 * a[0] / n1 if a else 0; mixb = 100 * b[0] / n2
    return [f'<i class="sw" style="background:var({PC[p]})"></i>{p}', f0(a[0]) if a else "—", f0(b[0]),
            pct(mixa) if a else "—", pct(mixb), f"{a[1]:.1f}%" if a else "—", f"{b[1]:.1f}%", f0(a[2]) if a else "—", f0(b[2])]
t_prod = table(["SKU", "Signups/mo Q1", "Signups/mo Q2", "Mix Q1", "Mix Q2", "Conv. Q1", "Conv. Q2", "Paid/mo Q1", "Paid/mo Q2"],
               [prow(p) for p in PRODUCTS] + [["<b>All signups</b>", f0(n1), f0(n2), "100%", "100%", f"<b>{cr1:.1f}%</b>", f"<b>{cr2:.1f}%</b>", f"<b>{f0(w1)}</b>", f"<b>{f0(w2)}</b>"]], "num")

t_kit = table(["Step", "Wins / month", "What it means"], [
    ["Q1 baseline", f1(kd[("Q1 wins / month", None)]), "Average paying customers per month, Jan–Mar"],
    ["Volume effect", f"+{f1(kd[('Volume effect', None)])}", "More signups at the average conversion"],
    ["Mix effect", f1(mix_total), "Signups moving from trials to Free CRM"],
    ["&nbsp;&nbsp;↳ Starter", f1(kd[("Mix effect", "Starter")]), ""],
    ["&nbsp;&nbsp;↳ Pro", f1(kd[("Mix effect", "Pro")]), ""],
    ["&nbsp;&nbsp;↳ Free CRM", f"+{f1(kd[('Mix effect', 'Free CRM')])}", ""],
    ["Rate effect", f1(rate_total), "Change in conversion inside each SKU"],
    ["&nbsp;&nbsp;↳ Starter", f"+{f1(kd[('Rate effect', 'Starter')])}", ""],
    ["&nbsp;&nbsp;↳ Pro", f1(kd[("Rate effect", "Pro")]), ""],
    ["Q2", f1(kd[("Q2 wins / month", None)]), "Average paying customers per month, Apr–Jun"],
], "kit")

def slice_tables():
    out = []
    for key, d in DIM_KEYS.items():
        rows = []
        vals = order_vals(d, [kv for kv in slice_month[key].items() if kv[0] in sl[d]])
        for v, mm in vals:
            if v not in sl[d]: continue
            a, b = sl[d][v]["Q1"], sl[d][v]["Q2"]
            rows.append([esc(lab(v))] + [f"{mm[i][1]:.1f}" if i in mm else "—" for i in range(1, 7)] +
                        [f"{a[1]:.1f}", f"{b[1]:.1f}", f"{b[1]-a[1]:+.1f}", f"{b[2]:.0f}%", f0((a[0] + b[0]) / 6)])
        rows.append(["<b>All signups</b>"] + [f"<b>{r[5]:.1f}</b>" for r in funnel] + [f"<b>{cr1:.1f}</b>", f"<b>{cr2:.1f}</b>", f"<b>{cr2-cr1:+.1f}</b>", "", f"<b>{f0((n1+n2)/2)}</b>"])
        out.append(f"<h4>{d}</h4>" + table([d] + MONTHS + ["Q1", "Q2", "Δ pp", "Free share Q2", "Signups/mo"], rows, "num"))
    return "".join(out)

trows = sorted(traffic, key=lambda r: -(r[2] - r[1]))
t_traffic = table(["Channel", "Sessions/mo Q1", "Sessions/mo Q2", "Δ sessions", "Share of new sessions", "Session → signup Q1", "Session → signup Q2", "Share of new signups"],
    [[esc(r[0]), f0(r[1]), f0(r[2]), f"{r[2]-r[1]:+,.0f}", f"{100*(r[2]-r[1])/d_sess_tot:.0f}%", f"{r[3]:.2f}%", f"{r[4]:.2f}%", f"{100*r[5]/d_sig_tot:.0f}%"] for r in trows]
    + [["<b>All channels</b>", f"<b>{f0(sess_q['Q1'])}</b>", f"<b>{f0(sess_q['Q2'])}</b>", f"<b>{d_sess_tot:+,.0f}</b>", "<b>100%</b>",
        f"<b>{100*n1/sess_q['Q1']:.2f}%</b>", f"<b>{100*n2/sess_q['Q2']:.2f}%</b>", "<b>100%</b>"]], "num")

weekly_full = q("SELECT week_start, signups, free_crm_signups, wins_30d, signup_to_win_pct FROM weekly_funnel ORDER BY 1")
t_weekly = table(["Week of", "Signups", "Free CRM share", "Paying customers (30d)", "Signup → paid"],
    [[f"{w:%b %-d}", f0(n), f"{100*fc/n:.0f}%", f0(wn), f"{cr:.1f}%"] for w, n, fc, wn, cr in weekly_full], "num")
sku_rows = []
for m in range(1, 7):
    for p_ in PRODUCTS:
        d_ = prod[p_].get(m)
        if d_:
            sku_rows.append([MONTHS[m-1], f'<i class="sw" style="background:var({PC[p_]})"></i>{p_}', f0(d_["n"]), f'{d_["mix"]:.0f}%', f'{d_["cr"]:.1f}%', f0(d_["w"]), "$" + f0(d_["mrr"])])
t_sku_month = table(["Month", "SKU", "Signups", "Mix", "Signup → paid", "Paying customers (30d)", "Deal value (30d)"], sku_rows, "num")

t_fin = table(["Close month", "Paying customers", "All closed opps (incl. $0)", "New deal value"],
              [[m, f0(p), f0(a), "$" + f0(mr)] for m, p, a, mr in fin])

WIN_SQL = "-- STEP 4." + Path("sql/01_clean.sql").read_text().split("-- STEP 4.")[1]

# ------------------------------------------------------------------ page
page = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Northwind CRM — Analysis</title>
<style>
:root {{
  color-scheme: light;
  --bg:#f9f9f7; --surface:#fcfcfb; --fg:#0b0b0b; --fg2:#52514e; --muted:#898781;
  --line:#e1e0d9; --axis:#c3c2b7; --accent:#1c5cab; --callout:#eef4fc;
  --s1:#2a78d6; --s2:#eb6834; --s3:#1baf7a; --ink-total:#6b6a66;
  --pos:#2a78d6; --neg:#e34948; --q1:#a9a8a2; --q2:#2a78d6; --bar-neutral:#b9b8b1; --track:#e4e3dd;
}}
@media (prefers-color-scheme: dark) {{
  :root:where(:not([data-theme="light"])) {{
    color-scheme: dark;
    --bg:#0d0d0d; --surface:#1a1a19; --fg:#f0efec; --fg2:#c3c2b7; --muted:#898781;
    --line:#2c2c2a; --axis:#383835; --accent:#86b6ef; --callout:#16202c;
    --s1:#3987e5; --s2:#d95926; --s3:#199e70; --ink-total:#8a8984;
    --pos:#3987e5; --neg:#e66767; --q1:#6b6a66; --q2:#3987e5; --bar-neutral:#5a5955; --track:#2e2e2c;
  }}
}}
:root[data-theme="dark"] {{
  color-scheme: dark;
  --bg:#0d0d0d; --surface:#1a1a19; --fg:#f0efec; --fg2:#c3c2b7; --muted:#898781;
  --line:#2c2c2a; --axis:#383835; --accent:#86b6ef; --callout:#16202c;
  --s1:#3987e5; --s2:#d95926; --s3:#199e70; --ink-total:#8a8984;
  --pos:#3987e5; --neg:#e66767; --q1:#6b6a66; --q2:#3987e5; --bar-neutral:#5a5955; --track:#2e2e2c;
}}
* {{ box-sizing:border-box; }}
body {{ margin:0; background:var(--bg); color:var(--fg); font:16px/1.6 system-ui,-apple-system,"Segoe UI",sans-serif; }}
main {{ max-width:1040px; margin:0 auto; padding:48px 16px 96px; }}
a {{ color:var(--accent); }}
nav.crumbs {{ font-size:14px; color:var(--muted); margin-bottom:24px; }}
h1 {{ font-size:30px; line-height:1.2; letter-spacing:-0.01em; margin:0 0 6px; }}
.date {{ color:var(--muted); font-size:14px; margin-bottom:28px; }}
h2 {{ font-size:22px; margin:56px 0 12px; padding-top:20px; border-top:1px solid var(--line); }}
h3 {{ font-size:17px; margin:36px 0 6px; }}
h4 {{ font-size:15px; margin:28px 0 8px; }}
p, li {{ max-width:80ch; }}
.tldr {{ font-size:18px; line-height:1.55; }}
.tiles {{ display:grid; grid-template-columns:repeat(4,1fr); gap:12px; margin:28px 0; }}
.tile {{ background:var(--surface); border:1px solid var(--line); border-radius:10px; padding:14px 16px; }}
.tile .l {{ font-size:13px; color:var(--fg2); }}
.tile .v {{ font-size:24px; font-weight:600; margin-top:4px; }}
.tile .v .q {{ font-size:15px; font-weight:500; color:var(--fg2); }}
.tile .d {{ font-size:13px; color:var(--fg2); margin-top:2px; }}
@media (max-width:640px) {{ .tiles {{ grid-template-columns:repeat(2,1fr); }} }}
.callout {{ background:var(--callout); border-radius:10px; padding:14px 18px; margin:24px 0; font-size:15px; }}
.callout b {{ display:block; margin-bottom:2px; }}
ol.findings > li {{ margin-bottom:16px; }}
.hyp li {{ margin-bottom:6px; }}
.verdict {{ font-size:13px; font-weight:600; padding:2px 8px; border-radius:999px; border:1px solid var(--line); margin-left:6px; white-space:nowrap; }}
figure {{ margin:24px 0 32px; background:var(--surface); border:1px solid var(--line); border-radius:12px; padding:18px 18px 12px; }}
figcaption .t {{ font-weight:600; font-size:15px; }}
figcaption .s {{ color:var(--fg2); font-size:14px; margin-top:2px; }}
figure svg {{ width:100%; height:auto; display:block; margin-top:12px; overflow:visible; }}
.legend {{ display:flex; flex-wrap:wrap; gap:14px; font-size:13px; color:var(--fg2); margin-top:10px; }}
.legend i {{ display:inline-block; width:10px; height:10px; border-radius:3px; margin-right:6px; vertical-align:-1px; }}
.note-foot {{ font-size:13px; color:var(--fg2); margin-top:8px; }}
svg .grid {{ stroke:var(--line); stroke-width:1; }}
svg .axis {{ stroke:var(--axis); stroke-width:1; }}
svg .tick {{ fill:var(--muted); font-size:11px; font-variant-numeric:tabular-nums; }}
svg .val {{ fill:var(--fg2); font-size:12px; font-weight:600; }}
svg .end {{ fill:var(--fg2); font-size:12px; }}
svg .lab {{ fill:var(--fg2); font-size:12px; }}
svg .hdr {{ fill:var(--fg); font-size:12px; font-weight:600; }}
svg .note {{ fill:var(--muted); font-size:11px; }}
svg .marker {{ stroke:var(--axis); stroke-width:1; }}
svg .halo {{ paint-order:stroke; stroke:var(--surface); stroke-width:4px; stroke-linejoin:round; font-weight:600; }}
svg .axt {{ fill:var(--fg2); font-size:11px; font-weight:600; }}
svg .launch {{ stroke:var(--fg2); stroke-width:1.5; stroke-dasharray:4 4; }}
svg .conn {{ stroke:var(--muted); stroke-width:1; }}
svg .bar-conn {{ stroke:var(--axis); stroke-width:2; }}
svg .ln {{ stroke-width:2; stroke-linejoin:round; stroke-linecap:round; }}
svg .ln.blended {{ stroke-dasharray:5 4; }}
svg .dot {{ stroke:var(--surface); stroke-width:2; }}
svg [data-tip] {{ cursor:default; }}
svg [data-tip]:hover {{ opacity:.85; }}
#tip {{ position:fixed; pointer-events:none; background:var(--fg); color:var(--bg); font-size:12px; padding:6px 9px; border-radius:6px; max-width:300px; opacity:0; transition:opacity .08s; z-index:10; }}
.tbl {{ overflow-x:auto; margin:12px 0 20px; }}
table {{ border-collapse:collapse; width:100%; font-size:14px; font-variant-numeric:tabular-nums; }}
th, td {{ padding:7px 10px; border-bottom:1px solid var(--line); text-align:right; white-space:nowrap; }}
th {{ font-size:12px; color:var(--fg2); font-weight:600; vertical-align:bottom; }}
th:first-child, td:first-child {{ text-align:left; }}
table.num th, table.num td {{ font-size:12.5px; padding:6px 7px; }}
table.kit td:nth-child(3), table.kit th:nth-child(3) {{ text-align:left; color:var(--fg2); }}
.sw {{ display:inline-block; width:10px; height:10px; border-radius:3px; margin-right:7px; }}
details {{ margin:12px 0; }}
summary {{ cursor:pointer; font-weight:600; }}
pre {{ background:var(--surface); border:1px solid var(--line); border-radius:8px; padding:14px; overflow-x:auto; font-size:12.5px; line-height:1.5; }}
.gloss li {{ margin-bottom:6px; }}
.pending {{ border:1px dashed var(--axis); border-radius:10px; padding:16px 18px; color:var(--fg2); }}
sup a {{ text-decoration:none; }}
</style>
</head>
<body>
<main>
<nav class="crumbs"><a href="./">Northwind CRM case</a> / Analysis</nav>
<h1>Why paying customers dropped while signups grew</h1>
<div class="date">Northwind CRM · Self-serve funnel · Data Jan 1 – Jun 30, 2026</div>

<p class="tldr">Paying customers dropped {100*(1-w2/w1):.0f}% QoQ after Free CRM launched ({f0(w1)} → {f0(w2)} per month), even though signups grew {100*(n2/n1-1):.0f}% QoQ. Signup-to-paid conversion by SKU didn't change. What changed is the SKU mix: Free CRM became the primary call-to-action across the site on Apr 1 and now takes {pct(100*free_n/n2)} of signups, but only {free_cr:.1f}% of them become paying customers, vs ~{pp[("Q2","Starter")][1]:.0f}% for Starter and Pro trials. The shift in SKU mix accounts for the drop.</p>

<div class="tiles">
  <div class="tile"><div class="l">Paying customers / month</div><div class="v"><span class="q">Q2:</span> {f0(w2)}</div><div class="d">Q1: {f0(w1)} · QoQ {100*(w2/w1-1):+.0f}%</div></div>
  <div class="tile"><div class="l">Signups / month</div><div class="v"><span class="q">Q2:</span> {f0(n2)}</div><div class="d">Q1: {f0(n1)} · QoQ {100*(n2/n1-1):+.0f}%</div></div>
  <div class="tile"><div class="l">Signup → paid</div><div class="v"><span class="q">Q2:</span> {cr2:.1f}%</div><div class="d">Q1: {cr1:.1f}% · QoQ {cr2-cr1:+.1f}pp</div></div>
  <div class="tile"><div class="l">New deal value / month</div><div class="v"><span class="q">Q2:</span> ${mrr2/1000:.1f}K</div><div class="d">Q1: ${mrr1/1000:.1f}K · QoQ {100*(mrr2/mrr1-1):+.0f}%</div></div>
</div>

<h2>Data</h2>
<p>We used {f0(n_sessions)} website sessions, {f0(n_signups)} signups and {f0(n_opps)} closed opportunities. Sessions and signups cover Jan 1 – Jun 30, 2026; opportunities run to {opp_end:%b %-d} so June signups have time to close. Signups are grouped by the month they signed up (cohorts) and compared as Q1 (Jan–Mar, before Free CRM) vs Q2 (Apr–Jun, after launch) using monthly averages. A paying customer is an opportunity with amount &gt; $0 closed within 30 days of signup. How the data was validated, cleaned and joined is in <a href="data-methodology.html">Data methodology</a>.</p>
<h2>Problem</h2>
<p>Northwind CRM shows an apparent signup-to-paid conversion problem: blended conversion fell from {cr1:.0f}% to {cr2:.0f}% and paying customers dropped ~{100*(1-w2/w1):.0f}% QoQ ({f0(w1)} → {f0(w2)}/month), even as signups grew {100*(n2/n1-1):.0f}% QoQ. The timing aligns with the launch of a new packaging scheme that includes a freemium plan.</p>

<h2>Hypotheses</h2>
<ol class="hyp">
  <li><b>Free CRM is cannibalizing Starter and Pro (SKU mix shift).</b> People who used to start a Pro or Starter trial now get Free CRM. If Free CRM converts at a lower rate, it could be pulling down the blended conversion rate.</li>
  <li><b>Signup quality deteriorated (top of funnel).</b> Lower-quality signups could also explain the drop in conversion, regardless of which SKU people sign up for.</li>
</ol>

<h2>What we found</h2>
<ol class="findings">
  <li><b>The SKU mix shifted; signup-to-paid conversion by SKU didn't.</b> Starter went from {pct(100*pp[("Q1","Starter")][0]/n1)} of signups to {pct(100*pp[("Q2","Starter")][0]/n2)}, Pro from {pct(100*pp[("Q1","Pro")][0]/n1)} to {pct(100*pp[("Q2","Pro")][0]/n2)}, and Free CRM took {pct(100*free_n/n2)}. Signup-to-paid by SKU stayed flat (Starter {pp[("Q1","Starter")][1]:.0f}% → {pp[("Q2","Starter")][1]:.0f}%, Pro {pp[("Q1","Pro")][1]:.0f}% → {pp[("Q2","Pro")][1]:.0f}%<sup><a href="#pro">†</a></sup>).</li>
  <li><b>The drop is the same across every top-of-funnel trait.</b> Channel, entry page, device, new vs returning visitor, company size and country all fall 12–22pp QoQ in signup-to-paid conversion, all in April, after a flat Q1. Free CRM takes 65–74% of Q2 signups in every slice. Signup quality doesn't explain the drop.</li>
  <li><b>Net signup growth is much smaller than Free CRM's volume.</b> Starter and Pro trial signups dropped by {f0(substitution)}/month QoQ and Free CRM grew by {f0(free_n)}, netting out at +{f0(net_new)} signups/month QoQ. That lift could be attributed to Free CRM, but not conclusively<sup><a href="#star">*</a></sup>.</li>
  <li><b>Free CRM upgrades go only to Starter.</b> All {fcrm_up[0]} Free CRM upgrades were to Starter ($35); none went to Pro. All happened within {fcrm_up[2]} days of signup.</li>
  <li><b>Traffic growth came almost entirely from low-converting sources.</b> Sessions grew {traffic_growth:.0f}% QoQ, and {low_sess_share:.0f}% of the new sessions came from Display and Direct. Those two channels brought only {low_sig_share:.0f}% of the new signups: Display turns fewer than 0.5% of visits into signups, and Direct's rate fell from 2.9% to 1.9% as its volume nearly doubled. This affects traffic efficiency, not the quality of the signups (finding 2).</li>
</ol>
<p class="note-foot" id="star">* {f0(net_new)} net new signups/month is an upper bound for what Free CRM added. In the same period traffic grew {traffic_growth:.0f}% QoQ (mostly Display and, in June, Direct) and the signup increase is spread across all channels. With this data we can't separate how much of the growth came from Free CRM vs traffic.</p>
<p class="note-foot" id="pro">† Pro's Q1 average is lifted by January (38.6%). Feb–Jun Pro ranges 26–32%, in line with Q2.</p>

<h2>Recommendations</h2>
<ol class="findings">
  <li><b>Use Free CRM to capture residual conversion, not as the default.</b> Make the Starter and Pro trials the main signup path again, and move trialists who don't buy to Free CRM when the trial ends (a reverse trial). Trials convert to paid at ~{pp[("Q2","Starter")][1]:.0f}% vs {free_cr:.1f}% for Free CRM, and ~{100-pp[("Q2","Starter")][1]:.0f}% of trialists don't buy today; Free CRM gives them a reason to stay instead of leaving. Validate it against today's setup on paying customers per visitor over 90 days, so Free CRM's slower upgrades are counted.</li>
  <li><b>Use in-product messaging to upsell Free CRM users to Starter in their first month.</b> Every Free CRM upgrade today happens within {fcrm_up[2]} days of signup, and all of them go to Starter. Connect upgrade prompts to the moments when users hit a Free CRM feature limit, so the message shows up when the value of Starter is most obvious.</li>
  <li><b>Add a product adoption layer alongside the purchase flow.</b> Track a few activation events for every signup, trial or free (for example: contacts imported, first deal created, a teammate invited). This tells us whether product adoption changed with the new packaging, why ~{100-free_cr:.0f}% of Free CRM users don't upgrade (they don't adopt, or they adopt but have no reason to pay), and later which trialists are worth moving to Free CRM.</li>
</ol>
<p><b>Sequencing.</b> Start 1 and 3 right away. Tracking adoption is critical for any free or freemium product, and nothing else depends on it to start. The reverse trial forces Free CRM to generate incremental value while we learn its long-term effect, and running it as a test limits the downside on paying customers. Recommendation 2 needs the adoption data from 3 to know when to trigger the upgrade message, so it follows once that data exists.</p>

<h2>Analysis</h2>

<h3>1. Signups grew while signup-to-paid conversion dropped</h3>
<p>Signups keep growing through the period. Signup-to-paid conversion is flat until Free CRM launches, then drops in a single step and stays at the new level.</p>
<figure>
  <figcaption><div class="t" id="c0t">Signups grew while conversion dropped in one step</div><div class="s">Weekly signup cohorts, complete weeks only (Jan 5 – Jun 28). Hover for values.</div></figcaption>
  {ch_weekly}
  {legend([("Signup → paid conversion (left axis)", "--s1"), ("Signups (right axis)", "--bar-neutral")])}
</figure>
<p>Same view by month, with sessions and deal value:</p>
{t_funnel}

<h3>2. Free CRM took two thirds of signups; signup-to-paid per SKU didn't move</h3>
<figure>
  <figcaption><div class="t" id="c1t">Signups per month by SKU</div><div class="s">The mix flips on Apr 1 and stays stable after.</div></figcaption>
  {ch_signups}
  {legend([(p, PC[p]) for p in PRODUCTS])}
</figure>
<figure>
  <figcaption><div class="t" id="c3t">Signup → paid conversion by SKU didn't move</div><div class="s">Starter and Pro hold at ~26–32%. The blended rate falls because Free CRM, at ~5%, is now most of the volume.</div></figcaption>
  {ch_conv}
  {legend([(p, PC[p]) for p in ["Starter", "Pro", "Free CRM"]] + [("Blended (all signups)", "--ink-total")])}
</figure>
<p>For paying customers to stay flat QoQ ({f0(w1)}/month), Free CRM would need a signup-to-paid conversion of ~{neutral_cr:.0f}%, vs {free_cr:.1f}% today.</p>
{t_prod}

<h3>3. How much of the drop each factor explains</h3>
<p>We split the change in monthly paying customers into three parts (Kitagawa decomposition): <b>volume</b> (more signups), <b>mix</b> (which SKU they sign up for) and <b>rate</b> (conversion inside each SKU). The three parts add up exactly to the total change.</p>
<figure>
  <figcaption><div class="t" id="c4t">From {f0(w1)} to {f0(w2)} paying customers per month</div><div class="s">Blue adds wins, red takes them away. Q1 vs Q2 monthly averages.</div></figcaption>
  {ch_water}
  {legend([("Increase", "--pos"), ("Decrease", "--neg"), ("Total", "--ink-total")])}
</figure>
<p class="note-foot">Assumption: Free CRM didn't exist in Q1, so it has no Q1 conversion rate. We use its Q2 rate for both periods, which puts its whole effect in mix. Query: <a href="https://github.com/northwind-acv/plg-conversion-panel/blob/main/sql/03_decomposition.sql">03_decomposition.sql</a>.</p>

<h3>4. The drop is the same for every type of signup</h3>
<figure>
  <figcaption><div class="t" id="c5t">Signup → paid conversion, Q1 vs Q2, by origin</div><div class="s">Every slice drops by a similar amount, close to the overall average. Hover for Free CRM share and sample size.</div></figcaption>
  {ch_dumb}
  {legend([("Q1 (Jan–Mar)", "--q1"), ("Q2 (Apr–Jun)", "--q2")])}
</figure>
<p>If traffic quality were the cause, we'd expect the drop to be concentrated in some channels and to build gradually as Display grew from February. Instead it hits every slice at once, in April. Free CRM also takes 65–74% of Q2 signups everywhere, including visitors who land on the Starter trial page (67%) and on pricing (68%).</p>
<p>The gaps between slices that existed in Q1 are still there in Q2: small companies convert better than large ones, Email and Social above average, tablet below. Those are structural differences between sources, and they didn't change with the launch. Monthly detail for every slice is in <a href="#appendix-b">Appendix B4</a>.</p>

<h3>5. Where the traffic growth came from</h3>
<p>Monthly averages, Q1 vs Q2. Display and Direct account for nearly all the new sessions. The other channels stayed flat in volume but turned more of their visits into signups.</p>
{t_traffic}
<p class="note-foot">Direct triples in June (26K sessions) while its session-to-signup rate drops to 1.3%; likely a tracking or bot issue worth checking at the source.</p>

<h2 id="appendix-a">Appendix A — Glossary</h2>
<ul class="gloss">
  <li><b>Session:</b> one visit to the Northwind website.</li>
  <li><b>Signup:</b> a lead registering for one SKU: Starter trial, Pro trial or Free CRM.</li>
  <li><b>SKU:</b> the product a lead signs up for (Starter trial, Pro trial or Free CRM). Not the plan they end up buying: Free CRM upgrades are bought as Starter.</li>
  <li><b>Win / paying customer:</b> a signup whose opportunity closed with an amount above $0 within 30 days of signing up. $0 deals (comps, coupons, internal) don't count.</li>
  <li><b>Signup → paid conversion:</b> wins divided by signups, for the same group of signups.</li>
  <li><b>Blended conversion:</b> signup → paid across all SKUs together.</li>
  <li><b>Cohort:</b> signups grouped by the week or month they signed up. A cohort's wins are counted whenever they close, up to 30 days later.</li>
  <li><b>Q1 / Q2:</b> Jan–Mar 2026 (before Free CRM) and Apr–Jun 2026 (after launch), compared as monthly averages.</li>
  <li><b>QoQ:</b> change from the Q1 monthly average to the Q2 monthly average.</li>
  <li><b>Mix shift:</b> a change in the share of signups going to each SKU.</li>
  <li><b>Deal value:</b> the opportunity amount: $35 for Starter, $110 for Pro.</li>
</ul>

<h2 id="appendix-b">Appendix B — Data behind the charts</h2>

<h4>B1. Weekly signups and signup → paid conversion (section 1)</h4>
<p class="note-foot">Complete Monday–Sunday weeks only. Free CRM launched Wednesday Apr 1, inside the week of Mar 30.</p>
{t_weekly}

<h4>B2. Signups and conversion by SKU, monthly (section 2)</h4>
{t_sku_month}

<h4>B3. Decomposition of the change in paying customers (section 3)</h4>
{t_kit}
<p class="note-foot">Free CRM has no Q1 rate; its Q2 rate is used for both periods, which puts its whole effect in mix.</p>

<h4>B4. Signup → paid conversion by origin slice, monthly (section 4)</h4>
<p class="note-foot">All signups, 30-day wins, in %. Slices with fewer than ~70 signups/month (Australia, Germany, Canada, tablet, trial and campaign landing pages) are noisy month to month; use Q1 vs Q2 for those.</p>
{slice_tables()}

<h2 id="appendix-c">Appendix C — Reconciliation with the finance view</h2>
<p>Finance counts customers by the month the deal closed; this analysis counts them by the month the customer signed up. The monthly numbers differ but tell the same story. January close-month counts are low because some January closes come from December signups, which aren't in the data.</p>
{t_fin}
<p class="note-foot">July closes come from June signups (the opportunity extract runs to Jul 26). Includes 15 opportunities whose lead_id doesn't match any signup.</p>

<h2 id="appendix-d">Appendix D — Queries</h2>
<p>Every number in this document comes from three SQL files in the <a href="https://github.com/northwind-acv/plg-conversion-panel">project repo</a>. How the data was validated and cleaned is in <a href="data-methodology.html">Data methodology</a>.</p>
<ul>
  <li><a href="https://github.com/northwind-acv/plg-conversion-panel/blob/main/sql/01_clean.sql">01_clean.sql</a>: cleaning rules and the analysis base table</li>
  <li><a href="https://github.com/northwind-acv/plg-conversion-panel/blob/main/sql/02_funnel.sql">02_funnel.sql</a>: weekly and monthly funnel, SKU split, slices, finance view</li>
  <li><a href="https://github.com/northwind-acv/plg-conversion-panel/blob/main/sql/03_decomposition.sql">03_decomposition.sql</a>: decomposition</li>
</ul>
</main>
<div id="tip" role="tooltip"></div>
<script>
const tip=document.getElementById('tip');
document.querySelectorAll('[data-tip]').forEach(el=>{{
  el.addEventListener('mousemove',e=>{{tip.textContent=el.dataset.tip;tip.style.opacity=1;
    const x=Math.min(e.clientX+12, innerWidth-tip.offsetWidth-8);tip.style.left=x+'px';tip.style.top=(e.clientY+14)+'px';}});
  el.addEventListener('mouseleave',()=>tip.style.opacity=0);
}});
</script>
</body>
</html>
"""
(ROOT / "docs" / "analysis.html").write_text(page)
print("wrote docs/analysis.html")
print(dict(w1=w1, w2=w2, n1=n1, n2=n2, cr1=cr1, cr2=cr2, mrr1=mrr1, mrr2=mrr2, free_n=free_n, free_cr=free_cr,
           be_wins=be_wins, be_mrr=be_mrr, lost_wins=lost_wins, lost_mrr=lost_mrr, net_new=net_new,
           substitution=substitution, traffic_growth=traffic_growth, fcrm_up=fcrm_up))
