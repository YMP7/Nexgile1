# 04 - Report drafting

Drafted `REPORT.md` with the five requested sections in order. Blind: `proctor_only/ground_truth.json` was not read.

## Inputs
- `results/numbers.json` (bridge, summary, initiatives) for every figure in sections 1-3.
- `results/verification.json` for the cross-checks (revenue definitions, exposure-adjusted DiD, cohort accounting, break-even).
- My own logs and `DECISIONS.md` (D1-D8) for section 4.

## Structure choices
| item | choice | why |
|---|---|---|
| Command at top | `python -m backend.analysis; if ($?) { python -m uvicorn backend.main:app --port 8000 }` | PowerShell 5.1 has no `&&`. `backend.analysis` rewrites `results/numbers.json` in a fresh process (the cache is per-process); uvicorn then serves it. |
| Extra commands | verify, frontend dev, generator (22 min) listed below the main one | the request asked for one exact command; the rest are context. |
| Memo | 359 words, plain language, one table with call + confidence + why | "one page max". Checked by word count, not by rendering a page. |
| Bridge sum line | table has both "sum of bars -6.04" and "actual -6.04%", plus a sentence that it holds by construction | "Unexplained" is a plug, so the sum proves nothing about the three causes. A reader should not take it as validation. |
| Section 5 | says the logs are my written logs, not a verbatim transcript, and that `01.md`, `04.md`, `05.md`, `README.md` are empty | the request said the full conversation is in `agent-conversation/`; that is not true as stated. |

## Checks run on the draft
- Script compared every bridge row (points and range), Q2/Q3 revenue, total, onboarding effect and arm sizes, EU mechanism components, ticket count, EU subscription counts, referral payouts/count/cannibalised share, DiD and exposure-adjusted figures against the two JSON files. **No mismatches.** Bridge bars sum to the total to within 0.0001.
- All three confidence ratings in the JSON are "medium"; calls are keep / change / stop, as stated in the memo.

## Errors found while drafting
1. **Stale figure in an earlier log.** `02-hypothesis-testing.md` said 278 EU price-complaint tickets; that came from the first dataset. The database and `numbers.json` say 232 (EU only). Fixed in the log, confirmed by a direct query, listed in REPORT section 4.
2. **Onboarding revenue link flipped sign between datasets** (-4.8 on the first dataset, +19.0 now, range -4.0 to +42.1). The memo says "not yet shown to raise revenue", which is still correct; the flip is recorded in section 4 as evidence of noise.
3. **Section 4 had to say "blind" is partly cosmetic.** I wrote the generator and know its mechanisms. The report now says so instead of implying an independent test.

## Not done / open
- Memo length not checked on a rendered page; 359 words should fit, but unverified.
- The memo in the API (`summary.memo`) and the memo in REPORT are separate texts. The numbers agree (checked); the wording does not have to.
- The recommendations in the memo include two suggestions that I did not test (a smaller or phased EU increase; paying referrals only for annual or retained customers). The report labels them as untested.
- REPORT sections 1-3 are copied, not generated. If `numbers.json` changes, they must be updated by hand; the comparison script was run once and is not saved in the repo.
