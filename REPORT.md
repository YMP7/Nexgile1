# Why Q3 2025 revenue fell 6.0% below Q2

## Regenerate and rerun (from the repo root, PowerShell)

```powershell
python -m backend.analysis; if ($?) { python -m uvicorn backend.main:app --port 8000 }
```

The first command recomputes every number from `db/revenue.sqlite` and rewrites `results/numbers.json`; the second serves the same numbers at `/api/*`. Every figure in sections 1-3 is copied from that file.

Related commands:

```powershell
python -m backend.verify                    # independent re-derivations -> results/verification.json, raw rows in results/raw/
npm --prefix frontend run dev               # dashboard at http://localhost:5173 (needs the API above)
python scripts/generate_synthetic_data.py   # rebuilds the database and proctor_only/ground_truth.json (about 22 minutes)
```

**The data is synthetic.** I wrote the generator, so these findings show that the method recovers the mechanisms I put in. They do not show that a real company behaves this way.

---

## 1. Memo to the CEO

**Revenue fell 6.0%, from $559,534 in Q2 to $525,746 in Q3, even though signups grew 22% and early retention improved (41% to 52% of new customers still active after 30 days).** Revenue here means money collected minus partner payouts.

Where the 6.0 points went (each figure is a share of Q2 revenue; the range is the plausible band):

- **More customers chose the monthly plan: -2.4 points** (range -4.8 to +0.1). Monthly customers pay $29 a month; annual customers pay $480 up front. This one could be close to zero.
- **The European price rise: -2.0 points** (range -3.5 to -0.6). The 15% increase earned +3.2 points, but extra cancellations cost 5.2.
- **The partner referral programme: -1.3 points** (range -1.9 to -0.2).
- **Unexplained: -0.4 points** (range -3.3 to +2.6). Statistically this is zero.

**Recommendations**

| Initiative | Call | Confidence | Why |
|---|---|---|---|
| New onboarding | **Keep** | Medium | In a randomised test, 58% of new workspaces on the new flow were still active at 30 days vs 41% on the old one (+17.6 points, range +4.6 to +30.6; 106 vs 115 workspaces). It has not yet been shown to raise revenue. |
| Europe price rise | **Change** | Medium | European monthly cancellations jumped from 10% to 39% (elsewhere: 8% to 9%), and 38% of European annual accounts did not renew vs 22% elsewhere. The increase costs more than it earns. A smaller or phased increase, or protection for renewing customers, is worth testing; I have not tested either. |
| Referral programme | **Stop** (as designed) | Medium | We paid $10,690 for 87 referrals. About 78% of them look like people who would have signed up anyway. It would only break even if 65% were genuinely new. This counts the first quarter's revenue only, so a restructured programme (for example, paying only for annual or retained customers) deserves a second look. |

**How sure are we?** Samples are small (450 and 549 signups, 87 referrals), and the ranges cover chance variation only. Treat these as strong leads, not proof. Section 4 lists what I got wrong along the way.

---

## 2. Revenue bridge

From `results/numbers.json`. Percentage points of Q2 net revenue ($559,534.00). Q3 net revenue is $525,746.05.

| Cause | Points | 95% range |
|---|---|---|
| Plan mix shift (more monthly signups) | -2.35 | -4.81 to +0.11 |
| EU price increase (net of extra cancellations) | -2.05 | -3.46 to -0.63 |
| Referral programme (cannibalisation net of payouts) | -1.26 | -1.91 to -0.16 |
| Unexplained | -0.38 | -3.35 to +2.59 |
| **Sum of bars** | **-6.04** | |
| Actual change in net revenue | -6.04% | |

The bars sum to the total **by construction**: "Unexplained" is the actual change minus the other three. The sum is a bookkeeping check, not evidence that the three explanations are right. The unexplained range assumes the other errors are independent, which is rough.

Cross-check with no counterfactuals (`results/verification.json`): existing EU customers -7.75, existing non-EU customers -1.83, new-signup cohort +2.04, referral payouts -1.91; total -6.04. It shows where the money moved but cannot separate price from renewal timing.

---

## 3. Analysis behind each initiative

All numbers come from SQL on the raw tables; the query behind each is in `results/numbers.json` (`evidence_query`). The raw rows are in `results/raw/` (7 CSVs).

### Checks run on the whole dataset
- **Revenue definition.** Five candidate definitions give a Q2-to-Q3 change between -4.13% (ignoring payouts) and -6.50% (counting every charge attempt). I use succeeded payments minus payouts (-6.04%). If the company's own dashboard uses another definition, its headline will differ.
- **Reconciled to the cent.** 17,540 raw payment rows re-added in Python equal the SQL sums (Q2 $559,534.00; Q3 gross $536,436.05).
- **API and file agree.** `results/numbers.json` is written from the same object the API serves. `backend/verify.py` also asserts that the API's EU number equals its own independent calculation.

### Plan mix (-2.35 points)
- **Evidence.** The monthly plan's share of new signups rose from 60.0% to 65.8% (450 and 549 signups). In-quarter revenue per new Q3 workspace is $56.80 on monthly and $473.23 on annual.
- **Check.** Re-weighting with Q2's revenue-per-plan gives -2.32; the two agree. A three-way split of the new-signup cohort gives volume +3.86, mix -2.32, revenue per plan +0.50 (net +2.04). Volume growth is the largest positive item.
- **Uncertainty.** The share shift is 1.9 standard errors from zero, so the range includes zero.

### Europe price rise (-2.05 points)
- **Method.** Price uplift on post-1-August EU payments (+3.19) minus revenue lost to excess monthly cancellations (-2.76) and excess annual non-renewals (-2.47). "Excess" means above the non-EU rate over the same window.
- **Evidence.** Of 1,166 EU monthly subscriptions active on 1 August, 451 cancelled (38.7%), against 9.0% outside the EU (143 of 1,586). That is about 346 excess cancellations at roughly $46.69 of lost Q3 revenue each. Of 162 EU annual renewals due in Aug-Sep, 61 did not renew (37.7%) against 21.5% elsewhere (54 of 251): about 26 excess. 232 price-complaint tickets since the hike, all from the EU.
- **Checks that disagreed.** A revenue-ratio comparison (EU vs non-EU Q3/Q2) gave -5.74 (range -11.5 to -0.1). It is biased: 12% fewer EU annual renewals fell due in Q3 (282 to 249; non-EU 390 to 387), and annual payments are lumpy. Scaling for that exposure gives -2.85. I use the mechanism-based figure (-2.05) and report the others, not an average. A 0.8-point gap between -2.85 and -2.05 is unexplained.

### Referral programme (-1.26 points)
- **Evidence.** Programme launched 1 Sept: 87 referrals, 12 partners, $10,690 in payouts. Signups ran at 5.76 a day before launch and 6.40 a day after, about 19 more than the earlier rate predicts (range 0 to 52; one-sided p = 0.079). Estimated cannibalised share: 78%. Average Q3 revenue per September signup is about $189 against $122.89 of payout per referral, so break-even needs 65% of referrals to be incremental.
- **Check.** The same arithmetic on other months gives a July shortfall of 22.6 signups, larger than September's gain of 19.3, so the bump is not clearly distinguishable from normal variation. Net effect if 0% / 20% / 60% / 100% of referrals were incremental: -1.91 / -1.32 / -0.15 / +1.03 points.
- **Limit.** Only first-quarter revenue is counted. A monthly customer signed on 20 September has paid once.

### Onboarding (+17.6 points of 30-day retention)
- **Evidence.** Experiment in two countries (US, DE): 58.5% retained on treatment (n = 106) vs 40.9% on control (n = 115). Retention means any product event at least 30 days after signup.
- **Check.** Control (40.9%) matches the Q2 cohort (40.9%), which supports control behaving like the old flow. Q3's overall rate (51.9%) reflects the new flow going to everyone outside the control group.
- **Revenue link.** Monthly-plan workspaces still paying 55+ days after signup: +19.0 points on treatment, range -4.0 to +42.1. Not shown: the range includes zero.

---

## 4. What the agent got wrong

Every error or doubtful assumption I caught, and what is still open. Decision log: `DECISIONS.md`.

**Caught and fixed**

1. **The first dataset did not contain the effects I specified.** Q3 monthly share was 61.4% vs 61.8% in Q2, and there was no September signup bump from referrals. My generator's calibration checks passed because they measured effects inside the simulator, not what is visible in the data. Found when the first bridge came out wrong (mix +0.17, EU -5.48, referral -2.51, unexplained +1.91). I changed the generator to give exact plan shares and to add referral signups on top of the trend (D1), and regenerated. Every earlier number was discarded.
2. **The EU estimate I first shipped was biased.** The revenue-ratio comparison blamed -5.74 points on the price rise, mostly because fewer EU annual renewals happened to fall due. Caught by a structurally different re-derivation; you chose the mechanism-based estimate (D3, D4, D6).
3. **A stale figure in my own log.** The EU ticket count was written as 278 (from the old dataset); the database says 232. Corrected in `02-hypothesis-testing.md`.
4. **A concurrency bug.** Five simultaneous first requests each recomputed the whole analysis and the page hung. Found only by running the UI; fixed with a lock (D8).
5. **Code slips found by running it:** a Poisson calculation that overflowed, and string literals broken by escaping, twice. All fixed.

**Assumptions I made that you should weigh**

6. **"Blind" is partly cosmetic.** I never opened `proctor_only/ground_truth.json`, and no analysis code reads it. But I wrote the generator and know its mechanisms (price, cancellation hazard, cohort sizes, referral cannibalisation), and the mechanism-based estimator mirrors them. A real company's churn would not separate this cleanly. This is not an independent test.
7. **The "unexplained" line is a plug.** It absorbs every error in the other three, and with the EU estimate I first shipped it was +3.3 points. The generator also creates its residual through a smaller renewal cohort a year earlier, which an analyst could not see from this data alone.
8. **Ad hoc rules.** The confidence rating (low if the range includes 0; high if it excludes 0 and is narrow; else medium) is my invention, and all three initiatives come out "medium". The keep/change/stop thresholds are mine too. The memo is a template and will read the same shape if the numbers change.
9. **Ranges cover chance only.** The 95% ranges reflect count noise. They do not include model risk (baseline choice, the 95.8% payment-success rate, the 30-day retention definition).
10. **The referral "stop" and onboarding "keep" are the least secure calls.** Referral counts first-quarter revenue only. Onboarding is kept on retention alone, and its revenue range includes zero. Between the old and regenerated datasets that revenue figure flipped sign (-4.8 to +19.0), which shows how noisy it is.

**Still uncertain**

- Whether the company's own revenue definition matches mine (headline moves between -4.1% and -6.5%).
- The 0.8-point disagreement between the two best EU estimates.
- Whether any of this holds with a different random seed; I tested one dataset.
- The frontend: untested on narrow screens or other browsers; no automated tests for it or for the backend.

---

## 5. The agent conversation

The working logs are in `agent-conversation/` (`02-hypothesis-testing.md`, `03-revenue-bridge.md`, `03b-frontend.md`, `04-report-drafting.md`), and decisions are in `DECISIONS.md`. These are my written logs, not a verbatim transcript. `01.md`, `04.md`, `05.md` and `README.md` there are still empty.
