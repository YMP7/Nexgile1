"""Independent re-derivations of the revenue bridge + raw-row exports.
Run: python -m backend.verify   (writes results/raw/*.csv and results/verification.json)
Reads only db/revenue.sqlite. Every estimate here is derived a different way from
backend/analysis.py; discrepancies are reported, never averaged.
"""
import csv
import json
import math
import sqlite3
from datetime import date

from . import analysis as A

Z = A.Z
RAW = A.ROOT / "results" / "raw"
RAW.mkdir(parents=True, exist_ok=True)
con = sqlite3.connect(A.DB)
Q2, Q3, HIKE = A.Q2, A.Q3, A.HIKE
out = {}


def q(sql):
    cur = con.execute(sql)
    return [dict(zip([c[0] for c in cur.description], r)) for r in cur.fetchall()]


def dump(name, sql):
    rs = q(sql)
    with open(RAW / f"{name}.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rs[0]))
        w.writeheader()
        w.writerows(rs)
    return rs


def add_months(d, k):
    m = d.month - 1 + k
    return date(d.year + m // 12, m % 12 + 1, min(d.day, 28))


# ---------------------------------------------------------------- 0. definitions (H4)
st = {(r["qtr"], r["status"]): r for r in q(f"""
 SELECT CASE WHEN payment_date BETWEEN '{Q2[0]}' AND '{Q2[1]}' THEN 'Q2' ELSE 'Q3' END qtr, status,
        SUM(amount) amt, COUNT(*) n FROM payments
 WHERE payment_date BETWEEN '{Q2[0]}' AND '{Q3[1]}' GROUP BY 1,2""")}
pay = {r["qtr"]: r["p"] for r in q(f"""
 SELECT CASE WHEN referral_date BETWEEN '{Q2[0]}' AND '{Q2[1]}' THEN 'Q2' ELSE 'Q3' END qtr, SUM(payout_amount) p
 FROM referrals GROUP BY 1""")}
pay.setdefault("Q2", 0.0)
edge = {r["d"]: r["amt"] for r in q(
    "SELECT payment_date d, SUM(amount) amt FROM payments WHERE status='succeeded' "
    "AND payment_date IN ('2025-06-30','2025-09-30') GROUP BY 1")}
S = lambda qt, s: st[(qt, s)]["amt"]
defs = {
    "A used: succeeded - payouts": (S("Q2", "succeeded") - pay["Q2"], S("Q3", "succeeded") - pay["Q3"]),
    "B succeeded only (ignore payouts)": (S("Q2", "succeeded"), S("Q3", "succeeded")),
    "C succeeded+refunded - payouts": (S("Q2", "succeeded") + S("Q2", "refunded") - pay["Q2"],
                                       S("Q3", "succeeded") + S("Q3", "refunded") - pay["Q3"]),
    "D every attempted charge - payouts": (sum(S("Q2", s) for s in ("succeeded", "refunded", "failed")) - pay["Q2"],
                                           sum(S("Q3", s) for s in ("succeeded", "refunded", "failed")) - pay["Q3"]),
    "E A but last day of each quarter dropped": (S("Q2", "succeeded") - edge.get("2025-06-30", 0) - pay["Q2"],
                                                 S("Q3", "succeeded") - edge.get("2025-09-30", 0) - pay["Q3"]),
}
out["definitions"] = {k: {"q2": round(a, 2), "q3": round(b, 2), "change_pct": round((b / a - 1) * 100, 3)}
                      for k, (a, b) in defs.items()}
R2, R3 = defs["A used: succeeded - payouts"]
total_pp = (R3 / R2 - 1) * 100
# reconcile to the cent: re-add the exported raw payment rows in Python
rawp = dump("payments_q2_q3", f"""SELECT p.workspace_id, w.country, w.plan, w.signup_date, p.payment_date, p.amount, p.status
 FROM payments p JOIN workspaces w USING(workspace_id)
 WHERE p.payment_date BETWEEN '{Q2[0]}' AND '{Q3[1]}' ORDER BY p.payment_date, p.workspace_id""")
py_q2 = round(sum(r["amount"] for r in rawp if r["status"] == "succeeded" and r["payment_date"] <= Q2[1]), 2)
py_q3 = round(sum(r["amount"] for r in rawp if r["status"] == "succeeded" and r["payment_date"] >= Q3[0]), 2)
out["reconcile_cent"] = {"python_sum_q2": py_q2, "sql_q2": round(S("Q2", "succeeded"), 2),
                         "python_sum_q3": py_q3, "sql_q3": round(S("Q3", "succeeded"), 2),
                         "raw_rows": len(rawp)}

# ---------------------------------------------------------------- 1. EU price effect
eu_list = [r["country"] for r in q(A.SQL_PRICE_MARKETS)]
eu = ",".join(f"'{c}'" for c in eu_list)
ws = dump("eu_per_workspace", f"""SELECT w.workspace_id, w.country, w.plan, w.signup_date,
 CASE WHEN w.country IN ({eu}) THEN 1 ELSE 0 END eu,
 COALESCE(SUM(CASE WHEN p.status='succeeded' AND p.payment_date BETWEEN '{Q2[0]}' AND '{Q2[1]}' THEN p.amount END),0) r2,
 COALESCE(SUM(CASE WHEN p.status='succeeded' AND p.payment_date BETWEEN '{Q3[0]}' AND '{Q3[1]}' THEN p.amount END),0) r3
 FROM workspaces w LEFT JOIN payments p USING(workspace_id) GROUP BY w.workspace_id""")
grp = lambda r: "EU" if r["eu"] else "non-EU"
agg = {g: {"n": 0, "n_paying_q2": 0, "n_paying_q3": 0, "r2": 0.0, "r3": 0.0} for g in ("EU", "non-EU")}
for r in ws:
    a = agg[grp(r)]
    a["n"] += 1
    a["r2"] += r["r2"]
    a["r3"] += r["r3"]
    a["n_paying_q2"] += r["r2"] > 0
    a["n_paying_q3"] += r["r3"] > 0
out["eu_did_inputs"] = {g: {k: round(v, 2) for k, v in a.items()} for g, a in agg.items()}
did = (agg["EU"]["r3"] - agg["EU"]["r2"] * agg["non-EU"]["r3"] / agg["non-EU"]["r2"]) / R2 * 100
out["eu_did_pp"] = round(did, 3)
out["eu_growth_ratio"] = {g: round(a["r3"] / a["r2"], 4) for g, a in agg.items()}

# structural: price uplift minus revenue lost to excess cancellations / non-renewals
old = {r["plan"]: r["p"] for r in q(
    f"SELECT w.plan, MAX(p.amount) p FROM payments p JOIN workspaces w USING(workspace_id) "
    f"WHERE p.payment_date < '{HIKE}' GROUP BY w.plan")}
uplift = q(f"""SELECT SUM(p.amount - CASE w.plan WHEN 'monthly' THEN {old['monthly']} ELSE {old['annual']} END) u, COUNT(*) n
 FROM payments p JOIN workspaces w USING(workspace_id)
 WHERE p.status='succeeded' AND w.country IN ({eu}) AND p.payment_date BETWEEN '{HIKE}' AND '{Q3[1]}'""")[0]
succ_rate = q(f"""SELECT AVG(p.status='succeeded') s FROM payments p JOIN workspaces w USING(workspace_id)
 WHERE w.country IN ({eu}) AND p.payment_date BETWEEN '{HIKE}' AND '{Q3[1]}'""")[0]["s"]

# monthly plans
mc = {r["grp"]: r for r in q(A.sql_eu_cancel(eu))}
a_eu, c_eu = mc["EU"]["post_active"], mc["EU"]["post_cancel"]
a_n, c_n = mc["non-EU"]["post_active"], mc["non-EU"]["post_cancel"]
p_eu, p_n = c_eu / a_eu, c_n / a_n
pre_eu = mc["EU"]["pre_cancel"] / mc["EU"]["pre_active"]
canc_rows = dump("eu_monthly_cancellations_post_hike", f"""SELECT s.workspace_id, w.country, s.start_date, s.cancel_date, s.price
 FROM subscriptions s JOIN workspaces w USING(workspace_id)
 WHERE s.plan='monthly' AND w.country IN ({eu}) AND s.cancel_date BETWEEN '{HIKE}' AND '{Q3[1]}' ORDER BY s.cancel_date""")
end3 = date.fromisoformat(Q3[1])


def forgone(r):  # payments that would have fallen in Q3 had the sub not cancelled
    d0, k, n = date.fromisoformat(r["cancel_date"]), 0, 0
    while add_months(d0, k) <= end3:
        n, k = n + 1, k + 1
    return n * r["price"]


per_cancel = sum(forgone(r) for r in canc_rows) / len(canc_rows)


def monthly_loss(p0):
    ex = c_eu - a_eu * p0
    var = a_eu * p_eu * (1 - p_eu) + a_eu ** 2 * p0 * (1 - p0) / a_n
    return ex, math.sqrt(var), ex * per_cancel * succ_rate


ex_m, se_m, loss_m = monthly_loss(p_n)           # baseline = non-EU post-hike rate
ex_m2, _, loss_m2 = monthly_loss(pre_eu)          # baseline = EU's own pre-hike rate

# annual plans
ann = {r["grp"]: r for r in q(f"""SELECT CASE WHEN w.country IN ({eu}) THEN 'EU' ELSE 'non-EU' END grp,
 SUM(kind='renewed') renewed, SUM(kind='not_renewed') not_renewed FROM (
  SELECT w.workspace_id, 'renewed' kind FROM payments p JOIN workspaces w USING(workspace_id)
   WHERE w.plan='annual' AND p.payment_date BETWEEN '{HIKE}' AND '{Q3[1]}' AND p.payment_date > w.signup_date
  UNION ALL
  SELECT w.workspace_id, 'not_renewed' FROM subscriptions s JOIN workspaces w USING(workspace_id)
   WHERE s.plan='annual' AND s.cancel_date BETWEEN '{HIKE}' AND '{Q3[1]}') x
 JOIN workspaces w USING(workspace_id) GROUP BY grp""")}
due = lambda g: ann[g]["renewed"] + ann[g]["not_renewed"]
nr_eu, nr_n = ann["EU"]["not_renewed"] / due("EU"), ann["non-EU"]["not_renewed"] / due("non-EU")
ex_a = ann["EU"]["not_renewed"] - due("EU") * nr_n
se_a = math.sqrt(due("EU") * nr_eu * (1 - nr_eu) + due("EU") ** 2 * nr_n * (1 - nr_n) / due("non-EU"))
annual_hiked = old["annual"] * 1.15
loss_a = ex_a * annual_hiked * succ_rate
net_struct = uplift["u"] - loss_m - loss_a
se_pp = math.sqrt((se_m * per_cancel * succ_rate) ** 2 + (se_a * annual_hiked * succ_rate) ** 2) / R2 * 100
pp = lambda x: round(x / R2 * 100, 3)
out["eu_structural"] = {
    "price_uplift_usd": round(uplift["u"], 2), "price_uplift_pp": pp(uplift["u"]), "eu_payments_post_hike": uplift["n"],
    "monthly": {"active_at_hike_EU": a_eu, "cancel_EU": c_eu, "rate_EU": round(p_eu, 4),
                "active_at_hike_nonEU": a_n, "cancel_nonEU": c_n, "rate_nonEU": round(p_n, 4),
                "eu_pre_hike_rate": round(pre_eu, 4), "excess_cancels_vs_nonEU": round(ex_m, 1),
                "excess_se": round(se_m, 1), "forgone_q3_usd_per_cancel": round(per_cancel, 2),
                "loss_usd": round(loss_m, 2), "loss_pp": pp(loss_m),
                "loss_pp_if_baseline_is_EU_pre_rate": pp(loss_m2)},
    "annual": {"due_EU": due("EU"), "not_renewed_EU": ann["EU"]["not_renewed"], "due_nonEU": due("non-EU"),
               "not_renewed_nonEU": ann["non-EU"]["not_renewed"], "rate_EU": round(nr_eu, 4),
               "rate_nonEU": round(nr_n, 4), "excess_non_renewals": round(ex_a, 1), "excess_se": round(se_a, 1),
               "loss_usd": round(loss_a, 2), "loss_pp": pp(loss_a)},
    "net_pp": pp(net_struct), "net_range_pp": [round(pp(net_struct) - Z * se_pp, 3), round(pp(net_struct) + Z * se_pp, 3)],
    "success_rate_assumed": round(succ_rate, 4),
}
# the API's EU number is the same mechanism computed by backend/analysis.py: they must agree
_api = A.get_numbers()["bridge"][1]["pct_points"]
assert abs(_api - out["eu_structural"]["net_pp"]) < 0.002, (_api, out["eu_structural"]["net_pp"])
# third derivation: DiD by plan, with annual revenue scaled by relative renewal exposure
def renewals_due(a, b):
    return {r["g"]: r["due"] for r in q(f"""SELECT g, SUM(c) due FROM (
      SELECT CASE WHEN w.country IN ({eu}) THEN 'EU' ELSE 'non-EU' END g, COUNT(*) c
        FROM payments p JOIN workspaces w USING(workspace_id)
        WHERE w.plan='annual' AND p.payment_date BETWEEN '{a}' AND '{b}' AND p.payment_date > w.signup_date GROUP BY g
      UNION ALL
      SELECT CASE WHEN w.country IN ({eu}) THEN 'EU' ELSE 'non-EU' END, COUNT(*)
        FROM subscriptions s JOIN workspaces w USING(workspace_id)
        WHERE s.plan='annual' AND s.cancel_date BETWEEN '{a}' AND '{b}' GROUP BY 1) GROUP BY g""")}


d2, d3 = renewals_due(*Q2), renewals_due(*Q3)
rp = {(r["grp"], r["plan"]): r for r in q(f"""SELECT CASE WHEN w.country IN ({eu}) THEN 'EU' ELSE 'non-EU' END grp, w.plan,
 SUM(CASE WHEN p.payment_date BETWEEN '{Q2[0]}' AND '{Q2[1]}' THEN p.amount ELSE 0 END) q2,
 SUM(CASE WHEN p.payment_date BETWEEN '{Q3[0]}' AND '{Q3[1]}' THEN p.amount ELSE 0 END) q3
 FROM payments p JOIN workspaces w USING(workspace_id) WHERE p.status='succeeded' GROUP BY 1,2""")}
g = lambda grp, plan: rp[(grp, plan)]["q3"] / rp[(grp, plan)]["q2"]
did_m = (rp[("EU", "monthly")]["q3"] - rp[("EU", "monthly")]["q2"] * g("non-EU", "monthly")) / R2 * 100
did_a = (rp[("EU", "annual")]["q3"] - rp[("EU", "annual")]["q2"] * g("non-EU", "annual")) / R2 * 100
exposure = (d3["EU"] / d2["EU"]) / (d3["non-EU"] / d2["non-EU"])
did_a_adj = (rp[("EU", "annual")]["q3"] - rp[("EU", "annual")]["q2"] * g("non-EU", "annual") * exposure) / R2 * 100
out["eu_exposure_adjusted"] = {
    "renewals_due": {"Q2": d2, "Q3": d3}, "relative_exposure_EU_vs_nonEU": round(exposure, 4),
    "did_monthly_pp": round(did_m, 3), "did_annual_pp_naive": round(did_a, 3),
    "did_annual_pp_exposure_adjusted": round(did_a_adj, 3),
    "total_naive_pp": round(did_m + did_a, 3), "total_exposure_adjusted_pp": round(did_m + did_a_adj, 3),
}
# raw rows: EU workspaces with the biggest Q2->Q3 drops
dump("eu_biggest_swings", f"SELECT * FROM (SELECT w.workspace_id, w.country, w.plan, w.signup_date, "
     f"SUM(CASE WHEN p.status='succeeded' AND p.payment_date BETWEEN '{Q2[0]}' AND '{Q2[1]}' THEN p.amount ELSE 0 END) r2, "
     f"SUM(CASE WHEN p.status='succeeded' AND p.payment_date BETWEEN '{Q3[0]}' AND '{Q3[1]}' THEN p.amount ELSE 0 END) r3 "
     f"FROM workspaces w LEFT JOIN payments p USING(workspace_id) WHERE w.country IN ({eu}) GROUP BY w.workspace_id) "
     f"ORDER BY r3-r2 LIMIT 25")
out["eu_revenue_by_plan"] = q(f"""SELECT CASE WHEN w.country IN ({eu}) THEN 'EU' ELSE 'non-EU' END grp, w.plan,
 SUM(CASE WHEN p.payment_date BETWEEN '{Q2[0]}' AND '{Q2[1]}' THEN p.amount ELSE 0 END) q2,
 SUM(CASE WHEN p.payment_date BETWEEN '{Q3[0]}' AND '{Q3[1]}' THEN p.amount ELSE 0 END) q3
 FROM payments p JOIN workspaces w USING(workspace_id) WHERE p.status='succeeded' GROUP BY 1,2""")

# ---------------------------------------------------------------- 2. mix, three-way
coh = dump("signup_cohorts_q2_q3", f"""SELECT w.workspace_id, w.country, w.plan, w.signup_date,
 CASE WHEN w.signup_date <= '{Q2[1]}' THEN 'Q2' ELSE 'Q3' END cohort,
 COALESCE(SUM(CASE WHEN p.status='succeeded' AND p.payment_date BETWEEN
   CASE WHEN w.signup_date <= '{Q2[1]}' THEN '{Q2[0]}' ELSE '{Q3[0]}' END AND
   CASE WHEN w.signup_date <= '{Q2[1]}' THEN '{Q2[1]}' ELSE '{Q3[1]}' END THEN p.amount END),0) in_qtr_rev
 FROM workspaces w LEFT JOIN payments p USING(workspace_id)
 WHERE w.signup_date BETWEEN '{Q2[0]}' AND '{Q3[1]}' GROUP BY w.workspace_id""")
cs = {}
for r in coh:
    c = cs.setdefault((r["cohort"], r["plan"]), {"n": 0, "rev": 0.0})
    c["n"] += 1
    c["rev"] += r["in_qtr_rev"]
n = {k: cs[(k, "monthly")]["n"] + cs[(k, "annual")]["n"] for k in ("Q2", "Q3")}
sh = {k: {p: cs[(k, p)]["n"] / n[k] for p in ("monthly", "annual")} for k in n}
ar = {k: {p: cs[(k, p)]["rev"] / cs[(k, p)]["n"] for p in ("monthly", "annual")} for k in n}
dsh = sh["Q3"]["monthly"] - sh["Q2"]["monthly"]
mix_q3w = n["Q3"] * dsh * (ar["Q3"]["monthly"] - ar["Q3"]["annual"]) / R2 * 100
mix_q2w = n["Q3"] * dsh * (ar["Q2"]["monthly"] - ar["Q2"]["annual"]) / R2 * 100
vol = (n["Q3"] - n["Q2"]) * sum(sh["Q2"][p] * ar["Q2"][p] for p in sh["Q2"]) / R2 * 100
rate = n["Q3"] * sum(sh["Q3"][p] * (ar["Q3"][p] - ar["Q2"][p]) for p in sh["Q3"]) / R2 * 100
se_sh = math.sqrt(sh["Q3"]["monthly"] * (1 - sh["Q3"]["monthly"]) / n["Q3"] + sh["Q2"]["monthly"] * (1 - sh["Q2"]["monthly"]) / n["Q2"])
newc = lambda k: sum(cs[(k, p)]["rev"] for p in ("monthly", "annual"))
out["mix"] = {
    "n": n, "monthly_share": {k: round(sh[k]["monthly"], 4) for k in sh}, "share_shift_se": round(se_sh, 4),
    "arpu_in_quarter": {k: {p: round(v, 2) for p, v in ar[k].items()} for k in ar},
    "mix_pp_Q3_arpu_weights": round(mix_q3w, 3), "mix_pp_Q2_arpu_weights": round(mix_q2w, 3),
    "three_way_new_cohort_delta_pp": {"volume": round(vol, 3), "mix": round(mix_q2w, 3), "arpu_rate": round(rate, 3),
                                      "interaction_and_rounding": round((newc("Q3") - newc("Q2")) / R2 * 100 - vol - mix_q2w - rate, 3),
                                      "total": round((newc("Q3") - newc("Q2")) / R2 * 100, 3)},
    "mix_range_pp": [round(mix_q3w - Z * se_sh * abs(mix_q3w / dsh), 3), round(mix_q3w + Z * se_sh * abs(mix_q3w / dsh), 3)],
}

# ---------------------------------------------------------------- 3. referral
launch = q(A.SQL_LAUNCH)[0]["launch"]
dump("referrals_with_value", f"""SELECT r.referral_id, r.partner_id, r.referred_workspace_id, r.referral_date, r.payout_amount,
 w.country, w.plan, COALESCE((SELECT SUM(p.amount) FROM payments p WHERE p.workspace_id=w.workspace_id
   AND p.status='succeeded' AND p.payment_date BETWEEN '{Q3[0]}' AND '{Q3[1]}'),0) q3_rev
 FROM referrals r JOIN workspaces w ON w.workspace_id=r.referred_workspace_id ORDER BY r.referral_date""")
daily = dump("daily_signups_q2_q3", f"""SELECT signup_date d, COUNT(*) total,
 SUM(workspace_id IN (SELECT referred_workspace_id FROM referrals)) referred
 FROM workspaces WHERE signup_date BETWEEN '{Q2[0]}' AND '{Q3[1]}' GROUP BY 1 ORDER BY 1""")
month = {}
for r in daily:
    month[r["d"][:7]] = month.get(r["d"][:7], 0) + r["total"]
days = {"2025-04": 30, "2025-05": 31, "2025-06": 30, "2025-07": 31, "2025-08": 31, "2025-09": 30}
placebo = {}
for m, others in (("2025-04", ("2025-05", "2025-06")), ("2025-05", ("2025-04", "2025-06")), ("2025-06", ("2025-04", "2025-05")),
                  ("2025-07", ("2025-08", "2025-09")), ("2025-08", ("2025-07", "2025-09")), ("2025-09", ("2025-07", "2025-08"))):
    base = sum(month[o] for o in others) / sum(days[o] for o in others)
    placebo[m] = {"count": month[m], "expected_from_other_months_in_quarter": round(base * days[m], 1),
                  "deviation": round(month[m] - base * days[m], 1)}
s = q(A.sql_ref_signups(launch))[0]
exp_ = s["pre_total"] / s["pre_days"] * s["post_days"]
k_obs = s["post_total"]
pval = 1 - sum(math.exp(-exp_ + i * math.log(exp_) - math.lgamma(i + 1)) for i in range(k_obs))  # P(X >= k_obs)
pays_ = q("SELECT COUNT(*) n, SUM(payout_amount) p FROM referrals")[0]
rev_per = q(f"""SELECT AVG(rev) a FROM (SELECT COALESCE(SUM(CASE WHEN p.status='succeeded' THEN p.amount END),0) rev
 FROM workspaces w LEFT JOIN payments p ON p.workspace_id=w.workspace_id AND p.payment_date BETWEEN '{Q3[0]}' AND '{Q3[1]}'
 WHERE w.signup_date >= '{launch}' GROUP BY w.workspace_id)""")[0]["a"]
out["referral"] = {
    "launch": launch, "referrals": pays_["n"], "payouts": pays_["p"], "post_signups": k_obs, "expected_post_signups": round(exp_, 1),
    "excess_signups": round(k_obs - exp_, 1), "poisson_one_sided_p": round(pval, 3),
    "monthly_placebo": placebo, "avg_sept_signup_q3_rev": round(rev_per, 2),
    "break_even_incremental_share": round(pays_["p"] / (pays_["n"] * rev_per), 3),
    "estimated_incremental_share_of_referrals": round(min(max(k_obs - exp_, 0), pays_["n"]) / pays_["n"], 3),
    "net_pp_if_incremental_share_is": {str(x): round((x * pays_["n"] * rev_per - pays_["p"]) / R2 * 100, 3)
                                       for x in (0.0, 0.1, 0.2, 0.3, 0.4, 0.6, 1.0)},
}

# ---------------------------------------------------------------- 4. cohort-accounting bridge (no counterfactuals)
base = {r["g"]: r for r in q(f"""SELECT CASE WHEN w.country IN ({eu}) THEN 'EU' ELSE 'non-EU' END g,
 SUM(CASE WHEN p.status='succeeded' AND p.payment_date BETWEEN '{Q2[0]}' AND '{Q2[1]}' THEN p.amount ELSE 0 END) r2,
 SUM(CASE WHEN p.status='succeeded' AND p.payment_date BETWEEN '{Q3[0]}' AND '{Q3[1]}' THEN p.amount ELSE 0 END) r3
 FROM payments p JOIN workspaces w USING(workspace_id) WHERE w.signup_date < '{Q2[0]}' GROUP BY g""")}
out["cohort_accounting_pp"] = {
    "existing_base_EU": round((base["EU"]["r3"] - base["EU"]["r2"]) / R2 * 100, 3),
    "existing_base_nonEU": round((base["non-EU"]["r3"] - base["non-EU"]["r2"]) / R2 * 100, 3),
    "new_signup_cohort_delta": out["mix"]["three_way_new_cohort_delta_pp"]["total"],
    "referral_payouts_delta": round(-(pay["Q3"] - pay["Q2"]) / R2 * 100, 3),
    "total": round(total_pp, 3),
    "existing_base_nonEU_ratio_q3_over_q2": round(base["non-EU"]["r3"] / base["non-EU"]["r2"], 4),
    "existing_base_EU_ratio_q3_over_q2": round(base["EU"]["r3"] / base["EU"]["r2"], 4),
}

# ---------------------------------------------------------------- sample sizes
out["sample_sizes"] = {
    "workspaces_total": q("SELECT COUNT(*) n FROM workspaces")[0]["n"],
    "eu_workspaces": agg["EU"]["n"], "non_eu_workspaces": agg["non-EU"]["n"],
    "eu_monthly_active_at_hike": a_eu, "eu_annual_renewals_due_in_window": due("EU"),
    "q2_signups": n["Q2"], "q3_signups": n["Q3"],
    "referrals": pays_["n"], "post_launch_signups": s["post_total"],
    "experiment": q("SELECT arm, COUNT(*) n FROM experiment GROUP BY arm"),
}
json.dump(out, open(A.ROOT / "results" / "verification.json", "w"), indent=2, default=str)
print(json.dumps(out, indent=1, default=str))
