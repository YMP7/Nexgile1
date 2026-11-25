"""Revenue-bridge analysis. Every number comes from a SQL query on the raw tables in
db/revenue.sqlite (the query text is returned as `evidence_query`). The API and
results/numbers.json both serve the single dict returned by compute().

Blind analysis: nothing here reads anything outside db/revenue.sqlite.
"""
import json
import math
import random
import sqlite3
import threading
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "db" / "revenue.sqlite"
OUT = ROOT / "results" / "numbers.json"

Q2 = ("2025-04-01", "2025-06-30")
Q3 = ("2025-07-01", "2025-09-30")
HIKE = "2025-08-01"  # EU price-increase date (given by the business)
Z = 1.96
BOOT = 300


def net_rev(a, b):
    return (f"SELECT SUM(amount) FROM payments WHERE status='succeeded' "
            f"AND payment_date BETWEEN '{a}' AND '{b}'")


SQL_REVENUE = f"""SELECT
 ({net_rev(*Q2)}) AS q2_gross,
 ({net_rev(*Q3)}) AS q3_gross,
 (SELECT COALESCE(SUM(payout_amount),0) FROM referrals WHERE referral_date BETWEEN '{Q2[0]}' AND '{Q2[1]}') AS q2_payouts,
 (SELECT COALESCE(SUM(payout_amount),0) FROM referrals WHERE referral_date BETWEEN '{Q3[0]}' AND '{Q3[1]}') AS q3_payouts,
 (SELECT COUNT(*) FROM workspaces WHERE signup_date BETWEEN '{Q2[0]}' AND '{Q2[1]}') AS q2_signups,
 (SELECT COUNT(*) FROM workspaces WHERE signup_date BETWEEN '{Q3[0]}' AND '{Q3[1]}') AS q3_signups"""

# in-quarter revenue of each signup cohort, by plan
SQL_MIX = f"""WITH c AS (
  SELECT workspace_id, plan,
         CASE WHEN signup_date BETWEEN '{Q2[0]}' AND '{Q2[1]}' THEN 'Q2' ELSE 'Q3' END q
  FROM workspaces WHERE signup_date BETWEEN '{Q2[0]}' AND '{Q3[1]}')
SELECT c.q, c.plan, COUNT(DISTINCT c.workspace_id) AS n,
       COALESCE(SUM(CASE WHEN p.status='succeeded' THEN p.amount END),0) AS rev
FROM c LEFT JOIN payments p ON p.workspace_id=c.workspace_id
  AND p.payment_date BETWEEN CASE c.q WHEN 'Q2' THEN '{Q2[0]}' ELSE '{Q3[0]}' END
                         AND CASE c.q WHEN 'Q2' THEN '{Q2[1]}' ELSE '{Q3[1]}' END
GROUP BY c.q, c.plan"""

# markets whose monthly price jumped >10% at the hike date
SQL_PRICE_MARKETS = f"""SELECT w.country FROM payments p JOIN workspaces w USING(workspace_id)
WHERE w.plan='monthly'
GROUP BY w.country
HAVING MAX(CASE WHEN p.payment_date>='{HIKE}' THEN p.amount END)
     > 1.1*MAX(CASE WHEN p.payment_date<'{HIKE}' THEN p.amount END)
ORDER BY 1"""


def sql_eu_ws(eu):
    return f"""SELECT CASE WHEN w.country IN ({eu}) THEN 1 ELSE 0 END AS eu,
 COALESCE(SUM(CASE WHEN p.status='succeeded' AND p.payment_date BETWEEN '{Q2[0]}' AND '{Q2[1]}' THEN p.amount END),0) AS r2,
 COALESCE(SUM(CASE WHEN p.status='succeeded' AND p.payment_date BETWEEN '{Q3[0]}' AND '{Q3[1]}' THEN p.amount END),0) AS r3
FROM workspaces w LEFT JOIN payments p USING(workspace_id)
GROUP BY w.workspace_id"""


def sql_eu_cancel(eu):
    return f"""SELECT CASE WHEN w.country IN ({eu}) THEN 'EU' ELSE 'non-EU' END AS grp,
 SUM(s.start_date<'2025-05-01' AND (s.cancel_date IS NULL OR s.cancel_date>='2025-05-01')) AS pre_active,
 SUM(s.start_date<'2025-05-01' AND s.cancel_date BETWEEN '2025-05-01' AND '2025-06-30') AS pre_cancel,
 SUM(s.start_date<'{HIKE}' AND (s.cancel_date IS NULL OR s.cancel_date>='{HIKE}')) AS post_active,
 SUM(s.start_date<'{HIKE}' AND s.cancel_date BETWEEN '{HIKE}' AND '{Q3[1]}') AS post_cancel
FROM subscriptions s JOIN workspaces w USING(workspace_id)
WHERE s.plan='monthly' GROUP BY grp"""


def sql_eu_tickets(eu):
    return f"""SELECT CASE WHEN w.country IN ({eu}) THEN 'EU' ELSE 'non-EU' END AS grp,
 COUNT(*) AS price_tickets
FROM support_tickets t JOIN workspaces w USING(workspace_id)
WHERE t.ticket_date >= '{HIKE}' AND lower(t.text) LIKE '%price%' GROUP BY grp"""


SQL_LAUNCH = "SELECT MIN(referral_date) AS launch FROM referrals"


def sql_ref_signups(launch):
    return f"""SELECT
 SUM(signup_date < '{launch}') AS pre_total,
 SUM(signup_date >= '{launch}') AS post_total,
 SUM(signup_date >= '{launch}' AND workspace_id IN (SELECT referred_workspace_id FROM referrals)) AS post_referred,
 SUM(signup_date >= '{launch}' AND workspace_id NOT IN (SELECT referred_workspace_id FROM referrals)) AS post_organic,
 CAST(julianday('{launch}')-julianday('{Q3[0]}') AS INT) AS pre_days,
 CAST(julianday('{Q3[1]}')-julianday('{launch}') AS INT)+1 AS post_days
FROM workspaces WHERE signup_date BETWEEN '{Q3[0]}' AND '{Q3[1]}'"""


def sql_ref_value(launch):
    return f"""SELECT CASE WHEN w.workspace_id IN (SELECT referred_workspace_id FROM referrals)
            THEN 'referred' ELSE 'organic' END AS src,
 COUNT(*) AS n, AVG(rev) AS avg_q3_rev
FROM workspaces w JOIN (
  SELECT w2.workspace_id, COALESCE(SUM(CASE WHEN p.status='succeeded' THEN p.amount END),0) AS rev
  FROM workspaces w2 LEFT JOIN payments p ON p.workspace_id=w2.workspace_id
       AND p.payment_date BETWEEN '{Q3[0]}' AND '{Q3[1]}'
  GROUP BY w2.workspace_id) r USING(workspace_id)
WHERE w.signup_date BETWEEN '{launch}' AND '{Q3[1]}' GROUP BY src"""


SQL_REF_PAYOUT = ("SELECT COUNT(*) AS referrals, COALESCE(SUM(payout_amount),0) AS payouts, "
                  "COUNT(DISTINCT partner_id) AS partners FROM referrals")

# 30-day retention = any event >= 30 days after signup
SQL_RET_CTE = """WITH r AS (
  SELECT w.workspace_id, w.signup_date,
         MAX(CASE WHEN julianday(substr(e.event_timestamp,1,10))-julianday(w.signup_date)>=30 THEN 1 ELSE 0 END) AS retained
  FROM workspaces w LEFT JOIN events e USING(workspace_id)
  WHERE w.signup_date BETWEEN '2025-04-01' AND '2025-09-30' GROUP BY w.workspace_id)"""
SQL_RET_COHORT = SQL_RET_CTE + f"""
SELECT CASE WHEN signup_date<='{Q2[1]}' THEN 'Q2' ELSE 'Q3' END AS cohort, COUNT(*) AS n, SUM(retained) AS retained
FROM r GROUP BY cohort"""
SQL_RET_ARM = SQL_RET_CTE + """
SELECT x.arm, COUNT(*) AS n, SUM(r.retained) AS retained
FROM experiment x JOIN r USING(workspace_id) GROUP BY x.arm"""
# does retention reach revenue? monthly-plan experiment workspaces still paying >=55 days after signup
SQL_ARM_PAYING = """SELECT x.arm, COUNT(*) AS n,
 SUM(EXISTS(SELECT 1 FROM payments p WHERE p.workspace_id=w.workspace_id AND p.status='succeeded'
            AND julianday(p.payment_date)-julianday(w.signup_date)>=55)) AS still_paying
FROM experiment x JOIN workspaces w USING(workspace_id)
WHERE w.plan='monthly' AND w.signup_date<='2025-07-31' GROUP BY x.arm"""


def rows(con, sql):
    cur = con.execute(sql)
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def r4(x):
    return round(x, 4)


def diff_props(x1, n1, x0, n0):
    p1, p0 = x1 / n1, x0 / n0
    se = math.sqrt(p1 * (1 - p1) / n1 + p0 * (1 - p0) / n0)
    d = p1 - p0
    return d, [d - Z * se, d + Z * se]


def did_pp(sample, denom):
    r2e = sum(r[1] for r in sample if r[0])
    r3e = sum(r[2] for r in sample if r[0])
    r2n = sum(r[1] for r in sample if not r[0])
    r3n = sum(r[2] for r in sample if not r[0])
    return (r3e - r2e * r3n / r2n) / denom * 100


def add_months(d, k):
    m = d.month - 1 + k
    return date(d.year + m // 12, m % 12 + 1, min(d.day, 28))


def eu_mechanism(run, eu, r2):
    """EU price effect = price uplift on post-hike EU payments minus revenue lost to EXCESS
    monthly cancellations and annual non-renewals (baseline: non-EU rates over the same window).
    Conditions on renewals actually due, unlike the revenue-ratio DiD. Range = count noise only."""
    old = {r["plan"]: r["p"] for r in run("eu_old_prices",
           f"SELECT w.plan, MAX(p.amount) AS p FROM payments p JOIN workspaces w USING(workspace_id) "
           f"WHERE p.payment_date < '{HIKE}' GROUP BY w.plan")}
    succ = run("eu_payment_success", f"""SELECT AVG(p.status='succeeded') AS success
FROM payments p JOIN workspaces w USING(workspace_id)
WHERE w.country IN ({eu}) AND p.payment_date BETWEEN '{HIKE}' AND '{Q3[1]}'""")[0]["success"]
    uplift = run("eu_uplift_succeeded", f"""SELECT SUM(p.amount - CASE w.plan WHEN 'monthly' THEN {old['monthly']} ELSE {old['annual']} END) AS u
FROM payments p JOIN workspaces w USING(workspace_id)
WHERE p.status='succeeded' AND w.country IN ({eu}) AND p.payment_date BETWEEN '{HIKE}' AND '{Q3[1]}'""")[0]["u"]
    mc = {c["grp"]: c for c in run("eu_cancellations", sql_eu_cancel(eu))}
    a1, c1, a0, c0 = (mc["EU"]["post_active"], mc["EU"]["post_cancel"],
                      mc["non-EU"]["post_active"], mc["non-EU"]["post_cancel"])
    p1, p0 = c1 / a1, c0 / a0
    rows_ = run("eu_cancelled_monthly_subs", f"""SELECT s.cancel_date, s.price FROM subscriptions s
JOIN workspaces w USING(workspace_id)
WHERE s.plan='monthly' AND w.country IN ({eu}) AND s.cancel_date BETWEEN '{HIKE}' AND '{Q3[1]}'""")
    end3 = date.fromisoformat(Q3[1])

    def forgone(r):  # payments that would have fallen in Q3 had the subscription not cancelled
        d0, k, n = date.fromisoformat(r["cancel_date"]), 0, 0
        while add_months(d0, k) <= end3:
            n, k = n + 1, k + 1
        return n * r["price"]

    per_cancel = sum(forgone(r) for r in rows_) / len(rows_)
    ex_m = c1 - a1 * p0
    se_m = math.sqrt(a1 * p1 * (1 - p1) + a1 ** 2 * p0 * (1 - p0) / a0)
    ann = {r["grp"]: r for r in run("eu_annual_renewals", f"""SELECT CASE WHEN w.country IN ({eu}) THEN 'EU' ELSE 'non-EU' END AS grp,
 SUM(kind='renewed') AS renewed, SUM(kind='not_renewed') AS not_renewed FROM (
  SELECT w.workspace_id, 'renewed' AS kind FROM payments p JOIN workspaces w USING(workspace_id)
   WHERE w.plan='annual' AND p.payment_date BETWEEN '{HIKE}' AND '{Q3[1]}' AND p.payment_date > w.signup_date
  UNION ALL
  SELECT w.workspace_id, 'not_renewed' FROM subscriptions s JOIN workspaces w USING(workspace_id)
   WHERE s.plan='annual' AND s.cancel_date BETWEEN '{HIKE}' AND '{Q3[1]}') x
 JOIN workspaces w USING(workspace_id) GROUP BY grp""")}
    d1, d0 = (ann[g]["renewed"] + ann[g]["not_renewed"] for g in ("EU", "non-EU"))
    n1, n0 = ann["EU"]["not_renewed"] / d1, ann["non-EU"]["not_renewed"] / d0
    ex_a = ann["EU"]["not_renewed"] - d1 * n0
    se_a = math.sqrt(d1 * n1 * (1 - n1) + d1 ** 2 * n0 * (1 - n0) / d0)
    hiked_annual = old["annual"] * 1.15
    loss_m, loss_a = ex_m * per_cancel * succ, ex_a * hiked_annual * succ
    pp = lambda x: x / r2 * 100
    net = pp(uplift - loss_m - loss_a)
    hw = Z * pp(math.sqrt((se_m * per_cancel * succ) ** 2 + (se_a * hiked_annual * succ) ** 2))
    return {"net_pp": net, "net_range_pp": [net - hw, net + hw], "price_uplift_pp": pp(uplift),
            "monthly_loss_pp": pp(loss_m), "annual_loss_pp": pp(loss_a),
            "monthly": {"active_at_hike": {"EU": a1, "non-EU": a0}, "cancelled": {"EU": c1, "non-EU": c0},
                        "excess_cancels": r4(ex_m), "forgone_q3_usd_per_cancel": r4(per_cancel)},
            "annual": {"renewals_due": {"EU": d1, "non-EU": d0},
                       "not_renewed": {"EU": ann["EU"]["not_renewed"], "non-EU": ann["non-EU"]["not_renewed"]},
                       "excess_non_renewals": r4(ex_a)},
            "payment_success_rate": r4(succ)}


CONFIDENCE_RULE = ("low: 95% range includes 0; high: range excludes 0 and its half-width is at most half "
                   "the estimate; medium: range excludes 0 but is wider")


def confidence(v, rng):
    if rng[0] <= 0 <= rng[1]:
        return "low"
    return "high" if (rng[1] - rng[0]) / 2 <= abs(v) * 0.5 else "medium"


def compute():
    con = sqlite3.connect(DB)
    q = {}  # name -> query text actually executed

    def run(name, sql):
        q[name] = sql
        return rows(con, sql)

    # ---- headline revenue (net = succeeded payments - referral payouts)
    rev = run("revenue", SQL_REVENUE)[0]
    r2 = rev["q2_gross"] - rev["q2_payouts"]
    r3 = rev["q3_gross"] - rev["q3_payouts"]
    total_pp = (r3 / r2 - 1) * 100

    # ---- 1. plan mix shift (Q3 volume held, Q2 plan mix restored)
    g = {(m["q"], m["plan"]): m for m in run("mix", SQL_MIX)}
    n2 = g[("Q2", "monthly")]["n"] + g[("Q2", "annual")]["n"]
    n3 = g[("Q3", "monthly")]["n"] + g[("Q3", "annual")]["n"]
    m2, m3 = g[("Q2", "monthly")]["n"] / n2, g[("Q3", "monthly")]["n"] / n3
    arpu = {p: g[("Q3", p)]["rev"] / g[("Q3", p)]["n"] for p in ("monthly", "annual")}
    per_share = n3 * (arpu["monthly"] - arpu["annual"]) / r2 * 100  # pp per unit of monthly-share shift
    mix_pp = (m3 - m2) * per_share
    se_share = math.sqrt(m3 * (1 - m3) / n3 + m2 * (1 - m2) / n2)
    mix_rng = sorted([mix_pp - Z * se_share * abs(per_share), mix_pp + Z * se_share * abs(per_share)])

    # ---- 2. EU price increase: difference-in-differences vs markets with no price change
    eu_list = [c["country"] for c in run("price_markets", SQL_PRICE_MARKETS)]
    eu = ",".join(f"'{c}'" for c in eu_list)
    ws = [(r["eu"], r["r2"], r["r3"]) for r in run("eu_per_workspace", sql_eu_ws(eu))]
    did_val = did_pp(ws, r2)  # cross-check only: biased when annual renewals due differ by group
    rng = random.Random(7)
    boots = sorted(did_pp(rng.choices(ws, k=len(ws)), r2) for _ in range(BOOT))
    did_rng = [boots[int(.025 * BOOT)], boots[int(.975 * BOOT) - 1]]
    mech = eu_mechanism(run, eu, r2)
    eu_pp, eu_rng = mech["net_pp"], mech["net_range_pp"]
    canc = {c["grp"]: c for c in run("eu_cancellations", sql_eu_cancel(eu))}
    eu_cancel = {grp: {"pre_rate": r4(c["pre_cancel"] / c["pre_active"]),
                       "post_rate": r4(c["post_cancel"] / c["post_active"])} for grp, c in canc.items()}
    eu_tickets = {t["grp"]: t["price_tickets"] for t in run("eu_price_tickets", sql_eu_tickets(eu))}

    # ---- 3. referral programme: incremental signups vs payouts
    launch = run("referral_launch", SQL_LAUNCH)[0]["launch"]
    s = run("referral_signups", sql_ref_signups(launch))[0]
    val = {v["src"]: v for v in run("referral_value", sql_ref_value(launch))}
    pay = run("referral_payouts", SQL_REF_PAYOUT)[0]
    expected = s["pre_total"] / s["pre_days"] * s["post_days"]
    se_inc = math.sqrt(s["post_total"] + expected ** 2 / s["pre_total"])
    clip = lambda v: min(max(v, 0.0), s["post_referred"])
    inc = [clip(s["post_total"] - expected + k * se_inc) for k in (0, -Z, Z)]
    avg_rev = (s["post_referred"] * val["referred"]["avg_q3_rev"]
               + s["post_organic"] * val["organic"]["avg_q3_rev"]) / s["post_total"]
    ref_all = [(i * avg_rev - rev["q3_payouts"]) / r2 * 100 for i in inc]
    ref_pp, ref_rng = ref_all[0], [ref_all[1], ref_all[2]]

    # ---- bridge
    resid = total_pp - mix_pp - eu_pp - ref_pp
    half = lambda r: (r[1] - r[0]) / 2
    hw = math.sqrt(half(mix_rng) ** 2 + half(eu_rng) ** 2 + half(ref_rng) ** 2)
    bridge = [
        {"cause": "Plan mix shift (more monthly signups)", "pct_points": r4(mix_pp), "range": [r4(x) for x in mix_rng],
         "evidence_query": q["mix"]},
        {"cause": "EU price increase (net of extra cancellations)", "pct_points": r4(eu_pp), "range": [r4(x) for x in eu_rng],
         "evidence_query": ";\n".join(q[k] for k in ("eu_uplift_succeeded", "eu_cancellations", "eu_annual_renewals"))},
        {"cause": "Referral programme (cannibalisation net of payouts)", "pct_points": r4(ref_pp),
         "range": [r4(x) for x in ref_rng], "evidence_query": q["referral_signups"]},
        {"cause": "Unexplained", "pct_points": r4(resid), "range": [r4(resid - hw), r4(resid + hw)],
         "evidence_query": q["revenue"]},
    ]
    assert abs(sum(b["pct_points"] for b in bridge) - total_pp) < 4e-4, "bridge must sum to total"

    # ---- onboarding initiative
    coh = {c["cohort"]: c for c in run("retention_cohort", SQL_RET_COHORT)}
    arm = {a["arm"]: a for a in run("retention_arm", SQL_RET_ARM)}
    ret_d, ret_rng = diff_props(arm["treatment"]["retained"], arm["treatment"]["n"],
                                arm["control"]["retained"], arm["control"]["n"])
    pa = {a["arm"]: a for a in run("arm_paying", SQL_ARM_PAYING)}
    pay_d, pay_rng = diff_props(pa["treatment"]["still_paying"], pa["treatment"]["n"],
                                pa["control"]["still_paying"], pa["control"]["n"])
    ret_q = {k: r4(c["retained"] / c["n"]) for k, c in coh.items()}
    onboarding = {
        "name": "onboarding",
        "effect": {"metric": "30-day retention, treatment minus control (pp)", "value": r4(ret_d * 100),
                   "range": [r4(x * 100) for x in ret_rng]},
        "evidence": {
            "retention_by_arm": {a: r4(v["retained"] / v["n"]) for a, v in arm.items()},
            "arm_sizes": {a: v["n"] for a, v in arm.items()},
            "cohort_retention": ret_q,
            "revenue_link": {"metric": "monthly-plan workspaces still paying >=55 days after signup, treatment minus control (pp)",
                             "value": r4(pay_d * 100), "range": [r4(x * 100) for x in pay_rng]},
            "caveat": "Randomised in two countries only; Q3 cohort retention also reflects rollout to all other signups.",
        },
        "evidence_query": q["retention_arm"],
        "recommendation": "keep" if ret_rng[0] > 0 else ("stop" if ret_rng[1] < 0 else "change"),
    }

    europe = {
        "name": "europe_price",
        "effect": {"metric": "price uplift minus excess cancellations and non-renewals (pp of Q2 revenue)", "value": r4(eu_pp),
                   "range": [r4(x) for x in eu_rng]},
        "evidence": {
            "price_increase_markets": eu_list,
            "monthly_cancel_rate_pre_vs_post_hike": eu_cancel,
            "price_complaint_tickets_since_hike": eu_tickets,
            "mechanism": {k: (r4(v) if isinstance(v, float) else v) for k, v in mech.items()
                          if k not in ("net_pp", "net_range_pp")},
            "cross_check_revenue_ratio_did": {"pp": r4(did_val), "range": [r4(x) for x in did_rng],
                                              "caveat": "EU had 12% fewer annual renewals fall due; this inflates the DiD (see verification)"},
        },
        "evidence_query": q["eu_uplift_succeeded"],
        "recommendation": "keep" if eu_pp >= 0 else "change",
    }

    referral = {
        "name": "referral",
        "effect": {"metric": "net revenue after payouts (pp of Q2 revenue)", "value": r4(ref_pp),
                   "range": [r4(x) for x in ref_rng]},
        "evidence": {
            "launch_date": launch, "referrals": pay["referrals"], "partners": pay["partners"],
            "payouts": pay["payouts"],
            "signups_per_day_before_launch": r4(s["pre_total"] / s["pre_days"]),
            "signups_per_day_after_launch": r4(s["post_total"] / s["post_days"]),
            "organic_signups_per_day_after_launch": r4(s["post_organic"] / s["post_days"]),
            "estimated_incremental_signups": {"value": r4(inc[0]), "range": [r4(inc[1]), r4(inc[2])]},
            "estimated_cannibalised_share": r4(1 - inc[0] / s["post_referred"]),
            "avg_q3_revenue_per_signup": {k: r4(v["avg_q3_rev"]) for k, v in val.items()},
        },
        "evidence_query": q["referral_signups"],
        "recommendation": "stop" if ref_rng[1] < 0 else ("change" if ref_pp < 0 else "keep"),
    }

    for i in (onboarding, europe, referral):
        i["confidence"] = confidence(i["effect"]["value"], i["effect"]["range"])
        i["confidence_rule"] = CONFIDENCE_RULE
    sig = (rev["q3_signups"] / rev["q2_signups"] - 1) * 100
    pr = lambda b: f"{b['cause'].split(' (')[0]} {b['pct_points']:+.1f}pp (range {b['range'][0]:+.1f} to {b['range'][1]:+.1f})"
    para = [
        f"Net revenue (succeeded payments minus referral payouts) fell {abs(total_pp):.1f}% from ${r2:,.0f} in Q2 to "
        f"${r3:,.0f} in Q3, even though signups rose {sig:.0f}% and 30-day retention rose from {ret_q['Q2']:.0%} to "
        f"{ret_q['Q3']:.0%}.",
        "Where the revenue went, in percentage points of Q2 revenue: " + "; ".join(pr(b) for b in bridge) + ".",
        f"Onboarding: {onboarding['recommendation']} ({onboarding['confidence']} confidence) - 30-day retention is "
        f"{onboarding['effect']['value']:+.1f}pp higher in treatment, but no revenue effect is shown yet. "
        f"Europe price: {europe['recommendation']} ({europe['confidence']} confidence) - the increase costs "
        f"{abs(eu_pp):.1f}pp net of extra cancellations. "
        f"Referral programme: {referral['recommendation']} ({referral['confidence']} confidence) - about "
        f"{referral['evidence']['estimated_cannibalised_share']:.0%} of referrals look cannibalised, and in-quarter revenue "
        "does not cover the payouts (later payments are not counted).",
        f"Caveats: small samples ({n2} and {n3} signups, {pay['referrals']} referrals); ranges are 95% and reflect count "
        "noise only; the data is synthetic.",
    ]
    memo = (chr(10) * 2).join(para)
    summary = {
        "q2_net_revenue": r4(r2), "q3_net_revenue": r4(r3), "revenue_change_pct": r4(total_pp),
        "signups": {"q2": rev["q2_signups"], "q3": rev["q3_signups"],
                    "change_pct": r4((rev["q3_signups"] / rev["q2_signups"] - 1) * 100)},
        "monthly_plan_share_of_signups": {"q2": r4(m2), "q3": r4(m3)},
        "retention_30d": ret_q,
        "bridge": [{k: b[k] for k in ("cause", "pct_points", "range")} for b in bridge],
        "recommendations": {i["name"]: i["recommendation"] for i in (onboarding, europe, referral)},
        "memo": memo,
    }
    con.close()
    return {"summary": summary, "bridge": bridge,
            "initiatives": {i["name"]: i for i in (onboarding, europe, referral)}}


_cache = {"mtime": None, "data": None}
_lock = threading.Lock()  # concurrent first requests must not each recompute and rewrite numbers.json


def get_numbers():
    """Recompute when the DB changes; always rewrite results/numbers.json from the same dict."""
    with _lock:
        mt = DB.stat().st_mtime
        if _cache["mtime"] != mt:
            _cache.update(mtime=mt, data=compute())
            OUT.parent.mkdir(exist_ok=True)
            OUT.write_text(json.dumps(_cache["data"], indent=2))
        return _cache["data"]


if __name__ == "__main__":
    get_numbers()
    print(f"wrote {OUT}")
