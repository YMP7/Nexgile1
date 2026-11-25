# DECISIONS

Live log. Newest entries at the bottom. Analysis is blind: nothing here reads `proctor_only/ground_truth.json`.

## D1 - Regenerated the dataset after finding it did not embody the spec
- **Found:** first dataset had Q3 monthly-plan share 61.4% vs Q2 61.8% (no visible mix shift) and no September signup bump from referrals. Cause: random plan assignment (noise ~2pp vs a ~6pp shift) and incremental referral signups placed inside a flat signup curve.
- **Decision:** patched `scripts/generate_synthetic_data.py` (exact plan shares by rank; incremental referred signups added on top of the Sept trend), regenerated, calibration checks passed.
- **Cost:** generator now takes ~22 min. Output is deterministic (seed fixed).
- **Not done:** I did not open ground_truth.json to decide this; the flaws were visible from the data and the spec text.

## D2 - Interpreting "show me the raw rows behind this number"
- **Decision:** "this number" = every line of the revenue bridge, with the EU price effect first (widest range, and it leaks into "Unexplained"). Raw rows are exported to `results/raw/*.csv` and sampled in the logs; aggregates alone are not accepted as evidence.
- **Alternative rejected:** asking which number was meant. The bridge is one object; covering all four lines costs little.

## D3 - Two EU estimates disagree; not averaging them
- **Found:** difference-in-differences (EU vs non-EU Q3/Q2 revenue ratio) gives -5.74pp (95% bootstrap range -11.5 to -0.1). A mechanism-based estimate (price uplift on EU payments minus revenue lost to excess monthly cancellations and annual non-renewals, baselined on non-EU rates) gives -2.05pp (range -3.46 to -0.63). Gap = 3.7pp of Q2 revenue. The ranges overlap, but the point estimates are far apart.
- **Where the gap sits:** annual plans. EU annual revenue fell 13.2% Q2->Q3; non-EU annual rose 3.6%. The mechanism estimate only explains ~14k of the ~24k annual shortfall the DiD implies.
- **Hypothesis to test:** DiD assumes EU and non-EU would have had the same Q3/Q2 ratio. Annual revenue is lumpy (a renewal is $480-$552), so the *number of renewals falling due* in each quarter can differ by chance between groups. If so, DiD is mis-attributing exposure noise to the price rise. Testing by counting renewals due per quarter per group.
- **Rule:** I will report both, say which I trust and why, and not publish a blend.

## D4 - EU estimator: keep API unchanged until chosen
- Found: exposure-adjusting the DiD (EU saw 11.7% fewer annual renewals fall due than non-EU, 282 to 249 vs 390 to 387) moves it from -5.76pp to -2.85pp. The mechanism-based estimate is -2.05pp. The API serves -5.74pp.
- Effect on the bridge: "Unexplained" is +3.31pp with the API number, -0.38pp with the mechanism estimate, +0.42pp with the exposure-adjusted one.
- Decision: do not silently swap the estimator in backend/analysis.py. All three are in results/verification.json; the choice is waiting on the user.
- Recommendation: mechanism-based as headline, exposure-adjusted DiD as cross-check. Reason: it conditions on renewals actually due and has a narrower range. Caveat: its range covers count noise only, not model risk.

## D5 - Referral recommendation is in-quarter only
- Found: the September bump (+19 signups, p=0.079) is smaller than July's miss (-22.6). Estimated incremental share 22% vs break-even 65%.
- Decision: keep "stop" but label it in-quarter. Later payments of September signups are not counted, which biases against the programme.

## D6 - Adopted the mechanism-based EU estimator (user decision)
- Decision (user): EU price effect in the API and results/numbers.json is now price uplift minus excess monthly cancellations and annual non-renewals, baselined on non-EU rates. Implemented as `eu_mechanism()` in backend/analysis.py.
- Result: EU -2.05pp (range -3.46 to -0.63); "Unexplained" -0.38pp (range -3.35 to +2.59). Mix and referral unchanged.
- Kept: the revenue-ratio DiD (-5.74pp) stays in the europe_price evidence as a labelled cross-check. backend/verify.py asserts the API's EU number equals its own independent copy of the calculation (tolerance 0.002pp).
- Still true: the range is count noise only, not model risk. The 0.8pp gap to the exposure-adjusted DiD (-2.85pp) is unexplained.

## D7 - Frontend: confidence and memo are computed in the backend
- Problem: the brief asks for "confidence" per initiative and "CEO memo text pulled from /api/summary", but the API had neither.
- Decision: added `confidence` (+ `confidence_rule`) to each initiative and `memo` to /api/summary in backend/analysis.py, so numbers.json stays the single source and the frontend does no calculation.
- Confidence rule (mine, not a statistical standard): low = 95% range includes 0; high = range excludes 0 and half-width <= half the estimate; medium = range excludes 0 but wider. All three initiatives come out "medium".
- Memo is templated from the computed numbers; it is not written prose and will read the same if the numbers change sign.
- Chart: hand-rolled SVG instead of a charting library (no extra dependency for four bars).

## D8 - Fixed a concurrency bug found by running the UI
- Found: the page sat on "Loading..." because 5 simultaneous first requests each recomputed the whole analysis and rewrote numbers.json.
- Decision: wrapped `get_numbers()` in a lock. First request computes (~10 s); the rest wait and reuse it.
- Not done: no warm-up at startup, so the first page load after a server start is slow.

## D9 - Report drafting
- Decision: REPORT.md figures are copied from results/numbers.json and results/verification.json, then compared programmatically (no mismatches). The comparison script was not saved in the repo, so edits to numbers.json need a manual refresh of the report.
- Decision: the report says the bridge sums to the total by construction (Unexplained is a plug) and that "blind" is partly cosmetic because I wrote the generator.
- Decision: section 5 states that agent-conversation/ holds my written logs, not a verbatim transcript, and that 01.md, 04.md, 05.md and README.md are empty. The request described it as the full conversation, which is not accurate.
- Decision: command at the top is the PowerShell form (no &&): python -m backend.analysis; if ($?) { python -m uvicorn backend.main:app --port 8000 }.
- Fixed: stale ticket count (278 -> 232) in 02-hypothesis-testing.md.
