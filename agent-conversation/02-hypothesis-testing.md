# 02 - Hypothesis testing (round 2: raw rows, sample sizes, independent re-derivation)

Blind: nothing in this file reads `proctor_only/ground_truth.json`. Everything is reproducible with
`python -m backend.verify` (writes `results/verification.json` and the raw rows in `results/raw/`).

## What was asked
1. Show the raw rows behind each number, not the aggregate.
2. State the sample size; give a range if it is small.
3. Re-derive each number a structurally different way and show any mismatch. Do not average discrepancies away.

## H4 - definitions (tested first)
Same database, five candidate revenue definitions. The headline moves by 2.4pp depending on which one a dashboard uses.

| definition | Q2 | Q3 | change |
|---|---|---|---|
| **A (used): succeeded - referral payouts** | 559,534.00 | 525,746.05 | **-6.04%** |
| B succeeded only (payouts ignored) | 559,534.00 | 536,436.05 | -4.13% |
| C succeeded + refunded - payouts | 570,807.00 | 533,940.85 | -6.46% |
| D every attempted charge - payouts | 590,012.00 | 551,650.30 | -6.50% |
| E = A with 30 Jun / 30 Sep dropped (off-by-one) | 559,025.00 | 524,095.35 | -6.25% |

Reconciled to the cent: 17,540 raw payment rows (`results/raw/payments_q2_q3.csv`) re-added in Python give Q2 559,534.00 and Q3 536,436.05 (gross), identical to the SQL sums.
Referral payouts alone are 1.91pp of the Q2->Q3 change (10,690.00, all dated Sept).

## H1 - plan mix
**Raw rows** (`signup_cohorts_q2_q3.csv`, 999 rows; first rows):
`7554,IN,monthly,2025-04-01,Q2,87.0` / `7556,US,annual,2025-04-01,Q2,480.0` / `7558,DE,monthly,2025-04-01,Q2,87.0`
(in-quarter revenue is 3 payments of 29 for an early-April monthly signup, one payment of 480 for annual).

**Sample:** n = 450 (Q2) and 549 (Q3) signups. Monthly share 60.0% -> 65.8%, shift +5.76pp, SE 3.07pp, so the shift is only 1.9 SE from zero.

| derivation | mix effect |
|---|---|
| used: Q3 in-quarter ARPU gap ($56.80 vs $473.23) | -2.35pp, 95% range **-4.81 to +0.11** |
| structurally different: Q2 ARPU gap ($53.92 vs $464.00) | -2.32pp |
| three-way new-cohort decomposition (volume / mix / ARPU rate) | +3.86 / -2.32 / +0.50 = +2.04pp, residual 0.00 |

Match: the two weightings agree to 0.04pp. **The range still includes zero** because 549 signups cannot pin down a 6pp share shift. Point estimate is stable; its significance is borderline.
Volume growth is worth +3.86pp; it is the biggest positive item in the bridge and is not a "cause" in the brief's list.

## H2 - EU price increase (the one that did not match)
**Raw rows.** `eu_per_workspace.csv` (8,552 rows), `eu_monthly_cancellations_post_hike.csv` (451 rows), `eu_biggest_swings.csv`.
Example cancellations: `9,DE,2023-04-01,2025-08-01,29.0` / `537,IT,2023-06-01,2025-08-01,29.0` / `2554,FR,2024-01-01,2025-08-01,29.0`.
**The 25 biggest EU "swings" are all annual accounts that paid 480 in Q2 and nothing in Q3** (e.g. `12,ES,annual,2023-04-02,480.0,0`). That is renewal timing (next payment 2026), not a price reaction. A per-workspace Q2->Q3 comparison is dominated by this.

**Sample sizes:** 3,583 EU and 4,969 non-EU workspaces, but the effect rests on small counts: 1,166 EU monthly subscriptions active at the hike (451 cancelled, 38.7%, vs 143 of 1,586 = 9.0% non-EU), and only **162 EU annual renewals due in Aug-Sep** (61 not renewed, 37.7%, vs 54 of 251 = 21.5% non-EU).

| derivation | EU effect, pp of Q2 revenue | range |
|---|---|---|
| used: DiD, EU vs non-EU Q3/Q2 revenue ratio (0.883 vs 1.016) | **-5.74** | -11.52 to -0.12 (bootstrap, 300 resamples) |
| structural: price uplift (+3.19) - excess monthly cancels (-2.77) - excess annual non-renewals (-2.47) | **-2.05** | -3.46 to -0.63 (count noise only) |
| DiD by plan, annual scaled by relative renewal exposure (0.890) | **-2.85** | not computed |

**These do not match.** The DiD and the structural estimate differ by 3.69pp, about two thirds of the DiD figure. Not averaged.
Where the gap sits: annual plans. EU annual revenue fell 13.2% (142,560 -> 123,720); non-EU annual rose 3.6%. Renewals falling due: EU 282 (Q2) -> 249 (Q3), -11.7%; non-EU 390 -> 387, -0.8%. The DiD assumes both groups would have had the same Q3/Q2 ratio, and for lumpy annual revenue they did not, by chance. Adjusting only for that moves the DiD from -5.76 to -2.85.
Remaining gap between the two better estimates: 0.80pp (-2.85 vs -2.05). It is inside the structural range but I cannot explain it from the data; candidate causes are the structural baseline choice (non-EU post-hike rates; using the EU's own pre-hike rate changes the monthly loss from 2.77 to 2.65) and the 0.958 payment-success assumption.
Price-complaint tickets since the hike: 232 EU, none outside the EU (qualitative support only).

**Verdict:** the DiD is not trustworthy for this effect. The structural estimate is tighter and conditions on what actually fell due, but its range covers count noise only, not model risk.

## H3 - referral cannibalisation
**Raw rows** (`referrals_with_value.csv`, 87 rows): `1,7,8361,2025-09-01,120.0,US,monthly,29.0` / `3,8,8364,2025-09-01,150.0,ES,annual,552.0`; `daily_signups_q2_q3.csv` (183 days).
**Sample:** 87 referrals, 12 partners, 192 signups after launch (30 days) vs 357 in the 62 days before.
Excess signups over the Jul-Aug rate: **+19.3**, one-sided Poisson p = 0.079.
**Placebo, same arithmetic on other months:** deviation from the quarter's other months is Apr +2.5, May -11.1, Jun +8.4, Jul **-22.6**, Aug +3.0, Sep +19.3. July's miss is larger than September's bump. The September bump is not distinguishable from ordinary month-to-month noise.
Break-even: payouts per referral 122.9 vs 188.9 average in-quarter revenue per September signup, so referrals break even only if **65%** are incremental. The estimate is 22% (range 0-60%, i.e. the upper end is still below break-even).

| share of referrals that are incremental | net effect |
|---|---|
| 0% | -1.91pp |
| 20% | -1.32pp |
| 40% | -0.74pp |
| 60% | -0.15pp |
| 100% | +1.03pp |

Used estimate: -1.26pp, range -1.91 to -0.16. Match with the break-even table at 22%: yes.
**Limit that matters:** revenue is counted in-quarter only. A monthly referral signed on 20 Sep has paid once; its later payments are ignored, which understates the programme's value. The sign of the conclusion is therefore not secure beyond this quarter.

## Not done / open
- The exposure-adjusted DiD has no confidence interval.
- The unexplained residual depends on which EU estimate is used (see 03).
- No second dataset or seed was tested.
