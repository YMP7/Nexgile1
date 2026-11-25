# UNDERSTANDING

## The business and the data, in my own words

The company sells a B2B SaaS product per **workspace**, on a **monthly** plan ($29) or an **annual** plan ($480, paid upfront). The question: **why was Q3 2025 (Jul–Sep) net revenue below Q2 2025 (Apr–Jun)?** It fell even though signups grew and a new onboarding flow appears to have improved early retention.

**The data is synthetic.** I wrote the generator (`scripts/generate_synthetic_data.py`) to match the brief's schema and wrote its output to `db/revenue.sqlite`. It is not real company data. The generator also writes `proctor_only/ground_truth.json`, which is sealed. I have not opened it and the analysis will not read it.

The tables in `db/revenue.sqlite`:

| Table | What it holds |
|---|---|
| `workspaces` | one row per customer: country, plan, signup date |
| `subscriptions` | price, start and cancel dates, status |
| `payments` | each charge: amount, date, `succeeded` / `refunded` / `failed` |
| `referrals` | partner referrals and the payout owed per referred workspace (programme launched Sep 2025) |
| `experiment` | onboarding A/B assignment for Q3 signups in the two test countries |
| `events` | product activity, used for 30-day retention |
| `support_tickets` | free text, useful as qualitative evidence (price complaints, referral questions) |

**Working revenue definition:** succeeded payments dated in the quarter, minus referral payouts dated in the quarter. Refunded and failed payments don't count. One of the first backend jobs is to pin this definition down and compare it with the alternatives (see H4).

## Hypotheses, ranked

1. **Plan mix shift (annual → monthly).** If more Q3 signups picked monthly, each one brings in $29 a quarter instead of $480 upfront. Q3 cash revenue drops even when signups grow. Test: plan share by signup quarter, then revenue per new workspace.
2. **Europe price increase → more cancellations.** EU prices went up around August. If the higher price drove extra cancellations or annual non-renewals, the lost revenue can outweigh what the higher price earns. Test: EU vs non-EU cancel and renewal rates before and after the increase, plus price-related support tickets.
3. **Referral cannibalisation.** Partner payouts are subtracted from revenue. If many referred workspaces would have signed up organically anyway, the payouts buy no new revenue. Test: referred vs organic signup volume and mix in September, payout total vs revenue from referred workspaces.
4. **Dashboard definitional mismatch.** This one is worth testing even on synthetic data. The generator is not the only place a bug can hide: my own dashboard queries can disagree with the revenue definition. Examples: counting refunded payments, skipping payouts, off-by-one date bounds, or using signup date where payment date belongs. Test: recompute the headline number under each candidate definition and reconcile them to the cent.

Any gap the four drivers leave unexplained gets reported as a **residual**. I won't stretch one of the four to cover it.

## What I doubt

- **The generator's assumptions are the biggest limitation.** Every mechanism in this data is one I wrote: fixed prices, a constant base churn hazard, set payment-failure and refund rates, a fixed cannibalisation share, and causal effects that only run through the parameters I chose. The analysis can recover those mechanisms. It cannot say whether a real company behaves this way. Findings here show that the method works, not that the business conclusions hold.
- **I'm not blind to the answer.** I wrote the generator, so I know which mechanisms are in it, and its source code includes the tuning targets. Sealing `ground_truth.json` stops anyone quoting the answer file. It does not make the analysis independent. To keep it honest, every number in the report will be computed from the database by the backend and reproducible from it, and none will be copied from the generator.
- **Each driver's effect depends on its counterfactual.** "How much did the mix shift cost" depends on the baseline, such as Q2's plan share. Effects measured one at a time won't sum exactly to the total. That's why the residual is reported separately.
- **Retention isn't revenue.** Onboarding improved 30-day retention, but in this window that may not show up in Q3 cash yet. I won't credit it as a revenue driver without evidence.
- **Small samples.** There are a few hundred new signups per quarter, and referrals cover only one month. Expect noisy per-country or per-partner figures.

## Two approaches and the trade-off

| | **A. Bottom-up revenue bridge (chosen)** | **B. Top-down cohort regression** |
|---|---|---|
| How | Start at Q2 revenue and add one bar per driver (mix, EU, referral, residual) to reach Q3. Each bar comes from a SQL counterfactual: what Q3 would have been with that driver held at its Q2 baseline. | Model revenue per workspace on cohort, plan, region, referral flag and the period after the price increase. Read the drivers off the coefficients. |
| Pros | Maps directly onto the deliverable, a waterfall/bridge chart and API endpoints. Every number traces back to a query. Easy to explain. | More rigorous: handles interactions and gives uncertainty estimates. |
| Cons | One driver at a time leaves a residual. Interactions aren't modelled. | Slow to build and validate, harder to turn into a dashboard, and specification choices need defending. |
| Verdict | **Chosen.** It's the analytical core of the deliverable and fits the time available. | Out of scope for the time available. Mentioned in the report as the next step. |

## Plan, in priority order

1. **Backend/API first.** It's the analytical core. Revenue definition and reconciliation (H4), then the per-driver bridge queries (H1–H3) and the residual, exposed as API endpoints, with a self-check that the bridge sums to the actual Q2→Q3 change.
2. **Frontend second.** A bridge/waterfall chart and per-driver breakdowns that read from the API. No calculations in the frontend.
3. **Report last.** `REPORT.md` covers the findings, the residual and the limitations above. `DECISIONS.md` gets updated as decisions are made.
