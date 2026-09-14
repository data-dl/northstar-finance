# Assumptions

Every default in the sample household that was invented rather than derived, so nobody
mistakes a design choice for a fact. Change a row here, then `synth/persona.py` and
`config.yaml` follow; `python -m synth --out data && python update.py` rebuilds everything.

## The household

| Area | Assumption | Status |
|---|---|---|
| Person | One adult, "Casey Morgan", systems analyst at a county library in the fictional city of Lakeview (state code OH is used only as the city/state tail on card lines) | invented |
| Window | Bank history 2024-07-01 → 2026-08-31; card exports pulled 2026-09-01; alerts through 2026-09-11; "today" for the static demo is 2026-09-12 | invented |
| Pay | $81,250 gross, 26 biweekly checks from 2024-07-12, $1,970.68 net; deductions sum to gross to the cent (a validation check) | invented, arithmetic verified |
| Employer benefits | 403(b) at 5.5%, a county defined-benefit pension at 5.75%, health premium fully employer-paid, no disability coverage | invented |
| Non-salary income | Three deposits: a travel reimbursement, a state tax refund, a class-action settlement — so the salary-only view has something to strip | invented |

## Accounts

| Area | Assumption | Status |
|---|---|---|
| Bank | "Lakeshore Credit Union": Share Savings 0001 + Free Checking 0072; $24,880.35 combined at 2026-09-01. The balance is a snapshot, not derived from the transaction flow | invented |
| Cards | Chase Freedom ···4417 (alerts on, autopay), Chase Prime Visa ···8802 (alerts on, autopay), Discover it ···3160 moved to Capital One servicing (no export, alerts off) | invented |
| Statement cycles | Freedom closes the 19th and autopays the 16th; Prime Visa closes the 10th and autopays the 7th. Statement balances and points in `data/cards/statements.json` are computed from the generated purchases so everything reconciles | invented, derived |
| Brokerage | Vanguard: taxable x3142, Roth x8827, rollover x5510, Cash Plus x0417; Fidelity individual x4471 (no positions export, so the gauge carries a $181 statement bridge); Voya 403(b) $27,310.44; a prior state plan's DC side $11,062.18 | invented |
| Prices | VFIFX NAV 66.59; single-stock marks as listed in `synth/persona.py`; S&P baseline 648.20 in the gauge | invented, frozen |
| Liabilities | Student loan $3,118.40 at $78.20/mo; the two Chase balances; nothing else | invented |
| Loan out | $3,500 to "Alex Carver", lent 2026-08-20 by Zelle from savings, due 2026-12-20 | invented |

## Behaviour the commentary describes

| Area | Assumption | Status |
|---|---|---|
| Corner-store habit | "Fourth Street Market": ~19 visits/month on a $0.25 price grid plus 7% tax; the signature basket is a $3.25 Red Bull + $1.75 Clif Bar = $5.35 charged, ~46% of visits | invented; a test asserts >80% of tickets sit on the grid and >30% are the signature basket |
| Energy drinks | The same product is bought monthly on Amazon as a 24-pack at $42.00 ($1.75/can) via Subscribe & Save | invented |
| Cooking pivot | Cooking starts 2026-04-06: eating-out volume ×0.82 and grocery volume ×1.16 from April 2026 | invented |
| Card pivot | From 2026-05-19 everyday purchases move from the debit card (84%) to the Freedom (94%) | invented |
| Cat | Adopted May 2026; nine Chewy orders from 2026-05-22 with promo credits on some; cat gear bought on Amazon in July; Autoship enrolled 2026-07-15 | invented |
| Furnishing wave | May–Jul 2026 one-time costs listed in `config.one_time_costs` are generated as the matching purchases (bed frame, mattress, curtains, lamp, shoe bench, dental) | invented, tied to receipts |
| Venmo history | 2015 social only; roommate rent 2017–2021 (Priya $900 → Marcus $640 → Dana $500 per month); 2023 loan of $18,000 to "T. Okonkwo" with $6,060 repaid on-platform and the rest off-platform (net $11,940 on Venmo); 2024–2026 fruit cart, movies and shared meals; a $210 cabin-weekend payment on 2026-09-02 that the bank has not caught yet; no 2016 statement | invented |
| Family support | $120/month by Zelle, doubled in December, skipped once, raised once | invented |
| Subscriptions | Netflix $15.49 → $17.99 from Nov 2025 and Vantel Fiber $45 → $49 from Jan 2026 (price creep); Audible, Hulu and a renters' policy ended in 2025 (ended services); Amazon Prime and Microsoft 365 annual | invented |
| Alerts | 21 alerts 2026-09-02 → 2026-09-11 including one refund; one fuel pre-auth parked in review; a Discover "statement is ready" balance of $184.20 | invented |

## Things deliberately not generated

| Area | Reason |
|---|---|
| Bank and card statement PDFs | The parsers are real (`finlib/loaders.py`) but producing pixel-faithful statement layouts is not worth the weight; the CSV path and `statements.json` exercise the same downstream logic. |
| Paystub images | Never parsed by the pipeline; the pay structure lives in `config.pay`. |
| Discover/Capital One activity | The card has no export in the sample, exactly the blind spot the real design documents; its two payments show up on the bank side as card payments. |
| Gmail traffic | The static demo replays a scripted sync; the real fetch needs a Google OAuth client and a Windows machine. |
