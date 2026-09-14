# Northstar — design notes

The original build spec, kept current. It encodes the reconciliation logic that makes the
numbers right; a naive parser of the same exports produces a savings rate that is off by
double-counted card payments, mis-signed Venmo flows and a landlord counted as a merchant.
**Section 5 is the whole value of the project.**

---

## 1. What "done" looks like

```
$ python update.py
✓ Loaded bank (2 csv + 0 pdf), cards (3), amazon (2), venmo (11), paystubs (config), balances (9 accounts), card bills (2 cards)
✓ Reconciled: 26-mo savings rate 31% · avg spend $2,868/mo · income verified
✓ Validation passed (20/20 checks)
✓ Wrote output/data.js
✓ Rendered output/index.html, output/dashboard.html, output/runway.html, output/portfolio_gauge.html
Done in 1.3s
```

Drop a fresh statement into the right `data/` subfolder, rerun, and the dashboards reflect
it. No network calls at build time; the only outbound traffic in the whole project is the
optional read-only Gmail fetch in `tools/sync_alerts.py`, which runs *before* the build.

---

## 2. Repo structure

```
northstar-finance/
├── config.yaml             ← every household-specific value (Sec.6); nothing personal in code
├── update.py               ← entry point: load → reconcile → compute → validate → render
├── finlib/
│   ├── loaders.py          ← one loader per source (Sec.4)
│   ├── reconcile.py        ← the rules in Sec.5
│   ├── metrics.py          ← the computations in Sec.7
│   ├── validate.py         ← the 20 fail-loudly checks in Sec.9
│   ├── render.py           ← writes data.js, copies the templates
│   ├── alerts.py           ← issuer transaction-alert emails → pending card rows (Sec.4g)
│   └── gmail_sync.py       ← read-only Gmail fetch with DPAPI-encrypted token
├── templates/              ← the four pages, data-driven; hand-written commentary (Sec.8)
├── synth/                  ← generator for the sample household (every file in data/)
├── data/                   ← the raw exports the loaders read (sample data committed)
├── tools/                  ← local server, alert sync, demo build, Windows launchers
├── docs/                   ← this file + the static demo GitHub Pages serves
└── output/                 ← generated; git-ignored
```

---

## 3. Coverage is reported, never assumed

Every source covers a different window and the dashboards say so. Bank history defines the
income-and-spending window (26 months in the sample); cards, Venmo and Amazon run their own
lengths. A month with no bank rows is a **missing statement, not a frugal month**: it is
excluded from every average and surfaced on the *Data quality* panel instead of quietly
dragging the numbers down.

---

## 4. Data sources & schemas

### 4a. Bank — credit union (`data/bank/*.csv`, optional `*.pdf`)
Columns: `Date, Description, Original Description, Amount, Type, Parent Category, Category, Account, Tags, Memo, Pending`
- **`Amount` is always positive.** Direction comes from `Type` (`Credit` in, `Debit` out).
- `Account` distinguishes checking from savings; both are in the file.
- Exports are year-at-a-time and overlap at the boundaries. The loader dedupes on
  `(Date, Description, Amount, Type, Account)` **per occurrence**, so two genuinely identical
  same-day rows (two $2.75 transit taps) both survive while the overlap collapses.
- Monthly statement PDFs extend history before the first CSV row and after the last one.
  Every statement's parsed deposit/withdrawal totals are checked against its printed control
  totals; a line format the parser does not handle fails the build rather than dropping rows.
  Institution-specific wording is mapped through `config.bank_statement_pdf`.

### 4b. Cards — Chase activity exports (`data/cards/Chase<last4>_Activity_*.csv`)
Columns: `Transaction Date, Post Date, Description, Category, Type, Amount, Memo`
- **Purchases** are `Type == "Sale"` with a negative `Amount` → `abs()`. `Payment`, `Return`
  and `Fee` never count as spend.
- Card identity is the four digits in the filename; `config.cards` names it.
- Statement facts (closing balance, due date, rewards block) come from statement PDFs when
  present, or from `data/cards/statements.json` (the same facts transcribed). The newest
  statement per card wins; `data/balances/credit_cards.csv` can supply a newer *current*
  balance, and the dashboards label which kind they are showing.

### 4c. Amazon (`data/amazon/*.csv`)
Columns: `order id, order url, order date, quantity, description, item url, price, subscribe & save, ASIN`
- `price` is a `$27.48` string; line total = price × quantity; stray subtotal rows are dropped.
- Item descriptions are categorised by `config.amazon_categories`; short ambiguous keywords
  (`cat`, `pet`, `pan`) match whole words only, so *carpet* is not a pet.
- Amazon is **itemization**, never new spend: the card already carries the charge. On the
  *This Month* tab each order is matched back to the card charge that paid for it (subtotal
  within a tax-and-shipping window, within six days), so a charge opens into its line items.

### 4d. Venmo (`data/venmo/VenmoStatement_Jan_Dec_YYYY.csv`)
- The real header is on row 3 (`header=2`); rows 1–2 are the account banner and there are
  junk balance rows — keep only rows with a `Datetime` and a `Type`.
- `Amount (total)` is a string like `- $1,000.00`; the sign is the direction.
- Counterparty = `To` if `From` is the account holder (`config.identity.venmo_name`), else `From`.
- `Standard Transfer` rows are bank↔Venmo moves and are excluded.

### 4e. Paystubs
Image-based, not parsed. The pay structure lives in `config.pay` and changes only on a raise.
Two integrity checks cover it: components sum to gross to the cent, and gross × checks/year
matches the annual salary.

### 4f. Chewy (`data/chewy/*.csv`) — itemization only
A scraped order list with cosmetic column names and one or two products surfaced per order.
The card already carries `CHEWY.COM`; this source powers the *Cat Care* tab. Per-order totals
are the money figure (reconciled to the card; the gap is applied promo credit); item list
prices are a representative sample.

### 4g. Card transaction alerts (`data/alerts/`)
Issuers email an alert within seconds of a swipe — the only near-real-time signal there is.
`finlib/alerts.py` parses them with hard guarantees (see the module docstring): Decimal money,
sender allow-list, subject/body cross-check, declines and holds quarantined, two dedupe keys.
Alerts are **authorisations**: they live in the pending lane and each card's own statement
export supersedes its alerts independently. A card with alerts off falls back to the balance
in its monthly "statement is ready" email, labelled as a balance rather than spending.

### 4h. Balances (`data/balances/`)
`balances.csv` is one row per account (assets and the receivable); `VANGUARD_ACCOUNT_LIST.csv`
is the brokerage's positions export, parsed only up to the transaction block. Account balances
must equal the sum of their positions (a check), and every account carries its own `as_of`,
because a brokerage refreshed today must not make a two-month-old pension statement look current.

---

## 5. Reconciliation rules — the core of the project

Everything is on an **accrual basis**: spending is counted when it was charged, not when the
card was paid, so payment timing cannot distort the savings rate.

### 5a. Classify every bank debit into exactly one bucket (first match wins)
1. **LOAN_OUT** — principal lent to a person (`config.loans_out`, keyword *and* date window).
   A balance-sheet move: the cash leaves, an equal receivable arrives. Never spending.
2. **INTERNAL_TRANSFER** — checking↔savings sweeps (`config.bank_internal_transfer_descriptions`).
   Excluded entirely; a check asserts they net to ~0.
3. **INVESTING** — `Parent Category == "Investments"` or `config.investing_desc_match`.
   Tracked as *capital deployed*, not consumption.
4. **FAMILY** — transfers to the family account (`config.entities.family_desc_match`). Own line,
   subtracted from savings, never consumption. Money that comes back nets against it.
5. **CARD_PAYMENT** — `config.card_payment_desc_matches`. Excluded, because the purchases are
   already counted from the card files. Counting both is the classic double-count.
6. **DIRECT_SPEND** — every other debit: rent, utilities, debit-card swipes, ATM, laundry.

**INCOME** = `Type == "Credit"` and `Parent Category == "Income"`. Within it, only rows matching
`config.payroll_desc_matches` are salary; a settlement, a refund or a reimbursement is real
money but the *salary-only* view strips it, because a windfall read as income is the easiest
way to misjudge a month.

### 5b. Total spend = bank DIRECT_SPEND + card purchases, per month
Never add card-payment rows. Never add Amazon, Chewy or Venmo statement rows — they itemize
money the bank or a card already recorded.

### 5c. Savings
```
saved = income − total_spend − family
rate  = saved / income            (also reported against salary only, and against gross
                                   with the automatic retirement deductions added back)
```

### 5d. Venmo is relabelled, not added
The bank only ever says *Transfer to Venmo*. The Venmo statement names a counterparty on every
payment, so each month's transfer is split across the categories it funded, in that month's
proportions (`config.venmo_category_split`). Money is conserved — the bank amount stays
authoritative, only its label is refined. Loan principal and one-off events are tagged but
unmapped, so they never drag the mix toward a category they did not fund.

### 5e. Known entities
Fruit vendor → groceries; movie buddy → entertainment; historical roommates → rent; a settled
personal loan stays settled (a Venmo-only ledger still shows the net-out and says why).

---

## 6. `config.yaml` — everything household-specific

Identity and pay structure; the cards (autopay, issuer, whether alerts are on); the entities
above; event dates the trend framing uses (cooking started, card pivot, Autoship enrolled);
keyword → category maps for bank/card descriptions, Amazon items and Chewy items; display
names; budgets; merchant aliases and the city/state tails to strip; an optional frozen `clock`
(the sample pins it to its as-of date); the corner-store price grid
and known items; one-time costs per month; loans out; transactions the exports have not caught
yet; per-charge notes; liabilities; tax-bucket and asset-allocation maps; the emergency-fund
target; and the state unemployment maximum for the runway. The committed copy describes the
generated sample household; `ASSUMPTIONS.md` lists what was invented.

---

## 7. Metrics (`finlib/metrics.py` → `output/data.js` as `window.DASHBOARD_DATA`)

`summary`, `paycheck`, `trends`, `categories` (with per-merchant drill-downs and 12-month
sparklines), `merchants` (leaderboard plus the grab-and-go habit), `deli_decode` (tickets read
back into baskets), `energy` (one product priced across three channels), `savings_history`,
`month_review` (current month against the trailing year, category by category, every hot charge
opened to its receipt), `recurring` (cadence, ended services, price creep), `forward_30` (the
next 30 days of committed cash), `rewards`, `fixed_floor`, `paycheck_view`, `deferral_math`,
`era_analysis` (did the card pivot change spending, or just the rails?), `data_quality`,
`red_flags`, `amazon`, `chewy`, `net_worth_detail` (with positions and concentration),
`card_alerts`, `runway_inputs`, `financial_integrity`.

Every dollar figure is rounded for display and kept raw for math. Averages run over complete
months only; lifetime totals cover everything observed.

---

## 8. Rendering

The templates are static, data-driven HTML: `render.py` writes `data.js` and copies them,
giving each copy a versioned `data.js?v=` so an open tab cannot reuse a stale dataset.

**Honest limitation:** the *numbers* and *charts* update automatically. The narrative sentences
("cooking cut eating-out 37%", "the corner store is your top discretionary line") are authored
against a specific household and only need editing when the *story* changes, not every refresh.
`tests/test_sample_hygiene.py` pins the figures the sample's commentary quotes to the data.

---

## 9. Validation (`finlib/validate.py`) — fail loudly, every run

Twenty checks, most of them critical (the build stops): paycheck arithmetic (two checks);
category breakdown reconciles to total spend; no interior gap in bank coverage; internal
transfers net to ~0; reported coverage windows match the data; and a chain of balance-sheet
identities — tax buckets, stock/bond/cash allocation and account rows each sum to total assets,
net worth equals assets minus liabilities, liability rows sum, summary and balance sheet agree,
loan receivables reconcile, runway and balance sheet use the same spendable cash, position
values equal shares × price, brokerage positions reconcile to account balances, and the
integrity contract the command center reads matches the source metrics. Non-critical: spend
anomalies (>3× median) and data freshness (>35 days stale).

---

## 10. Adding new data

Export the newest statement → drop it in the matching `data/` subfolder → `python update.py`.
Overlaps are safe (Sec.4a); superseded full-history pulls can be deleted or kept. A raise means
editing `config.pay`. A new merchant that lands in *Other* means adding a keyword.

---

## 11. Tech stack

Python 3.11+, `pandas`, `pyyaml`; `pdfplumber` for statement PDFs; `google-api-python-client`
+ `google-auth-oauthlib` only for the alert fetch. The sample generator is stdlib-only and
seeded. `update.py` flags: `--validate-only`, `--source <name>`, `--open`, `--config`, `--data`,
`--output`.

---

## 12. Gotchas checklist

- [ ] Bank `Amount` is positive — use `Type` for direction.
- [ ] Venmo header is row 3; drop non-`Datetime` rows; exclude `Standard Transfer`.
- [ ] Card `Sale` amounts are negative — `abs()`; exclude `Payment`/`Return`/`Fee`.
- [ ] Never count bank card-payment rows **and** card purchases.
- [ ] Family transfers, investing and loans out are not spending — own lines.
- [ ] A settled loan is not a receivable.
- [ ] Paystub figures live in config, not parsed.
- [ ] Report real coverage windows; averages over complete months only.
- [ ] Narrative prose is semi-static; only numbers auto-update.
- [ ] Alerts are authorisations: pending lane only, superseded per card.
- [ ] Verify the state unemployment maximum and the IRS 403(b)/457(b) limits each year.
