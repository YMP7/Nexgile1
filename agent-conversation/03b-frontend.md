# 03b - Frontend

Single-page React app in `frontend/` (Vite + React 18, no router, no auth, inline styles). It does no calculation: every number comes from the API, which serves `results/numbers.json`'s dict.

## Run
```
python -m uvicorn backend.main:app --port 8000     # from the repo root
npm --prefix frontend run dev                      # http://localhost:5173, proxies /api to :8000
```
The first page load after the API starts takes about 10 s (the analysis runs once, then is cached until the DB changes).

## What it fetches
`/api/revenue-bridge`, `/api/summary`, `/api/initiative/onboarding`, `/api/initiative/europe_price`, `/api/initiative/referral`, all in parallel on load. Any failed request shows the error text instead of the page.

## What it renders
| section | source | notes |
|---|---|---|
| Headline | summary | revenue change %, Q2 -> Q3 dollars, signups |
| CEO memo | `summary.memo` | shown as-is, line breaks kept |
| Bridge chart | bridge | one bar per cause, from zero; black whisker = 95% range; label under each bar `-2.05pp [-3.46, -0.63]`; hover or keyboard-focus a row for the cause, range and the SQL behind it |
| Sum check | bridge + summary | sum of the bars vs the total change (-6.04pp vs -6.04%) |
| Initiative cards | initiative/{name} | keep/change/stop badge, confidence, effect and range, collapsible evidence and SQL, confidence rule |

Chart is a hand-written SVG (no charting dependency).

## Backend changes this needed
- `confidence` and `confidence_rule` on every initiative, and `memo` on `/api/summary` (D7). Rule: low if the 95% range includes 0; high if it excludes 0 and its half-width is at most half the estimate; medium otherwise. This is my own rule, not a statistical standard. All three initiatives are "medium".
- A lock around the first computation (D8): five simultaneous requests had each recomputed everything, and the page hung on "Loading...".

## Checked
- `npm run build` succeeds (30 modules, 146 kB JS).
- Run in the browser against the live API: headline, memo, four bars, the hover detail panel, and the three cards all rendered with the same numbers as the API (EU -2.05, mix -2.35, referral -1.26, unexplained -0.38; keep/change/stop).
- Fixed one defect seen on screen: the zero axis crossed the value labels (labels now have a white outline). I did not re-screenshot after that last style change.

## Not checked
- No automated frontend test.
- Not tried on a narrow/mobile viewport; the chart is a fixed 900 px wide SVG.
- Not tried in a browser other than the in-app one.
- The memo is generated from a template, so its wording will not adapt if the findings change shape.
- `frontend/node_modules` and `frontend/dist` exist locally; there is no `.gitignore` (the project is not a git repository).
