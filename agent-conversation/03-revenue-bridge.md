# 03 - Revenue bridge, with independent checks

Q2 net revenue 559,534.00 -> Q3 525,746.05 = **-6.04%** (succeeded payments minus referral payouts). Blind: ground truth not read.

## Bridge, in pp of Q2 revenue

| cause | API (`/api/revenue-bridge`) | independent check | match? |
|---|---|---|---|
| Plan mix shift | -2.35 (-4.81 to +0.11) | -2.32 (Q2 ARPU weights) | yes |
| EU price increase | -5.74 (-11.52 to -0.12) | -2.05 (-3.46 to -0.63) mechanism; -2.85 exposure-adjusted DiD | **no, 3.7pp apart** |
| Referral programme | -1.26 (-1.91 to -0.16) | -1.32 at 20% incremental (break-even table) | yes |
| Unexplained | +3.31 | **-0.38** using the mechanism EU estimate; **+0.42** using the exposure-adjusted DiD | **depends on the EU choice** |

"Unexplained" is total minus the other three, so it absorbs every error in them. With the API's EU number it is +3.3pp; with either better EU estimate it is within 0.5pp of zero.

## Independent decomposition with no counterfactuals (cohort accounting)

| piece | pp |
|---|---|
| Existing customers, EU (signed before Apr 2025) | -7.75 |
| Existing customers, non-EU | -1.83 |
| New signup cohort (Q3 vs Q2) | +2.04 |
| Referral payouts | -1.91 |
| **Total** | **-6.04** |

Sums to the total exactly. It shows where the money moved (the EU base) but cannot separate price from renewal timing, so it does not settle the EU question.

## Sample sizes behind each line

| line | n | how small? |
|---|---|---|
| Mix | 450 and 549 signups | small: share shift is 1.9 SE, range includes 0 |
| EU | 162 EU annual renewals, 1,166 EU monthly subs active at hike | annual part is small and lumpy ($480-552 each) |
| Referral | 87 referrals, 192 post-launch signups | small: bump p = 0.079, within monthly noise |
| Onboarding | 106 treatment / 115 control | small: +17.6pp, range +4.6 to +30.6 |

## Status
- The API now serves the mechanism-based EU estimate (-2.05pp, D6); the DiD (-5.74pp) is kept as a labelled cross-check. Unexplained is now -0.38pp (range -3.35 to +2.59).
- Raw rows: `results/raw/` (7 CSVs). Checks: `results/verification.json`.
