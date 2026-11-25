#!/usr/bin/env python3
"""Generate db/revenue.sqlite (Q2 vs Q3 2025) and proctor_only/ground_truth.json.

Net revenue = succeeded payments in quarter - referral payouts in quarter.
Each driver's pp effect is measured by counterfactual re-simulation on the same random
draws (workspace-level common random numbers), and the driver parameters are tuned
until the effects hit the targets. Stdlib only; deterministic for a given SEED.
"""
import json
import random
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "db" / "revenue.sqlite"
GT = ROOT / "proctor_only" / "ground_truth.json"
SEED = 20250925

END, HIKE, REF_LAUNCH = date(2025, 9, 30), date(2025, 8, 1), date(2025, 9, 1)
Q2S, Q2E, Q3S = date(2025, 4, 1), date(2025, 6, 30), date(2025, 7, 1)
TARGETS = {"mix": -2.5, "eu": -2.0, "referral": -1.0, "total": -6.0}  # pp of Q2 revenue

EU = {"DE": .14, "FR": .10, "ES": .07, "IT": .06, "NL": .05}
NON_EU = {"US": .25, "GB": .10, "IN": .10, "BR": .07, "CA": .06}
COUNTRIES = list(EU) + list(NON_EU)
WEIGHTS = list(EU.values()) + list(NON_EU.values())
TEST_COUNTRIES = {"US", "DE"}  # where onboarding was first tested
PRICE = {"monthly": 29.0, "annual": 480.0}
EU_HIKE = 1.15
BASE_HAZARD, BASE_RENEW, FAIL, REFUND = 0.05, 0.80, 0.03, 0.02
CANNIBALIZED = 0.70  # share of referred signups who would have signed up organically anyway
PAYOUTS = [100.0, 120.0, 150.0]  # by partner tier
N_Q2 = 450
N_Q3 = round(N_Q2 * 1.22)
P_MONTHLY_Q2 = 0.60
RET_Q2, RET_Q3 = 0.41, 0.52
KNOB_COHORT, KNOB_BASE = "B2024Q3", 1050  # renewal-cohort size is the free knob for the total

COHORTS = [  # name, first day, last day, size
    ("B2023Q2", date(2023, 4, 1), date(2023, 6, 30), 800),
    ("B2023Q3", date(2023, 7, 1), date(2023, 9, 30), 850),
    ("B2023Q4", date(2023, 10, 1), date(2023, 12, 31), 900),
    ("B2024Q1", date(2024, 1, 1), date(2024, 3, 31), 950),
    ("B2024Q2", date(2024, 4, 1), date(2024, 6, 30), 1000),
    (KNOB_COHORT, date(2024, 7, 1), date(2024, 9, 30), 1890),  # up to 1.8x; trimmed by knob
    ("B2024Q4", date(2024, 10, 1), date(2024, 12, 31), 1050),
    ("B2025Q1", date(2025, 1, 1), date(2025, 3, 31), 1100),
    ("Q2", Q2S, Q2E, N_Q2),
    ("Q3", Q3S, END, N_Q3),
    ("Q3X", REF_LAUNCH, END, 200),  # incremental referred signups, added on top of the organic trend
]


def add_months(d, k):
    m = d.month - 1 + k
    return date(d.year + m // 12, m % 12 + 1, min(d.day, 28))


def make_slot(cohort, idx, first, last):
    r = random.Random(f"{SEED}:{cohort}:{idx}")
    u = r.random
    return {
        "cohort": cohort, "idx": idx,
        "start": first + timedelta(days=int(u() * ((last - first).days + 1))),
        "u_country": u(), "u_plan": u(), "u_refsel": u(), "u_inc": u(), "u_partner": u(),
        "u_renew": [u() for _ in range(3)],
        "u_pay": [u() for _ in range(34)], "u_churn": [u() for _ in range(34)],
        "country": r.choices(COUNTRIES, WEIGHTS)[0],
    }


ALL_SLOTS = [make_slot(n, i, a, b) for n, a, b, size in COHORTS for i in range(size)]


def world(P, fl):
    """Workspaces existing in a counterfactual world + their plans. Plan shares are exact
    (rank on u_plan), so the realised monthly share equals the parameter. fl: mix/eu/ref."""
    K = round(P["k"])
    n_knob = round(KNOB_BASE * P["f"])
    pop = [s for s in ALL_SLOTS
           if not (s["cohort"] == KNOB_COHORT and s["idx"] >= n_knob)
           and not (s["cohort"] == "Q3" and s["idx"] >= N_Q3 - K)
           and not (s["cohort"] == "Q3X" and (s["idx"] >= K or not fl["ref"]))]
    groups = {}
    for s in pop:
        groups.setdefault("Q3" if s["cohort"] in ("Q3", "Q3X") else s["cohort"], []).append(s)
    plan = {}
    for g, lst in groups.items():
        p = P["p3"] if g == "Q3" and fl["mix"] else P_MONTHLY_Q2
        lst.sort(key=lambda s: s["u_plan"])
        for i, s in enumerate(lst):
            plan[id(s)] = "monthly" if i < round(p * len(lst)) else "annual"
    return pop, plan


def referred_ids(P):
    """K incremental referred signups plus the cannibalised ones (organic Sept signups that
    would have come anyway): R = K / (1 - CANNIBALIZED) referrals in total."""
    K = round(P["k"])
    inc = [s for s in ALL_SLOTS if s["cohort"] == "Q3X" and s["idx"] < K]
    n_cann = round(K / (1 - CANNIBALIZED)) - K
    sept = sorted((s for s in ALL_SLOTS if s["cohort"] == "Q3" and s["idx"] < N_Q3 - K and s["start"] >= REF_LAUNCH),
                  key=lambda s: s["u_refsel"])
    return {id(s) for s in inc + sept[:n_cann]}


def partner(s):
    return 1 + int(s["u_partner"] * 12)


def payout(s):
    return PAYOUTS[partner(s) % 3]


def simulate(s, P, fl, plan):
    """Return (payments[(date, amount, status)], cancel_date). fl: mix / eu / ref booleans."""
    eu = s["country"] in EU and fl["eu"]
    pays, cancel = [], None

    def pay(d, k):
        amt = round(PRICE[plan] * (EU_HIKE if eu and d >= HIKE else 1), 2)
        u = s["u_pay"][k]
        pays.append((d, amt, "failed" if u < FAIL else "refunded" if u < FAIL + REFUND else "succeeded"))

    pay(s["start"], 0)
    anchor = s["start"]
    k = 1
    while True:
        d = add_months(anchor, k) if plan == "monthly" else add_months(anchor, 12 * k)
        if d > END:
            break
        if plan == "monthly":
            h = BASE_HAZARD + (P["eu_uplift"] if eu and d >= HIKE else 0)
            churn = k >= 2 and s["u_churn"][k] < h  # first cancel can't precede day ~60
        else:
            r = BASE_RENEW - (1.2 * P["eu_uplift"] if eu and d >= HIKE else 0)
            churn = s["u_renew"][k - 1] >= max(r, 0.1)
        if churn:
            cancel = d
            break
        pay(d, k)
        k += 1
    return pays, cancel


def revenue(P, fl):
    r2 = r3 = 0.0
    pop, plan = world(P, fl)
    for s in pop:
        for d, amt, st in simulate(s, P, fl, plan[id(s)])[0]:
            if st == "succeeded":
                if Q2S <= d <= Q2E:
                    r2 += amt
                elif d >= Q3S:
                    r3 += amt
    if fl["ref"]:
        r3 -= sum(payout(s) for s in ALL_SLOTS if id(s) in referred_ids(P))
    return r2, r3


ALL = {"mix": True, "eu": True, "ref": True}


def effect_one(P, key):
    r2, r3 = revenue(P, ALL)
    return (r3 - revenue(P, {**ALL, key: False})[1]) / r2 * 100


def total_pp(P):
    r2, r3 = revenue(P, ALL)
    return (r3 / r2 - 1) * 100


def effects(P):
    out = {"total": total_pp(P)}
    for name, key in (("mix", "mix"), ("eu", "eu"), ("referral", "ref")):
        out[name] = effect_one(P, key)
    out["residual"] = out["total"] - out["mix"] - out["eu"] - out["referral"]
    return out


def solve(fn, lo, hi, target, decreasing=True, n=10):
    for _ in range(n):
        mid = (lo + hi) / 2
        if (fn(mid) > target) == decreasing:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def tune():
    P = {"p3": 0.72, "eu_uplift": 0.15, "k": 25.0, "f": 1.0}
    for _ in range(8):
        P["p3"] = solve(lambda x: effect_one({**P, "p3": x}, "mix"), 0.60, 0.98, TARGETS["mix"])
        P["eu_uplift"] = solve(lambda x: effect_one({**P, "eu_uplift": x}, "eu"), 0.0, 0.6, TARGETS["eu"])
        P["k"] = solve(lambda x: effect_one({**P, "k": x}, "ref"), 0.0, 150.0, TARGETS["referral"])
        P["f"] = solve(lambda x: total_pp({**P, "f": x}), 0.2, 1.8, TARGETS["total"], decreasing=False)
        e = effects(P)
        if all(abs(e[k] - TARGETS[k]) < .08 for k in TARGETS):
            break
    return P, e


TICKET_GENERIC = [
    "How do I export my reports to CSV?", "Can't find where to invite a teammate.",
    "Dashboard is loading slowly today.", "Need help connecting my data source.",
    "How do I change the workspace owner?", "Feature request: dark mode for the editor.",
    "Where can I download past invoices?", "Question about API rate limits.",
]
TICKET_PRICE = [
    "Why did my price go up? I was not told about this increase.",
    "The new price is too high for our team, we are reconsidering our subscription.",
    "Price increase of 15% is not acceptable, please cancel my plan.",
    "Our renewal quote is higher than last year. Is there any discount?",
]
TICKET_REFERRAL = [
    "I signed up through a partner link, where do I find my referral credit?",
    "Referred by a partner, can you confirm the offer applies to my account?",
]
TICKET_PAYMENT = [
    "My card was declined but I have funds, please retry the payment.",
    "Payment failed on my last invoice, how do I update billing details?",
]
TICKET_ONBOARDING = ["The setup wizard confused me, where do I start?", "Onboarding checklist is unclear."]


def build():
    P, eff = tune()
    rng = random.Random(SEED + 1)
    pop, plans = world(P, ALL)
    refset = referred_ids(P)
    referred = lambda s, _P=None: id(s) in refset
    sims = {id(s): (plans[id(s)], *simulate(s, P, ALL, plans[id(s)])) for s in pop}
    for s in pop:  # incremental referred signups belong to the Q3 cohort
        if s["cohort"] == "Q3X":
            s["cohort"] = "Q3"
    pop.sort(key=lambda s: (s["start"], s["cohort"], s["idx"]))
    wid = {id(s): i + 1 for i, s in enumerate(pop)}
    ws_rows, sub_rows, pay_rows, ev, ref_rows, tk = [], [], [], [], [], []

    def ts(d, lo=8, hi=20):
        return datetime(d.year, d.month, d.day, rng.randint(lo, hi), rng.randint(0, 59), rng.randint(0, 59))

    for s in pop:
        w = wid[id(s)]
        plan, pays, cancel = sims[id(s)]
        eu = s["country"] in EU
        ws_rows.append((w, s["country"], plan, s["start"].isoformat()))
        price = round(PRICE[plan] * (EU_HIKE if eu and pays[-1][0] >= HIKE else 1), 2)
        sub_rows.append((w, plan, price, s["start"].isoformat(), cancel.isoformat() if cancel else None,
                         "cancelled" if cancel else "active"))
        pay_rows += [(w, a, d.isoformat(), st) for d, a, st in pays]
        if referred(s, P):
            ref_rows.append((partner(s), w, payout(s), s["start"].isoformat()))

    # experiment (Q3 signups in the two test countries) and retention assignment
    byid = {wid[id(s)]: s for s in pop}
    q2 = [w for w, s in byid.items() if s["cohort"] == "Q2"]
    q3 = [w for w, s in byid.items() if s["cohort"] == "Q3"]
    arm = {w: rng.choice(["treatment", "control"]) for w in q3 if byid[w]["country"] in TEST_COUNTRIES}
    exp_rows = [(w, a, byid[w]["country"]) for w, a in sorted(arm.items())]
    ctrl = [w for w, a in arm.items() if a == "control"]
    treated = [w for w in q3 if arm.get(w) != "control"]
    ret = set(rng.sample(q2, round(RET_Q2 * len(q2))))
    ret_ctrl = rng.sample(ctrl, round(RET_Q2 * len(ctrl)))
    ret |= set(ret_ctrl) | set(rng.sample(treated, round(RET_Q3 * len(q3)) - len(ret_ctrl)))

    for w, s in byid.items():
        start, cancel = s["start"], sims[id(s)][2]
        if s["cohort"] in ("Q2", "Q3"):
            ev.append((w, "signup", ts(start)))
            for t in rng.sample(["create_project", "invite_member", "first_report", "login"], rng.randint(2, 3)):
                ev.append((w, t, ts(start + timedelta(days=rng.randint(0, 6)))))
            if rng.random() < (0.35 if s["cohort"] == "Q2" else (0.4 if arm.get(w) == "control" else 0.8)):
                ev.append((w, "onboarding_completed", ts(start + timedelta(days=rng.randint(0, 3)))))
            if w in ret:
                for _ in range(rng.randint(2, 3)):
                    ev.append((w, rng.choice(["login", "create_project", "first_report"]),
                               ts(start + timedelta(days=rng.randint(30, 36)))))
        else:
            for qs, qe in ((Q2S, Q2E), (Q3S, END)):
                if cancel is None or cancel > qs:
                    ev.append((w, "login", ts(qs + timedelta(days=rng.randint(0, (qe - qs).days)))))

    # support tickets
    def ticket(w, d, text):
        tk.append((w, min(d, END).isoformat(), text))

    for w, s in byid.items():
        plan, pays, cancel = sims[id(s)]
        eu = s["country"] in EU
        if eu and cancel and cancel >= HIKE and rng.random() < 0.55:
            ticket(w, cancel - timedelta(days=rng.randint(0, 10)), rng.choice(TICKET_PRICE))
        elif eu and not cancel and s["start"] < HIKE and rng.random() < 0.04:
            ticket(w, HIKE + timedelta(days=rng.randint(0, 59)), rng.choice(TICKET_PRICE))
        if referred(s, P) and rng.random() < 0.12:
            ticket(w, s["start"] + timedelta(days=rng.randint(0, 5)), rng.choice(TICKET_REFERRAL))
        for d, _, st in pays:
            if st == "failed" and d >= Q2S and rng.random() < 0.3:
                ticket(w, d + timedelta(days=rng.randint(0, 3)), rng.choice(TICKET_PAYMENT))
        if s["cohort"] in ("Q2", "Q3") and rng.random() < 0.05:
            ticket(w, s["start"] + timedelta(days=rng.randint(0, 6)), rng.choice(TICKET_ONBOARDING))
        if rng.random() < 0.03:
            ticket(w, max(s["start"], Q2S) + timedelta(days=rng.randint(0, 60)), rng.choice(TICKET_GENERIC))
    tk = [(i + 1, *t) for i, t in enumerate(sorted(tk, key=lambda t: t[1]))]
    ref_rows = [(i + 1, *r) for i, r in enumerate(sorted(ref_rows, key=lambda r: r[3]))]

    # write DB
    DB.parent.mkdir(exist_ok=True)
    GT.parent.mkdir(exist_ok=True)
    DB.unlink(missing_ok=True)
    con = sqlite3.connect(DB)
    con.executescript("""
    CREATE TABLE workspaces(workspace_id INTEGER PRIMARY KEY, country TEXT, plan TEXT CHECK(plan IN('monthly','annual')), signup_date TEXT);
    CREATE TABLE events(workspace_id INTEGER REFERENCES workspaces, event_type TEXT, event_timestamp TEXT);
    CREATE TABLE subscriptions(workspace_id INTEGER REFERENCES workspaces, plan TEXT, price REAL, start_date TEXT, cancel_date TEXT, status TEXT);
    CREATE TABLE payments(workspace_id INTEGER REFERENCES workspaces, amount REAL, payment_date TEXT, status TEXT CHECK(status IN('succeeded','refunded','failed')));
    CREATE TABLE experiment(workspace_id INTEGER REFERENCES workspaces, arm TEXT CHECK(arm IN('treatment','control')), country TEXT);
    CREATE TABLE referrals(referral_id INTEGER PRIMARY KEY, partner_id INTEGER, referred_workspace_id INTEGER REFERENCES workspaces, payout_amount REAL, referral_date TEXT);
    CREATE TABLE support_tickets(ticket_id INTEGER PRIMARY KEY, workspace_id INTEGER REFERENCES workspaces, ticket_date TEXT, text TEXT);
    CREATE INDEX ix_pay ON payments(payment_date); CREATE INDEX ix_ev ON events(workspace_id);
    """)
    ev = [(w, t, d.isoformat(sep=" ")) for w, t, d in sorted(ev, key=lambda e: e[2])]
    for tbl, rows in (("workspaces", ws_rows), ("events", ev), ("subscriptions", sub_rows), ("payments", pay_rows),
                      ("experiment", exp_rows), ("referrals", ref_rows), ("support_tickets", tk)):
        con.executemany(f"INSERT INTO {tbl} VALUES({','.join('?' * len(rows[0]))})", rows)
    con.commit()

    # self-checks (calibration + consistency), measured from the written DB
    q = lambda sql: con.execute(sql).fetchone()[0]
    rev = lambda a, b: q(f"SELECT SUM(amount) FROM payments WHERE status='succeeded' AND payment_date BETWEEN '{a}' AND '{b}'")
    r2, r3 = rev("2025-04-01", "2025-06-30"), rev("2025-07-01", "2025-09-30") - q("SELECT SUM(payout_amount) FROM referrals")
    sig = lambda a, b: q(f"SELECT COUNT(*) FROM workspaces WHERE signup_date BETWEEN '{a}' AND '{b}'")
    ret_rate = lambda a, b: q(f"""SELECT AVG(r) FROM (SELECT w.workspace_id,
        MAX(CASE WHEN julianday(substr(e.event_timestamp,1,10))-julianday(w.signup_date) BETWEEN 30 AND 36 THEN 1 ELSE 0 END) r
        FROM workspaces w JOIN events e USING(workspace_id) WHERE w.signup_date BETWEEN '{a}' AND '{b}' GROUP BY 1)""")
    checks = {
        "total_-6.0": abs((r3 / r2 - 1) * 100 - TARGETS["total"]) < 0.1,
        "mix": abs(eff["mix"] - TARGETS["mix"]) < 0.15, "eu": abs(eff["eu"] - TARGETS["eu"]) < 0.15,
        "referral": abs(eff["referral"] - TARGETS["referral"]) < 0.15,
        "residual_~-0.5": -0.8 <= eff["residual"] <= -0.2,
        "signups_+22%": abs(sig("2025-07-01", "2025-09-30") / sig("2025-04-01", "2025-06-30") - 1.22) < 0.005,
        "ret_q2_~41": abs(ret_rate("2025-04-01", "2025-06-30") - RET_Q2) < 0.01,
        "ret_q3_~52": abs(ret_rate("2025-07-01", "2025-09-30") - RET_Q3) < 0.01,
        "no_pay_after_cancel": q("""SELECT COUNT(*) FROM payments p JOIN subscriptions s USING(workspace_id)
            WHERE s.cancel_date IS NOT NULL AND p.payment_date >= s.cancel_date""") == 0,
    }
    if not all(checks.values()):
        raise SystemExit(f"calibration failed: {checks}\n{eff}\n{P}")

    GT.write_text(json.dumps({
        "seed": SEED,
        "revenue_definition": "succeeded payments in quarter minus referral payouts in quarter (Q2=Apr-Jun, Q3=Jul-Sep 2025)",
        "targets_pp_of_q2_revenue": TARGETS | {"residual": -0.5},
        "realized_pp_of_q2_revenue": {k: round(v, 3) for k, v in eff.items()},
        "revenue": {"q2": round(r2, 2), "q3_net": round(r3, 2)},
        "effect_method": "one-at-a-time counterfactual re-simulation on shared random draws; residual = total - sum(mix, eu, referral)",
        "tuned_parameters": P,
        "fixed_parameters": {
            "prices": PRICE, "eu_countries": list(EU), "eu_price_hike": EU_HIKE, "eu_hike_date": str(HIKE),
            "eu_cancel_uplift_monthly_hazard": round(P["eu_uplift"], 4),
            "eu_annual_renewal_drop": round(1.2 * P["eu_uplift"], 4),
            "base_monthly_hazard": BASE_HAZARD, "base_annual_renewal": BASE_RENEW,
            "payment_fail_rate": FAIL, "refund_rate": REFUND,
            "signups": {"q2": N_Q2, "q3": N_Q3, "growth": 0.22},
            "monthly_plan_share": {"q2": P_MONTHLY_Q2, "q3": round(P["p3"], 4)},
            "referral": {"launch": str(REF_LAUNCH), "cannibalized_share": CANNIBALIZED, "payouts_by_partner_tier": PAYOUTS,
                         "incremental_referred_signups": round(P["k"]), "referrals": len(ref_rows)},
            "retention_30d": {"q2": RET_Q2, "q3": RET_Q3, "definition": "any event 30-36 days after signup",
                              "experiment_countries": sorted(TEST_COUNTRIES),
                              "note": "Q3 rolled out new onboarding to all signups except experiment control arm"},
            "unexplained_residual_mechanism": "smaller 2024-Q3 annual renewal cohort (renewal-cohort size), no causal story in the data",
        },
    }, indent=2))

    for t in ("workspaces", "events", "subscriptions", "payments", "experiment", "referrals", "support_tickets"):
        print(f"{t:16s}{q(f'SELECT COUNT(*) FROM {t}'):>8d}")
    print("calibration + consistency checks: OK")
    con.close()


if __name__ == "__main__":
    build()
