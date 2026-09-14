"""Computes the `metrics` dict serialized to output/data.js as window.DASHBOARD_DATA. See docs/DESIGN.md Sec.7."""
import re
import statistics

import pandas as pd

from finlib import reconcile as rc


def _month_label(period: pd.Period) -> str:
    return period.strftime("%b") + str(period.year)[-2:]


def _month_range(start: pd.Period, end: pd.Period):
    return list(pd.period_range(start, end, freq="M"))


def _categorize(description: str, categories_cfg: dict) -> str:
    desc_l = str(description).lower()
    for cat_key, cat in categories_cfg.items():
        for kw in cat["keywords"]:
            if kw.lower() in desc_l:
                return cat_key
    return "other"


def _category_tag(cat_key: str, categories_cfg: dict) -> str:
    if cat_key == "other":
        return "var"
    return categories_cfg[cat_key]["tag"]


_PROCESSOR_PREFIXES = ("sq ", "tst", "at ", "eb ", "google ", "paddle.net", "amzn mktp", "amazon mktp")


def _apply_merchant_alias(name: str, aliases: dict) -> str:
    """Map a normalized merchant name onto its canonical spelling (config `merchant_aliases`).

    A pattern is a substring match; prefix it with "=" to require the whole name to match instead
    (needed for short truncations like "Green", which must not swallow "Greenpoint Organic")."""
    low = name.casefold()
    for canonical, patterns in (aliases or {}).items():
        for p in patterns:
            p = p.casefold()
            if (low == p[1:]) if p.startswith("=") else (p in low):
                return canonical
    return name


def _merchant_name(description: str, location_suffixes=(), aliases=None) -> str:
    """Normalize a raw statement description into a display merchant name so the same store groups
    together across its variants (e.g. 'TACO BELL #035828' and 'Taco Bell' -> 'Taco Bell').

    `location_suffixes` (config `merchant_location_suffixes`) are the "LAKEVIEW OH" tails the credit
    union's statement PDFs append to card swipes; without stripping them the PDF-era rows for a store
    never join up with the same store's CSV-era rows."""
    s = str(description).replace("&amp;", "&").strip()
    # the statement PDFs mangle curly apostrophes ("MCDONALD�S"); normalize them all to "'"
    s = re.sub(r"[‘’´�]", "'", s)
    # "... LAKEVIEW OHEff. Date 06/30" -- the statement's effective-date tail, sometimes glued on
    s = re.sub(r"Eff\.?\s*(?:Date\s*[\d/]*)?\s*$", "", s).strip()
    low = s.lower()
    # credit-union rows are prefixed "Tran " (transaction); drop it
    if low.startswith("tran "):
        s = s[5:]
        low = s.lower()
    # PDF-era swipe lines: "Debit Card DEBIT TRAN <merchant> <city> <ST>"
    s = re.sub(r"^(?:debit|credit)\s+card\s+(?:debit|credit)\s+tran\s+", "", s, flags=re.IGNORECASE)
    # PDF-era PIN lines: "POS #000053788900 <merchant> <store code> <street address> <city> <ST>"
    is_pos = bool(re.match(r"^POS\s+#?\d+\s+", s, flags=re.IGNORECASE))
    s = re.sub(r"^POS\s+#?\d+\s+", "", s, flags=re.IGNORECASE)
    low = s.lower()
    for suf in location_suffixes:
        if low.endswith(" " + suf):
            s = s[: -(len(suf) + 1)].rstrip()
            low = s.lower()
            break
    # a phone number or "TEL800632009" standing in for the city, followed by the state code
    s = re.sub(r"\s+(?:tel)?[\d][\d\-]{5,}\s+[A-Za-z]{2}$", "", s, flags=re.IGNORECASE).strip()
    low = s.lower()
    # payment-processor prefixes like "SQ *RIVERSIDE SOCIAL" / "GOOGLE *Google One" -> take the merchant
    if "*" in s and any(low.startswith(p) for p in _PROCESSOR_PREFIXES):
        s = s.split("*", 1)[1].strip()
    # strip trailing store/reference numbers, "#1234", and credit-union "Co Name ..." noise
    s = re.split(r"\s+co name\b", s, flags=re.IGNORECASE)[0]
    if is_pos:
        # the street address begins at the first standalone number after the merchant name
        # ("KROGER 445 ELM ST 445 ELM ST" -> "KROGER")
        m = re.match(r"^(.*?\S)\s+\d[\d\s\-]*\s+\S.*$", s)
        if m and m.group(1):
            s = m.group(1)
    s = re.sub(r"\s+[A-Za-z]\d{3,}\s*$", "", s).strip()   # chain store codes: "F3391", "Q25"
    s = re.sub(r"\s+#?\d[\d\-]*(\s+[A-Za-z])?\s*$", "", s).strip()
    s = re.sub(r"\s{2,}", " ", s)
    if not s:
        s = str(description).strip()
    if len(s) > 34:
        s = s[:34].rstrip() + "…"
    if s.isupper() or s.islower():
        s = s.title()
        s = re.sub(r"'S\b", "'s", s)   # str.title() turns "MCDONALD'S" into "Mcdonald'S"
    return _apply_merchant_alias(s, aliases)


def _round2(x):
    return round(float(x), 2)


def today(config: dict) -> "pd.Timestamp":
    """The pipeline's idea of "now". Real data leaves `config.clock` unset and gets the wall
    clock; the committed sample pins it, so a dataset frozen at one date never reads as stale
    and the build is reproducible on any day."""
    clock = (config or {}).get("clock")
    return pd.Timestamp(str(clock)).normalize() if clock else pd.Timestamp.now()


def _tax_bucket(account_type: str, tax_buckets: dict) -> str:
    at = str(account_type).lower()
    for bucket, keywords in tax_buckets.items():
        if any(kw in at for kw in keywords):
            return bucket
    return "taxable"


def _split_holding(symbol, name, fund_alloc: dict, fund_kw: list) -> dict:
    """Return {stocks, bonds, cash} weights (summing to 1) for a holding or account fund."""
    sym = str(symbol) if symbol is not None else ""
    if sym in fund_alloc:
        w = fund_alloc[sym]
        return {"stocks": w.get("stocks", 0.0), "bonds": w.get("bonds", 0.0), "cash": w.get("cash", 0.0)}
    low = str(name or "").lower()
    for entry in fund_kw:
        if any(m in low for m in entry["match"]):
            return {"stocks": entry.get("stocks", 0.0), "bonds": entry.get("bonds", 0.0), "cash": entry.get("cash", 0.0)}
    return {"stocks": 1.0, "bonds": 0.0, "cash": 0.0}  # default: an individual equity / unknown fund


def _acct_suffix(name: str) -> str:
    m = re.search(r"x([0-9]{3,})", str(name))
    return m.group(1) if m else ""


def _alert_card_roster(config, alert_rows, card_max_by_id, statement_balances):
    """One row per configured card: what it has spent, or why it cannot say."""
    stmt = {str(r.get("card_id")): r for r in statement_balances}
    out = []
    for cid, cfg in sorted((config.get("cards") or {}).items()):
        cid = str(cid).zfill(4)
        mine = [r for r in alert_rows if r["card_id"] == cid]
        alerts_on = bool(cfg.get("alerts", True))
        row = {
            "card_id": cid,
            "name": cfg.get("name", f"Card {cid}"),
            "issuer": cfg.get("issuer", "Chase"),
            "alerts_enabled": alerts_on,
            "count": len(mine),
            "net": _round2(sum(r["amount"] for r in mine)),
            "covered_through": (pd.Timestamp(card_max_by_id[cid]).date().isoformat()
                                if cid in card_max_by_id else None),
            "statement_balance": None,
            "statement_as_of": None,
            "status": "live",
        }
        if not alerts_on:
            s = stmt.get(cid)
            row["status"] = "no_alerts"
            if s:
                row["statement_balance"] = s.get("balance")
                row["statement_as_of"] = s.get("as_of")
        elif not mine:
            row["status"] = "quiet"
        out.append(row)
    return out


def _compute_net_worth(config: dict, balances_df, holdings_df, card_statements_df=None) -> dict:
    nw = config.get("net_worth") or {}
    liabilities = [{**l, "source_type": "config"} for l in nw.get("liabilities", [])]
    if card_statements_df is not None and not card_statements_df.empty:
        for _, card in card_statements_df.iterrows():
            as_of = card.get("as_of")
            due_date = card.get("due_date")
            liabilities.append({
                "name": f"{card['card_name']} x{card['card_id']}",
                "balance": float(card["liability_balance"]),
                "monthly_payment": float(card.get("minimum_payment", 0) or 0),
                "as_of": None if pd.isna(as_of) else pd.Timestamp(as_of).date().isoformat(),
                "source_type": "credit_card",
                "card_id": card["card_id"],
                "balance_kind": card.get("balance_kind", "statement"),
                "statement_balance": _round2(card.get("statement_balance", 0) or 0),
                "statement_date": None if pd.isna(card.get("statement_date")) else pd.Timestamp(card["statement_date"]).date().isoformat(),
                "due_date": None if pd.isna(due_date) else pd.Timestamp(due_date).date().isoformat(),
                "autopay": bool((config.get("cards") or {}).get(card["card_id"], {}).get("autopay", False)),
                "source_file": card.get("snapshot_source") or card.get("source_file"),
            })
    if balances_df is None or balances_df.empty:
        # No data/balances/ CSVs present -- return liabilities-only shell so the tab still renders.
        lt = sum(l["balance"] for l in liabilities)
        return {"as_of": None, "assets_total": 0, "liabilities_total": _round2(lt),
                "net_total": _round2(-lt), "by_tax": {}, "allocation": {}, "accounts": [],
                "unfunded_accounts": [], "holdings": [], "concentration": {}, "liabilities": [
                    {**l, "balance": _round2(l["balance"]),
                     "monthly_payment": _round2(l.get("monthly_payment", 0))}
                    for l in liabilities]}
    if holdings_df is None:
        import pandas as _pd
        holdings_df = _pd.DataFrame()
    tax_buckets = nw.get("tax_buckets", {})
    fund_alloc = nw.get("fund_allocation", {})
    fund_kw = nw.get("fund_allocation_keywords", [])
    cash_like_symbols = {s for s, w in fund_alloc.items() if w.get("cash", 0) >= 1.0}

    assets = balances_df[balances_df["account_type"].str.upper() != "LIABILITY"].copy()
    funded = assets[assets["balance"] > 0]
    unfunded = assets[assets["balance"] == 0]

    assets_total = float(funded["balance"].sum())
    liabilities_total = sum(l["balance"] for l in liabilities)

    # ---- tax buckets ----
    by_tax = {}
    for _, a in funded.iterrows():
        b = _tax_bucket(a["account_type"], tax_buckets)
        by_tax[b] = by_tax.get(b, 0.0) + a["balance"]

    # ---- which accounts have per-holding detail (Vanguard) vs. summary-only ----
    holding_suffixes = set()
    if not holdings_df.empty:
        for acct_no in holdings_df["account_number"].unique():
            holding_suffixes.add(str(acct_no)[-4:])

    def _covered(acct_name):
        suf = _acct_suffix(acct_name)
        return bool(suf) and suf[-4:] in holding_suffixes

    # ---- allocation: stocks / bonds / cash ----
    alloc = {"stocks": 0.0, "bonds": 0.0, "cash": 0.0}
    single_stocks = {}  # symbol -> $ (identifiable individual equities only)
    if not holdings_df.empty:
        for _, h in holdings_df.iterrows():
            w = _split_holding(h["symbol"], h["name"], fund_alloc, fund_kw)
            for k in alloc:
                alloc[k] += h["value"] * w[k]
            # an identifiable single stock = 100% stock weight, real ticker, not a fund/MM
            if (h["symbol"] not in fund_alloc and h["symbol"] not in cash_like_symbols
                    and str(h["symbol"]).lower() != "null" and w["stocks"] >= 1.0):
                single_stocks[h["symbol"]] = single_stocks.get(h["symbol"], 0.0) + h["value"]

    # summary-only accounts (no holding detail): split their whole balance by fund keyword
    for _, a in funded.iterrows():
        if _covered(a["account"]):
            continue
        w = _split_holding(None, a.get("fund", ""), fund_alloc, fund_kw)
        for k in alloc:
            alloc[k] += a["balance"] * w[k]

    # ---- single-stock concentration ----
    single_stock_total = sum(single_stocks.values())
    top_stock = max(single_stocks.items(), key=lambda kv: kv[1]) if single_stocks else (None, 0.0)

    return {
        "as_of": balances_df["as_of"].dropna().astype(str).max() if "as_of" in balances_df else None,
        # the OLDEST balance date is what actually governs how stale the picture is: refreshing one
        # bank snapshot must not make month-old brokerage positions look current
        "as_of_oldest": (balances_df.loc[balances_df["balance"] > 0, "as_of"]
                         .dropna().astype(str).min() if "as_of" in balances_df else None),
        "holdings_as_of": (balances_df.loc[
            balances_df["source_file"].astype(str).str.contains("VANGUARD", case=False, na=False),
            "as_of"].dropna().astype(str).min() if "source_file" in balances_df else None),
        "assets_total": _round2(assets_total),
        "liabilities_total": _round2(liabilities_total),
        "net_total": _round2(assets_total - liabilities_total),
        "by_tax": {k: _round2(v) for k, v in by_tax.items()},
        "allocation": {k: _round2(v) for k, v in alloc.items()},
        "accounts": [
            {"institution": a["institution"], "name": a["account"], "balance": _round2(a["balance"]),
             "tax_bucket": _tax_bucket(a["account_type"], tax_buckets), "fund": a.get("fund", ""),
             # each account ages at its own speed -- a Vanguard export refreshed today sits beside
             # a brokerage statement two months old, and one "positions are current" line hides that
             "as_of": str(a.get("as_of") or "")}
            for _, a in funded.sort_values("balance", ascending=False).iterrows()
        ],
        "unfunded_accounts": [
            {"name": a["account"], "note": a.get("notes", "")}
            for _, a in unfunded.iterrows()
        ],
        "holdings": [
            {"symbol": s, "value": _round2(v)}
            for s, v in sorted(single_stocks.items(), key=lambda kv: -kv[1])
        ],
        # Position-level detail is the source of truth for the live gauge. Keeping shares and
        # baseline marks in data.js means a new Vanguard export updates the gauge automatically
        # instead of leaving a second, hand-maintained portfolio hidden in the HTML template.
        "positions": [
            {
                "account_suffix": str(h["account_number"])[-4:],
                "name": str(h["name"]),
                "symbol": str(h["symbol"]),
                "shares": round(float(h["shares"]), 6),
                "price": round(float(h["price"]), 6),
                "value": _round2(h["value"]),
            }
            for _, h in holdings_df.iterrows()
        ],
        "concentration": {
            "single_stock_total": _round2(single_stock_total),
            "single_stock_pct_assets": _round2(single_stock_total / assets_total * 100) if assets_total else 0,
            "top_symbol": top_stock[0],
            "top_value": _round2(top_stock[1]),
            "top_pct_assets": _round2(top_stock[1] / assets_total * 100) if assets_total else 0,
        },
        "liabilities": [
            {**l, "balance": _round2(l["balance"]), "monthly_payment": _round2(l.get("monthly_payment", 0))}
            for l in liabilities
        ],
    }


def compute_metrics(loaded: dict, config: dict) -> dict:
    bank = loaded["bank"]
    cards = loaded["cards"]
    amazon = loaded["amazon"]
    venmo = loaded["venmo"]
    balances = loaded.get("balances")
    holdings = loaded.get("holdings")
    card_statements = loaded.get("card_statements")
    card_alerts = loaded.get("card_alerts")
    alert_review = loaded.get("alert_review") or []
    statement_balances = loaded.get("statement_balances") or []

    bank = rc.reconcile_bank(bank, config)
    cards = rc.reconcile_cards(cards)
    venmo_r = rc.reconcile_venmo(venmo, config)

    # ---- coverage windows ----
    bank_min, bank_max = bank["Date"].min(), bank["Date"].max()
    bank_start_p, bank_end_p = bank_min.to_period("M"), bank_max.to_period("M")

    # ---- manual transactions: things that happened after the last export ----
    # A statement drop always lags real life by a few days, and that gap is exactly where the
    # expensive surprises live. A config row counts only while the bank data has NOT reached its
    # date: the moment a statement covering that day loads, the real row takes over and this one
    # drops itself, so it can never double-count.
    manual_txns = []
    for mt in config.get("manual_transactions", []) or []:
        d = pd.Timestamp(mt["date"])
        if d <= bank_max:
            continue
        manual_txns.append({"date": d, "desc": str(mt["desc"]), "amount": float(mt["amount"]),
                            "source": str(mt.get("source", ""))})
    manual_spend_total = sum(r["amount"] for r in manual_txns)
    bank_months = _month_range(bank_start_p, bank_end_p)
    n_bank_months = len(bank_months)

    # A month with no bank rows is a MISSING STATEMENT, not a frugal month -- but averaged into a
    # 25-month denominator it silently drags every headline number down (a month with no statement
    # once reported $125 of spend and $0 income). Detect those months, exclude them from every
    # average/median/rolling figure, and surface them so the gap gets filled instead of hidden.
    bank_rows_by_month = bank.groupby("month").size()
    MIN_ROWS_FOR_COMPLETE = 5
    incomplete_months = {
        m for m in bank_months if int(bank_rows_by_month.get(m, 0)) < MIN_ROWS_FOR_COMPLETE
    }
    # the newest month is partial by recency, not by a missing file -- tracked separately.
    # "Newest" is not the same as "unfinished": once the data actually runs to the last day of the
    # month, that month is complete and belongs in every average and in the momentum comparison.
    current_month = bank_months[-1]
    newest_month_complete = bank_max.normalize() == (bank_max + pd.offsets.MonthEnd(0)).normalize()
    # denominator for "per month" averages: every month that actually has data. Excludes the hole,
    # keeps the current partial month (it has real data, just not all of it yet).
    n_avg_months = max(1, n_bank_months - len(incomplete_months))

    card_min, card_max = cards["Transaction Date"].min(), cards["Transaction Date"].max()

    # ---- Chase transaction alerts: the only near-real-time spending signal ----
    # An alert is an AUTHORISATION, so it lives in the pending lane and never in a
    # completed month. Each card's CSV supersedes its own alerts independently --
    # using one global cutoff would strand alerts on whichever card was exported
    # less recently, which is exactly the card most likely to be missing rows.
    card_max_by_id = cards.groupby("card_id")["Transaction Date"].max().to_dict()
    alert_rows, alerts_superseded = [], 0
    if card_alerts is not None and not card_alerts.empty:
        for _, a in card_alerts.iterrows():
            cid = str(a["card_id"])
            # a fuel pre-auth is a placeholder hold ($1 or $100), not the real
            # amount, and the purchase alert already covers the true charge
            if a.get("kind") == "gas_auth":
                continue
            cutoff = card_max_by_id.get(cid)
            if cutoff is not None and pd.Timestamp(a["date"]).normalize() <= pd.Timestamp(cutoff).normalize():
                alerts_superseded += 1
                continue
            # the parser already stores a credit as a negative amount; sign by kind rather than
            # trusting the stored sign, so a hand-edited CSV row cannot turn a refund into spending
            signed = -abs(float(a["amount"])) if a.get("kind") == "credit" else abs(float(a["amount"]))
            alert_rows.append({
                "alert_id": a["alert_id"],
                "datetime": (None if pd.isna(a["datetime"])
                             else pd.Timestamp(a["datetime"]).isoformat(sep=" ", timespec="minutes")),
                "date": pd.Timestamp(a["date"]).date().isoformat(),
                "card_id": cid,
                "card_name": (config.get("cards") or {}).get(cid, {}).get("name", f"Card {cid}"),
                "merchant": str(a["merchant"]),
                "amount": _round2(signed),
                "kind": str(a.get("kind") or "purchase"),
            })
    alert_rows.sort(key=lambda r: (r["datetime"] or r["date"]), reverse=True)
    alert_spend = sum(r["amount"] for r in alert_rows if r["amount"] > 0)
    alert_credits = -sum(r["amount"] for r in alert_rows if r["amount"] < 0)
    _a_dates = [pd.Timestamp(r["date"]) for r in alert_rows]
    _ing = None
    if card_alerts is not None and not card_alerts.empty and "_ingested_at" in card_alerts:
        _iv = card_alerts["_ingested_at"].dropna()
        if len(_iv):
            _ing = pd.Timestamp(_iv.iloc[0]).isoformat(sep=" ", timespec="minutes")
    card_alert_summary = {
        "ingested_at": _ing,
        # alerts the parser refused to count. Surfaced, never dropped: a discarded
        # alert looks exactly like a month with less spending.
        "review": [{"subject": str(r.get("subject", ""))[:140],
                    "reason": str(r.get("reason", "")),
                    "received": str(r.get("received", ""))[:10]}
                   for r in alert_review],
        "review_count": len(alert_review),
        "rows": alert_rows,
        "count": len(alert_rows),
        "spend": _round2(alert_spend),
        "credits": _round2(alert_credits),
        "net": _round2(alert_spend - alert_credits),
        "superseded": alerts_superseded,
        "since": min(_a_dates).date().isoformat() if _a_dates else None,
        "newest": max(_a_dates).date().isoformat() if _a_dates else None,
        # Every configured card appears, reporting or not. A card silently missing
        # from the list is indistinguishable from a card that spent nothing.
        "cards": _alert_card_roster(config, alert_rows, card_max_by_id, statement_balances),
        "by_card": [
            {"card_id": cid,
             "card_name": (config.get("cards") or {}).get(cid, {}).get("name", f"Card {cid}"),
             "count": sum(1 for r in alert_rows if r["card_id"] == cid),
             "net": _round2(sum(r["amount"] for r in alert_rows if r["card_id"] == cid)),
             "covered_through": (pd.Timestamp(card_max_by_id[cid]).date().isoformat()
                                 if cid in card_max_by_id else None)}
            for cid in sorted({r["card_id"] for r in alert_rows})
        ],
    }
    card_months = _month_range(card_min.to_period("M"), card_max.to_period("M"))

    amazon_min, amazon_max = amazon["order date"].min(), amazon["order date"].max()
    amazon_months = _month_range(amazon_min.to_period("M"), amazon_max.to_period("M"))

    venmo_years = sorted(venmo_r["year"].dropna().unique().tolist())

    coverage = {
        "bank": {"start": str(bank_min.date()), "end": str(bank_max.date()), "months": n_bank_months},
        "cards": {"start": str(card_min.date()), "end": str(card_max.date())},
        "amazon": {"start": str(amazon_min.date()), "end": str(amazon_max.date())},
        "venmo_years": [int(y) for y in venmo_years],
        "email_audits": config.get("email_audits") or {},
    }

    # Open personal loans are balance-sheet assets, not spending and not spendable cash. Publishing
    # the due date beside the receivable keeps a large friend loan from disappearing into net worth.
    open_loans = [
        {
            "name": str(loan.get("name", "Personal loan")),
            "borrower": str(loan.get("borrower", "")),
            "principal": _round2(loan.get("principal", 0)),
            "lent_on": str(loan.get("lent_on", "")),
            "due": str(loan.get("due", "")),
            "note": str(loan.get("note", "")),
        }
        for loan in (config.get("loans_out") or [])
    ]

    # ---- monthly series (accrual, per Sec.5b/5c) ----
    spend_by_month = rc.total_spend_by_month(bank, cards)
    income_by_month = rc.income_by_month(bank)
    salary_by_month = rc.salary_by_month(bank)
    family_by_month = rc.family_by_month(bank)
    investing_by_month = rc.investing_by_month(bank)

    def _at(series, month):
        return float(series.get(month, 0.0))

    # biweekly pay means 2 or 3 paydays land in a month; the count explains a "bad" month that was
    # really just a 2-check month, and a great one that was really a 3-check month
    pay_per_check = float(config["pay"]["per_check_net"])

    monthly_rows = []
    for m in bank_months:
        income = _at(income_by_month, m)
        salary = _at(salary_by_month, m)
        spend = _at(spend_by_month, m)
        family = _at(family_by_month, m)
        saved = income - spend - family
        saved_salary = salary - spend - family
        monthly_rows.append({
            "month": _month_label(m), "income": income, "salary": salary,
            "nonsalary": _round2(income - salary), "spend": spend, "family": family,
            "saved": saved, "rate": (saved / income * 100.0) if income else 0.0,
            # salary-only view: same costs, paycheck alone on the income side
            "saved_salary": saved_salary,
            "rate_salary": (saved_salary / salary * 100.0) if salary else 0.0,
            "n_paychecks": int(round(salary / pay_per_check)) if pay_per_check else 0,
            "incomplete": m in incomplete_months,
            "partial": (m == current_month) and not newest_month_complete,
            "bank_rows": int(bank_rows_by_month.get(m, 0)),
        })

    # Averages run over COMPLETE months only: a missing statement isn't a cheap month, and the
    # newest month is still filling in. Lifetime totals still cover everything actually observed.
    scored = [r for r in monthly_rows if not r["incomplete"] and not r["partial"]]
    n_scored = max(1, len(scored))
    total_income = sum(r["income"] for r in scored)
    total_salary = sum(r["salary"] for r in scored)
    total_spend = sum(r["spend"] for r in scored)
    total_family = sum(r["family"] for r in scored)
    total_saved = total_income - total_spend - total_family
    total_saved_salary = total_salary - total_spend - total_family
    savings_rate_takehome = (total_saved / total_income * 100.0) if total_income else 0.0
    savings_rate_salary = (total_saved_salary / total_salary * 100.0) if total_salary else 0.0
    # Statement-window totals. Post-statement manual activity is tracked separately below rather
    # than quietly changing completed-month averages before matching income has arrived.
    observed_spend = sum(r["spend"] for r in monthly_rows)
    family_all = sum(r["family"] for r in monthly_rows)

    # the individual non-payroll deposits, named -- so an unexplained $3.3k is visible, not netted
    # a raw ACH originator ("XYZ CORP SETTLEMENT") tells you nothing six months later; config supplies the
    # plain-English label and, crucially, whether the money can be expected again
    ns_labels = config.get("nonsalary_income_labels", []) or []

    def _label_nonsalary(desc):
        low = desc.lower()
        for entry in ns_labels:
            if str(entry.get("match", "")).lower() in low:
                return entry
        return {}

    nonsalary_items = []
    for _, r in rc.nonsalary_income_rows(bank).iterrows():
        desc = str(r["Description"]).strip()
        meta = _label_nonsalary(desc)
        nonsalary_items.append({
            "date": pd.Timestamp(r["Date"]).date().isoformat(),
            "month": _month_label(r["month"]),
            "desc": desc,
            "label": meta.get("label") or desc,
            "note": meta.get("note"),
            "recurring": meta.get("recurring"),
            "amount": _round2(r["Amount"]),
        })
    capital_deployed = float(investing_by_month.sum())

    # ---- paycheck (Sec.7 paycheck) ----
    pay = config["pay"]
    ded = pay["deductions_per_check"]
    checks = pay["checks_per_year"]
    taxes_per_check = (
        ded["fed_withholding"] + ded["social_security"] + ded["medicare"]
        + ded.get("state_withholding", 0) + ded.get("local_withholding", 0) + ded.get("state_pfl", 0)
    )
    retirement_per_check = ded["contrib_403b"] + ded["pension"]
    dues_per_check = ded["union_dues"]
    take_home_per_check = pay["per_check_net"]
    gross_per_check = pay["per_check_gross"]

    annual_403b = ded["contrib_403b"] * checks
    annual_457b = 0.0  # no 457(b) contribution present on stub; all headroom unused
    caps = pay["limits_2026"]
    headroom_403b = caps["contrib_403b_cap"] - annual_403b
    headroom_457b = caps["contrib_457b_cap"] - annual_457b

    take_home_mo = take_home_per_check * checks / 12
    gross_mo = pay["annual_salary"] / 12
    auto_retirement_mo = retirement_per_check * checks / 12
    savings_rate_gross = ((total_saved / n_scored + auto_retirement_mo) / gross_mo * 100.0) if gross_mo else 0.0

    paycheck = {
        "gross_per_check": _round2(gross_per_check),
        "take_home_per_check": _round2(take_home_per_check),
        "taxes_per_check": _round2(taxes_per_check),
        "retirement_per_check": _round2(retirement_per_check),
        "dues_per_check": _round2(dues_per_check),
        "checks_per_year": checks,
        "annual": {
            "gross": _round2(pay["annual_salary"]),
            "take_home": _round2(take_home_per_check * checks),
            "taxes": _round2(taxes_per_check * checks),
            "contrib_403b": _round2(annual_403b),
            "pension": _round2(ded["pension"] * checks),
            "union_dues": _round2(dues_per_check * checks),
        },
        "headroom_403b": _round2(headroom_403b),
        "headroom_457b": _round2(headroom_457b),
    }

    # ---- net worth (from data/balances/ CSVs: account balances + Vanguard holdings) ----
    net_worth = _compute_net_worth(config, balances, holdings, card_statements)

    # ---- momentum: trailing 3 months vs the 3 before that (direction, not precision) ----
    # Complete months only, same rule as every other average: a month that is 20 days old reads as
    # a spending-heavy, one-paycheck disaster purely because the rest of it hasn't happened yet.
    momentum = None
    if len(scored) >= 6:
        recent, prior = scored[-3:], scored[-6:-3]
        spend_recent = sum(r["spend"] for r in recent) / 3
        spend_prior = sum(r["spend"] for r in prior) / 3
        rate_recent = sum(r["rate"] for r in recent) / 3
        rate_prior = sum(r["rate"] for r in prior) / 3
        momentum = {
            "months": f"{recent[0]['month']}–{recent[-1]['month']}",
            "spend_recent3": _round2(spend_recent),
            "spend_prior3": _round2(spend_prior),
            "spend_delta_pct": _round2((spend_recent / spend_prior - 1) * 100) if spend_prior else 0,
            "rate_recent3": _round2(rate_recent),
            "rate_prior3": _round2(rate_prior),
            "rate_delta_pts": _round2(rate_recent - rate_prior),
        }

    # ---- summary ----
    summary = {
        "take_home_mo": _round2(take_home_mo),
        "gross_annual": _round2(pay["annual_salary"]),
        "avg_spend_mo": _round2(observed_spend / n_avg_months),
        "saved_mo": _round2(total_saved / n_scored),
        "savings_rate_takehome": _round2(savings_rate_takehome),
        "savings_rate_salary": _round2(savings_rate_salary),
        "saved_mo_salary": _round2(total_saved_salary / n_scored),
        "nonsalary_total": _round2(total_income - total_salary),
        "savings_rate_gross": _round2(savings_rate_gross),
        "auto_retirement_mo": _round2(auto_retirement_mo),
        "capital_deployed": _round2(capital_deployed),
        "family_mo": _round2(family_all / n_avg_months),
        "net_worth": net_worth["net_total"],
        "momentum": momentum,
    }

    # ---- trends ----
    card_purchase_by_month = cards[cards["is_purchase"]].groupby("month")["spend_amount"].sum()
    trend_card_spend = [
        {"month": _month_label(m), "amount": _round2(_at(card_purchase_by_month, m))}
        for m in card_months
    ]
    duo = [{"month": r["month"], "income": _round2(r["income"]), "spend": _round2(r["spend"])} for r in monthly_rows]
    rate_rows = [{"month": r["month"], "rate": round(r["rate"], 1)} for r in monthly_rows]

    # ---- savings history: every month, both income bases, with a 3-mo trend line ----
    # A single month's rate is noisy for reasons that aren't behavioral (2- vs 3-paycheck months,
    # when a card bill clears, a windfall landing). The rolling average is the line to actually read.
    def _roll(vals, i, n=3):
        window = [v for v in vals[max(0, i - n + 1):i + 1] if v is not None]
        return sum(window) / len(window) if window else 0.0

    rates_all = [r["rate"] for r in monthly_rows]
    rates_sal = [r["rate_salary"] for r in monthly_rows]
    cum_saved = cum_saved_sal = 0.0
    savings_history = []
    for i, r in enumerate(monthly_rows):
        cum_saved += r["saved"]
        cum_saved_sal += r["saved_salary"]
        savings_history.append({
            "month": r["month"],
            "income": _round2(r["income"]), "salary": _round2(r["salary"]),
            "nonsalary": r["nonsalary"], "spend": _round2(r["spend"]), "family": _round2(r["family"]),
            "saved": _round2(r["saved"]), "saved_salary": _round2(r["saved_salary"]),
            "rate": round(r["rate"], 1), "rate_salary": round(r["rate_salary"], 1),
            "roll3": round(_roll(rates_all, i), 1), "roll3_salary": round(_roll(rates_sal, i), 1),
            "cum_saved": _round2(cum_saved), "cum_saved_salary": _round2(cum_saved_sal),
            "n_paychecks": r["n_paychecks"],
        })

    _sorted_all = sorted(rates_all)
    _sorted_sal = sorted(rates_sal)
    savings_stats = {
        "median": round(statistics.median(_sorted_all), 1) if _sorted_all else 0,
        "median_salary": round(statistics.median(_sorted_sal), 1) if _sorted_sal else 0,
        "best": max(savings_history, key=lambda r: r["rate_salary"])["month"] if savings_history else None,
        "worst": min(savings_history, key=lambda r: r["rate_salary"])["month"] if savings_history else None,
        "months_negative": sum(1 for r in savings_history if r["saved_salary"] < 0),
        "months_total": len(savings_history),
        "nonsalary_items": nonsalary_items,
    }

    venmo_outflow_by_year = (
        venmo_r[venmo_r["amount"] < 0].assign(out=lambda d: -d["amount"]).groupby("year")["out"].sum()
    )
    yearly_venmo = []
    all_years_span = range(int(min(venmo_years)), int(max(venmo_years)) + 1) if venmo_years else []
    for y in all_years_span:
        val = venmo_outflow_by_year.get(y)
        yearly_venmo.append({"year": int(y), "amount": _round2(val) if val is not None else None})

    person_net = (
        venmo_r.groupby("counterparty")["amount"].sum().apply(lambda a: -a).sort_values(ascending=False)
    )
    by_person = [
        {"name": name, "net_out": _round2(val)}
        for name, val in person_net.items()
        if abs(val) >= 500
    ][:8]

    trends = {
        "card_spend_24mo": trend_card_spend,
        "income_vs_spend": duo,
        "savings_rate_by_month": rate_rows,
        "venmo_yearly_outflow": yearly_venmo,
        "venmo_by_person": by_person,
    }

    # ---- categories ----
    cats_cfg = config["categories"]
    spend_rows = []
    bank_window = bank[(bank["month"] >= bank_start_p) & (bank["month"] <= bank_end_p)]
    for _, r in bank_window[bank_window["bucket"] == rc.BUCKET_DIRECT_SPEND].iterrows():
        spend_rows.append({"description": r["Description"], "amount": r["Amount"], "month": r["month"],
                           "date": r["Date"], "source": "bank"})
    cards_window = cards[(cards["month"] >= bank_start_p) & (cards["month"] <= bank_end_p)]
    for _, r in cards_window[cards_window["is_purchase"]].iterrows():
        spend_rows.append({"description": r["Description"], "amount": r["spend_amount"], "month": r["month"],
                           "date": r["Transaction Date"], "source": r["card_name"]})

    # Manual activity after the newest bank statement remains visible in month_review and
    # data_quality, but is not mixed into historical category averages until the real row lands.

    # ---- Venmo transfers: relabel as what the Venmo statement says the money bought ----
    # The bank only ever writes "Transfer to Venmo", so the whole habit used to sit in one
    # opaque bucket. The Venmo statement names a counterparty on every payment, so split each
    # month's bank transfer across the categories it actually funded, in that month's mix
    # (falling back to the window-wide mix when a month's transfer has no payments to explain
    # it). The bank amount stays authoritative -- money is conserved, only the label is refined.
    venmo_split = config.get("venmo_category_split", {}) or {}
    if venmo_split and venmo_r is not None and not venmo_r.empty:
        v_out = venmo_r[venmo_r["amount"] < 0].assign(out=lambda d: -d["amount"])
        overall_mix = v_out.groupby("entity_tag")["out"].sum()
        month_mix = {m: g.groupby("entity_tag")["out"].sum() for m, g in v_out.groupby("month")}

        def _venmo_mix(month):
            s = month_mix.get(month)
            if s is None or float(s.sum()) <= 0:
                s = overall_mix
            # loan principal and one-off events are tagged but deliberately unmapped, so they
            # drop out here instead of dragging the mix toward a category they never funded
            s = s[s.index.isin(venmo_split)]
            total = float(s.sum())
            return (s / total) if total > 0 else None

        kw = str(config.get("venmo_transfer_desc_match", "Transfer to Venmo")).lower()
        split_rows = []
        for row in spend_rows:
            mix = _venmo_mix(row["month"]) if kw in str(row["description"]).lower() else None
            if mix is None:
                split_rows.append(row)
                continue
            for tag, share in mix.items():
                split_rows.append({**row, "amount": row["amount"] * float(share),
                                   "description": venmo_split[tag]})
        spend_rows = split_rows

    # A statement line cannot tell medication at Target from a lamp at Target. `transaction_notes`
    # lets a single charge be re-filed and explained, matched on date AND amount AND a description
    # fragment so the override can never leak onto another purchase at the same store. Every view
    # resolves a row's category through _cat_of, so an override can never apply in one panel and
    # not another.
    _txn_notes = config.get("transaction_notes") or []

    def _txn_note_for(row):
        if not _txn_notes:
            return None
        desc_l = str(row["description"]).lower()
        d = pd.Timestamp(row["date"]).normalize()
        for n in _txn_notes:
            if str(n.get("match", "")).lower() not in desc_l:
                continue
            if n.get("date") and pd.Timestamp(n["date"]).normalize() != d:
                continue
            if n.get("amount") is not None and abs(float(n["amount"]) - float(row["amount"])) > 0.005:
                continue
            return n
        return None

    def _cat_of(row):
        n = _txn_note_for(row)
        if n and n.get("category"):
            return str(n["category"])
        return _categorize(row["description"], cats_cfg)

    loc_sufs = tuple(config.get("merchant_location_suffixes", []) or [])
    merch_aliases = config.get("merchant_aliases", {}) or {}
    # merchants key on the casefolded name (the CSV and PDF eras capitalize the same store
    # differently); the spelling shown is whichever variant appears on the most transactions
    merchant_display = {}   # casefolded key -> {display spelling: count}
    for row in spend_rows:
        name = _merchant_name(row["description"], loc_sufs, merch_aliases)
        merchant_display.setdefault(name.casefold(), {})[name] = \
            merchant_display.setdefault(name.casefold(), {}).get(name, 0) + 1

    def _merchant_key(description):
        name = _merchant_name(description, loc_sufs, merch_aliases)
        variants = merchant_display.get(name.casefold())
        return max(variants.items(), key=lambda kv: kv[1])[0] if variants else name

    cat_totals = {}
    cat_merchants = {}   # cat_key -> {merchant_name: [sum, count]}
    cat_month = {}       # cat_key -> {month: amount}
    for row in spend_rows:
        key = _cat_of(row)
        cat_totals[key] = cat_totals.get(key, 0.0) + row["amount"]
        m = _merchant_key(row["description"])
        bucket = cat_merchants.setdefault(key, {})
        entry = bucket.setdefault(m, [0.0, 0])
        entry[0] += row["amount"]
        entry[1] += 1
        cm = cat_month.setdefault(key, {})
        cm[row["month"]] = cm.get(row["month"], 0.0) + row["amount"]

    # Display names: generic defaults, overridden per household in config `category_display_names`
    # (the same key also names the `family` line, which is not a keyword category).
    display_names = {
        "rent": "Rent", "groceries": "Groceries", "food_away": "Eating out (restaurants)",
        "snacks": "Corner stores & convenience",
        "pharmacy": "Mail-order pharmacy", "drugstore": "Drugstore & toiletries",
        "healthcare": "Healthcare & dental", "utilities": "Utilities", "transit": "Transit & travel",
        "student_loans": "Student loans", "subscriptions": "Subscriptions", "insurance": "Life insurance",
        "membership": "Memberships", "entertainment": "Movies, books & culture",
        "taxes": "Taxes (prep & payments)", "fees": "Bank & ATM fees",
        "web_hosting": "Web hosting", "cash": "Cash (ATM)", "laundry": "Laundry",
        "shopping": "Shopping", "shopping_costco": "Warehouse club",
        "fostering": "Pet care",
        "events": "One-time events",
        "fitness": "Gym & fitness",
        "fines": "Fines, tickets & collections",
        "venmo": "Venmo transfer (see Venmo tab)",
        "family": "Family support",
        "other": "Other (uncategorized)",
    }
    display_names.update({str(k): str(v) for k, v in (config.get("category_display_names") or {}).items()})
    budgets = config.get("budgets", {}) or {}
    needs_wants = config.get("needs_wants", {}) or {}

    def _class_of(key, tag):
        if key in needs_wants:
            return needs_wants[key]
        return "needs" if tag in ("fixed", "care") else "wants"

    def _top_merchants(key, limit=8):
        items = sorted(cat_merchants.get(key, {}).items(), key=lambda kv: -kv[1][0])
        return [
            {"name": name, "total": _round2(v[0]), "avg_mo": _round2(v[0] / n_avg_months), "count": v[1]}
            for name, v in items[:limit]
        ]

    # last-12-month series per category -- powers the sparklines in the drill-downs
    spark_months = bank_months[-12:]

    def _spark(series_by_month):
        return [
            {"m": _month_label(m), "v": _round2(series_by_month.get(m, 0.0))}
            for m in spark_months
        ]

    categories_list = []
    for key, total in cat_totals.items():
        tag = _category_tag(key, cats_cfg)
        avg_mo = total / n_avg_months
        budget = budgets.get(key)
        categories_list.append({
            "key": key,
            "name": display_names.get(key, key.replace("_", " ").title()),
            "avg_mo": _round2(avg_mo),
            "tag": tag,
            "class": _class_of(key, tag),
            "budget": budget,
            "variance": _round2(avg_mo - budget) if budget is not None else None,
            "merchants": _top_merchants(key),
            "monthly": _spark(cat_month.get(key, {})),
        })
    categories_list.append({
        "key": "family", "name": display_names["family"], "avg_mo": _round2(family_all / n_avg_months),
        "tag": "care", "class": "needs", "budget": None, "variance": None, "merchants": [],
        "monthly": _spark({m: float(family_by_month.get(m, 0.0)) for m in spark_months}),
    })
    categories_list.sort(key=lambda c: -c["avg_mo"])

    # ---- 50/30/20 needs / wants / savings rollup (of take-home) ----
    needs_mo = sum(c["avg_mo"] for c in categories_list if c["class"] == "needs")
    wants_mo = sum(c["avg_mo"] for c in categories_list if c["class"] == "wants")
    savings_residual_mo = take_home_mo - needs_mo - wants_mo
    budget_5030 = {
        "take_home_mo": _round2(take_home_mo),
        "needs_mo": _round2(needs_mo),
        "wants_mo": _round2(wants_mo),
        "savings_mo": _round2(savings_residual_mo),
        "needs_pct": _round2(needs_mo / take_home_mo * 100) if take_home_mo else 0,
        "wants_pct": _round2(wants_mo / take_home_mo * 100) if take_home_mo else 0,
        "savings_pct": _round2(savings_residual_mo / take_home_mo * 100) if take_home_mo else 0,
        "target": {"needs": 50, "wants": 30, "savings": 20},
        "auto_retirement_mo": _round2(auto_retirement_mo),  # pre-tax, on top of take-home
    }

    # ---- sinking funds: categories that arrive in lumpy bursts, with a suggested monthly reserve ----
    # A single big month (a quarterly pharmacy refill, a furnishing order) distorts that month's savings rate. The
    # "set aside" figure is the smoothed monthly average -- reserve it and the lumps stop hurting.
    sinking_funds = []
    for key, months in cat_month.items():
        vals = [months.get(m, 0.0) for m in bank_months]
        nonzero = [v for v in vals if v > 0]
        if len(vals) < 3 or not nonzero:
            continue
        mean = sum(vals) / len(vals)
        if mean < 20:  # too small to bother reserving for
            continue
        peak = max(vals)
        # lumpy = peak month is far above the average, or it only hits some months
        if peak >= 2.5 * mean or len(nonzero) <= max(2, len(vals) // 2):
            name = display_names.get(key, key.replace("_", " ").title())
            sinking_funds.append({
                "key": key, "name": name,
                "set_aside_mo": _round2(mean),
                "peak_month": _round2(peak),
                "months_hit": len(nonzero),
                "months_total": len(vals),
            })
    sinking_funds.sort(key=lambda s: -s["set_aside_mo"])

    # ---- merchant leaderboard: WHO gets the money, by name ----
    # The category view answers "how much on snacks"; this answers "which store". Every direct-spend
    # row is attributed to a normalized storefront, so the near-daily $3 stops aggregate into one
    # visible line instead of hiding inside a category subtotal.
    GRAB_AND_GO_CATS = ("snacks", "food_away")
    merch = {}   # merchant name -> accumulator
    for row in spend_rows:
        key = _cat_of(row)
        if key in ("venmo", "rent"):   # transfers / one fixed landlord: no merchant story to tell
            continue
        name = _merchant_key(row["description"])
        d = pd.to_datetime(row["date"], errors="coerce")
        e = merch.setdefault(name, {
            "name": name, "cat": key, "total": 0.0, "count": 0,
            "first": d, "last": d, "months": {}, "days": set(),
        })
        e["total"] += row["amount"]
        e["count"] += 1
        e["months"][row["month"]] = e["months"].get(row["month"], 0.0) + row["amount"]
        if pd.notna(d):
            if pd.isna(e["first"]) or d < e["first"]:
                e["first"] = d
            if pd.isna(e["last"]) or d > e["last"]:
                e["last"] = d
            e["days"].add(d.date())
        # a merchant can straddle categories (a corner store that also rings up a sandwich) -- label it with
        # the category holding the larger share of its dollars
        if key != e["cat"] and row["amount"] > e["total"] - row["amount"]:
            e["cat"] = key

    merchant_total_all = sum(e["total"] for e in merch.values())

    def _fmt_day(ts):
        return ts.strftime("%b %d, %Y").replace(" 0", " ") if pd.notna(ts) else None

    def _merchant_out(e, include_series=True):
        out = {
            "name": e["name"],
            "cat": e["cat"],
            "cat_name": display_names.get(e["cat"], e["cat"].replace("_", " ").title()),
            "class": _class_of(e["cat"], _category_tag(e["cat"], cats_cfg)),
            "total": _round2(e["total"]),
            "count": e["count"],
            "avg_ticket": _round2(e["total"] / e["count"]) if e["count"] else 0.0,
            "avg_mo": _round2(e["total"] / n_avg_months),
            "visits_mo": round(e["count"] / n_avg_months, 1),
            "share": round(100.0 * e["total"] / merchant_total_all, 2) if merchant_total_all else 0.0,
            "first": _fmt_day(e["first"]),
            "last": _fmt_day(e["last"]),
            "months_active": len(e["months"]),
        }
        if include_series:
            out["monthly"] = _spark(e["months"])
        return out

    # every merchant reaches the table; only the top slice carries a 12-month series (payload size)
    merch_sorted = sorted(merch.values(), key=lambda e: -e["total"])
    top_merchants = [_merchant_out(e, include_series=i < 60) for i, e in enumerate(merch_sorted)]

    # grab-and-go: the deli / bodega / takeout habit, merchant by merchant
    gg = [e for e in merch_sorted if e["cat"] in GRAB_AND_GO_CATS]
    gg_names = {e["name"] for e in gg}
    gg_total = sum(e["total"] for e in gg)
    gg_count = sum(e["count"] for e in gg)
    gg_days = set()
    gg_month = {}
    for e in gg:
        gg_days |= e["days"]
        for m, v in e["months"].items():
            gg_month[m] = gg_month.get(m, 0.0) + v
    window_days = max(1, (bank_max - bank_min).days + 1)

    # ticket-size distribution: the habit's signature is volume of tiny purchases, not big ones.
    # (Deliberately not a day-of-week chart -- the credit union posts weekend swipes on the next
    # business day, so a weekday split of this data measures the bank's calendar, not the person's.)
    ticket_edges = [(0, 3, "Under $3"), (3, 5, "$3–5"), (5, 10, "$5–10"),
                    (10, 20, "$10–20"), (20, float("inf"), "$20+")]
    ticket_buckets = [{"label": lab, "count": 0, "total": 0.0} for _, _, lab in ticket_edges]
    for row in spend_rows:
        if _merchant_key(row["description"]) not in gg_names:
            continue
        amt = row["amount"]
        for i, (lo, hi, _) in enumerate(ticket_edges):
            if lo <= amt < hi:
                ticket_buckets[i]["count"] += 1
                ticket_buckets[i]["total"] += amt
                break
    for b in ticket_buckets:
        b["total"] = _round2(b["total"])
        b["pct"] = round(100.0 * b["count"] / gg_count, 1) if gg_count else 0.0

    # Per-store enrichment for the "Corner Stores" tab: this habit is not one purchase, it is a
    # standing relationship with a handful of shops, so each one gets its own run-rate, its share
    # of the habit, a running cumulative share (how few stores account for most of it), and a
    # direction. The newest month is only used in the trend when it is actually complete --
    # mid-cycle it would read as every store collapsing.
    _last_month_complete = bank_max.normalize() == (bank_max + pd.offsets.MonthEnd(0)).normalize()
    gg_merchants = []
    _cum = 0.0
    for e in gg:
        out = _merchant_out(e)
        series = [p["v"] for p in out.get("monthly", [])]
        if not _last_month_complete:
            series = series[:-1]
        recent3 = sum(series[-3:]) / 3 if len(series) >= 6 else None
        prior3 = sum(series[-6:-3]) / 3 if len(series) >= 6 else None
        out["recent3_mo"] = _round2(recent3) if recent3 is not None else None
        out["prior3_mo"] = _round2(prior3) if prior3 is not None else None
        out["trend_pct"] = (_round2((recent3 / prior3 - 1) * 100)
                            if recent3 is not None and prior3 else None)
        # run-rate over the months this store was actually used, not diluted by the whole window
        out["run_rate_yr"] = _round2(e["total"] / max(1, len(e["months"])) * 12)
        out["pct_of_habit"] = round(100.0 * e["total"] / gg_total, 1) if gg_total else 0.0
        _cum += e["total"]
        out["cum_pct_of_habit"] = round(100.0 * _cum / gg_total, 1) if gg_total else 0.0
        # what one fewer stop a week would save, at this store's own average ticket
        out["one_less_per_week_yr"] = _round2((e["total"] / e["count"]) * 52) if e["count"] else 0.0
        gg_merchants.append(out)

    grab_and_go = {
        "merchants": gg_merchants,
        "total": _round2(gg_total),
        "avg_mo": _round2(gg_total / n_avg_months),
        "annualized": _round2(gg_total / n_avg_months * 12),
        "count": gg_count,
        "visits_mo": round(gg_count / n_avg_months, 1),
        "avg_ticket": _round2(gg_total / gg_count) if gg_count else 0.0,
        "distinct_merchants": len(gg),
        "days_with_a_stop": len(gg_days),
        "window_days": window_days,
        "pct_days": round(100.0 * len(gg_days) / window_days, 1),
        "monthly": _spark(gg_month),
        "ticket_buckets": ticket_buckets,
        "top_share": round(100.0 * gg[0]["total"] / gg_total, 1) if gg and gg_total else 0.0,
        "share_of_spend": round(100.0 * gg_total / observed_spend, 1) if observed_spend else 0.0,
    }

    merchants_block = {
        "top": top_merchants,
        "distinct": len(merch),
        "covered_total": _round2(merchant_total_all),
        "top10_share": round(
            100.0 * sum(e["total"] for e in merch_sorted[:10]) / merchant_total_all, 1
        ) if merchant_total_all else 0.0,
        "grab_and_go": grab_and_go,
        "window_months": n_avg_months,
    }

    # ---- deli decode: read the ticket ladder back into a shopping basket ----
    # A card statement gives one number per visit and no line items. But the tickets are tiny, land
    # on the store's own price grid, and repeat -- so the distribution of distinct amounts is
    # effectively the receipt nobody kept.
    deli_cfg = config.get("deli_decode") or {}
    deli_decode = None
    if deli_cfg.get("merchant"):
        target = deli_cfg["merchant"]
        tax = float(deli_cfg.get("tax_rate", 0.0))
        grid = float(deli_cfg.get("price_grid", 0.25))
        known = deli_cfg.get("known_items", []) or []
        tickets = [row["amount"] for row in spend_rows if _merchant_key(row["description"]) == target]
        if tickets:
            unit = grid * (1 + tax)
            on_grid = [t for t in tickets if abs(round(t / unit) - t / unit) < 0.01]

            def _read(pre):
                """Cheapest combination of known items summing to this pre-tax amount, if any."""
                best = None
                for a_i in range(0, 7):
                    for b_i in range(0, 7):
                        if not (a_i or b_i) or len(known) < 2:
                            continue
                        if abs(a_i * known[0]["price"] + b_i * known[1]["price"] - pre) < 0.005:
                            if best is None or a_i + b_i < best[0] + best[1]:
                                best = (a_i, b_i)
                return best

            ladder, explained, units = {}, 0.0, {k["name"]: 0 for k in known}
            for t in tickets:
                pre = round(t / (1 + tax), 2)
                e = ladder.setdefault(pre, {"pre": pre, "count": 0, "total": 0.0, "reading": None})
                e["count"] += 1
                e["total"] += t
                combo = _read(pre)
                if combo:
                    e["reading"] = " + ".join(
                        f"{n}x {known[i]['name']}" for i, n in enumerate(combo) if n
                    )
                    explained += t
                    for i, n in enumerate(combo):
                        units[known[i]["name"]] += n
            # ---- the signature combo, counted month by month ----
            # The habit has one basket it repeats: the charged price is the items' pre-tax sum plus
            # tax, and it lands on the grid exactly, so it can be counted per visit rather than
            # inferred. Counting it monthly is what makes "was this month lighter than usual?" a
            # question with an answer -- and it separates the two ways a month gets cheaper: fewer
            # trips, or a smaller basket each trip.
            combo = None
            sig = deli_cfg.get("signature_combo") or {}
            price_of = {k["name"]: float(k["price"]) for k in known}
            if sig.get("items") and all(n in price_of for n in sig["items"]):
                pre_combo = round(sum(price_of[n] for n in sig["items"]), 2)
                charged_combo = round(pre_combo * (1 + tax), 2)
                is_combo = [abs(t - charged_combo) < 0.005 for t in tickets]
                n_combo = sum(is_combo)
                combo = {
                    "label": sig.get("label") or " + ".join(sig["items"]),
                    "items": sig["items"],
                    "pre": pre_combo,
                    "charged": charged_combo,
                    "count": n_combo,
                    "total": _round2(n_combo * charged_combo),
                    "share_visits_pct": round(100.0 * n_combo / len(tickets), 1) if tickets else 0.0,
                }

            # ---- per-month series: visits, spend, average ticket, combos ----
            by_m = {}
            for row in spend_rows:
                if _merchant_key(row["description"]) != target:
                    continue
                m = row["month"]
                e = by_m.setdefault(m, {"visits": 0, "spend": 0.0, "combos": 0})
                e["visits"] += 1
                e["spend"] += row["amount"]
                if combo and abs(row["amount"] - combo["charged"]) < 0.005:
                    e["combos"] += 1
            monthly = [
                {"m": _month_label(m), "visits": v["visits"], "spend": _round2(v["spend"]),
                 "combos": v["combos"],
                 "avg_ticket": _round2(v["spend"] / v["visits"]) if v["visits"] else 0.0}
                for m, v in sorted(by_m.items())
            ]
            # "usual" excludes the newest month so the comparison is against history, not itself
            hist = monthly[:-1][-12:]
            latest = monthly[-1] if monthly else None
            usual = None
            if latest and hist:
                n = len(hist)
                usual = {
                    "months": n,
                    "spend": _round2(sum(h["spend"] for h in hist) / n),
                    "visits": round(sum(h["visits"] for h in hist) / n, 1),
                    "combos": round(sum(h["combos"] for h in hist) / n, 1),
                    "avg_ticket": _round2(sum(h["spend"] for h in hist) / max(1, sum(h["visits"] for h in hist))),
                }

            rows_out = sorted(ladder.values(), key=lambda r: -r["total"])
            for r in rows_out:
                r["total"] = _round2(r["total"])
            total_t = sum(tickets)
            deli_decode = {
                "merchant": target, "tax_rate": tax, "price_grid": grid,
                "visits": len(tickets), "total": _round2(total_t),
                "avg_ticket": _round2(total_t / len(tickets)),
                "on_grid_pct": round(100.0 * len(on_grid) / len(tickets), 1),
                "ladder": rows_out[:16],
                "distinct_tickets": len(ladder),
                "explained": _round2(explained),
                "explained_pct": round(100.0 * explained / total_t, 1) if total_t else 0,
                "units": [{"name": k, "count": v, "price": next(i["price"] for i in known if i["name"] == k)}
                          for k, v in units.items() if v],
                "top_unexplained": [
                    {"pre": r["pre"], "count": r["count"], "total": r["total"]}
                    for r in rows_out if not r["reading"]
                ][:6],
                "months": n_avg_months,
                "combo": combo,
                "monthly": monthly[-12:],
                "latest": latest,
                "usual": usual,
            }

    # ---- energy drinks, pooled across channels ----
    # The same product is bought at the corner store, on Amazon in bulk, and occasionally in premium
    # single-serve multipacks. Only pooling them shows what a can actually costs.
    ed_kw = [k.lower() for k in (config.get("energy_drink_keywords") or [])]
    energy = None
    if ed_kw and amazon is not None and not amazon.empty:
        am = amazon[amazon["description"].str.lower().str.contains("|".join(ed_kw), na=False)].copy()
        packs = []
        def _cans(d):
            """Total cans in a listing title. Order matters: '6 Packs of 4 Cans (Pack of 24)' must
            read as 24, not 4 -- taking the first match makes a 24-pack look like $8.74/can."""
            m = re.search(r"(\d+)\s*packs?\s*of\s*(\d+)", d, re.IGNORECASE)
            if m:
                return int(m.group(1)) * int(m.group(2))
            for pat in (r"(\d+)\s*cans", r"pack of (\d+)", r"(\d+)\s*count", r"\((\d+)\s*pack\)"):
                m = re.search(pat, d, re.IGNORECASE)
                if m:
                    return int(m.group(1))
            return None

        for _, r in am.iterrows():
            d = str(r["description"])
            n = _cans(d)
            packs.append({
                "date": str(pd.Timestamp(r["order date"]).date()) if pd.notna(r["order date"]) else None,
                "product": d[:70], "total": _round2(r["line_total"]),
                "cans": n, "per_can": _round2(r["line_total"] / n) if n else None,
            })
        packs.sort(key=lambda p: p["date"] or "")
        priced = [p for p in packs if p["per_can"]]
        # the corner-store can is the first "known item" of the deli decode (config), so the same
        # product is compared across channels without naming a brand in code
        can_name = str((deli_cfg.get("known_items") or [{}])[0].get("name", "")).lower()
        deli_can = None
        if deli_decode and deli_decode["units"]:
            mon = next((u for u in deli_decode["units"] if u["name"].lower() == can_name), None)
            if mon:
                deli_can = _round2(mon["price"] * (1 + deli_decode["tax_rate"]))
        deli_cans = next((u["count"] for u in (deli_decode or {}).get("units", [])
                          if u["name"].lower() == can_name), 0)
        # the standing bulk buy = the price actually paid most often, not a hypothetical
        # warehouse price. The realistic saving is only the deli cans moved to that same product.
        from collections import Counter
        modal = Counter(p["per_can"] for p in priced).most_common(1)
        bulk_price = modal[0][0] if modal else None
        deli_months = (deli_decode or {}).get("months", n_avg_months) or 1
        cans_mo = deli_cans / deli_months
        save_mo = cans_mo * (deli_can - bulk_price) if (deli_can and bulk_price) else 0.0
        energy = {
            "amazon_total": _round2(am["line_total"].sum()),
            "amazon_orders": int(len(am)),
            "amazon_cans": sum(p["cans"] for p in priced),
            "amazon_avg_per_can": _round2(sum(p["total"] for p in priced) / sum(p["cans"] for p in priced))
                                  if priced else None,
            "packs": packs[-12:],
            "best_per_can": min((p["per_can"] for p in priced), default=None),
            "worst_per_can": max((p["per_can"] for p in priced), default=None),
            "bulk_per_can": bulk_price,
            "deli_per_can": deli_can,
            "deli_cans": deli_cans,
            "deli_cans_mo": round(cans_mo, 1),
            "deli_spend_mo": _round2(cans_mo * deli_can) if deli_can else 0.0,
            "premium_per_can": _round2(deli_can - bulk_price) if (deli_can and bulk_price) else None,
            "savings_mo": _round2(save_mo),
            "savings_yr": _round2(save_mo * 12),
        }

    cats_by_key = {c["key"]: c for c in categories_list}

    # ---- rewards: is the points pivot actually paying? ----
    # Spending was restructured onto these cards to earn points, so the dashboard should be able
    # to say what that earned. Everything here comes off the statements' own rewards blocks.
    points_cards, points_total, points_earned = [], 0, 0
    for _, st in (card_statements.iterrows() if card_statements is not None and not card_statements.empty else []):
        p = st.get("points")
        if not p:
            continue
        spend = float(st.get("statement_balance") or 0)
        rate = (p["earned"] / 100.0 / spend * 100) if spend > 0 else 0.0
        idle = [e["label"] for e in p["earn_lines"] if not e["points"]]
        points_cards.append({
            "card_id": st["card_id"], "card_name": st["card_name"],
            "statement_date": st["statement_date"].strftime("%b %d %Y"),
            "previous": p["previous"], "earned": p["earned"], "redeemed": p["redeemed"],
            "total": p["total"], "value_usd": p["value_usd"],
            "earned_value_usd": p["earned_value_usd"],
            "verified": p["printed_total_verified"],
            "statement_spend": _round2(spend),
            "blended_rate": round(rate, 2),
            "earn_lines": [e for e in p["earn_lines"] if e["points"]],
            "idle_lines": idle,
        })
        points_total += p["total"]
        points_earned += p["earned"]

    rewards = None
    if points_cards:
        fre = next((c for c in points_cards if "freedom" in c["card_name"].lower()), None)
        bonus_cap = float(config.get("freedom_bonus_cap_per_quarter", 1500))
        bonus_uplift = float(config.get("freedom_bonus_uplift", 0.04))
        # Did any bonus-category points land on the Freedom? "1% on all purchases" as the only
        # earn line means the quarterly categories were never activated.
        bonus_earned = 0
        if fre:
            bonus_earned = sum(e["points"] for e in fre["earn_lines"] if "1%" not in e["label"])
        quarterly_volume = (fre["statement_spend"] * 3) if fre else 0.0

        # An activation recorded in config beats the statement when it happened after it:
        # the points block can only ever describe the quarter that has already closed.
        # statement_date is a display string ("Aug 19 2026"), so parse before comparing.
        _stmt_ts = pd.to_datetime((fre or {}).get("statement_date"), errors="coerce")
        _act_after_stmt = None
        for _q, _on in sorted((config.get("freedom_bonus_activations") or {}).items()):
            _on_ts = pd.to_datetime(_on, errors="coerce")
            if pd.isna(_on_ts):
                continue
            if pd.isna(_stmt_ts) or _on_ts > _stmt_ts:
                _act_after_stmt = _on_ts.date().isoformat()
        _today = today(config)
        _nq = _today + pd.offsets.QuarterBegin(startingMonth=1)
        _next_quarter_label = f"{_nq.year}Q{(_nq.month - 1)//3 + 1}"
        _next_quarter_start = _nq.date().isoformat()
        capturable = min(bonus_cap, quarterly_volume)
        rewards = {
            "cards": points_cards,
            "total_points": points_total,
            "total_value_usd": round(points_total / 100.0, 2),
            "earned_points": points_earned,
            "earned_value_usd": round(points_earned / 100.0, 2),
            "bonus_activated": bonus_earned > 0 or _act_after_stmt is not None,
            "bonus_activated_on": _act_after_stmt,
            "bonus_next_quarter": _next_quarter_label,
            "bonus_next_quarter_starts": _next_quarter_start,
            "bonus_cap": bonus_cap,
            "quarterly_volume": _round2(quarterly_volume),
            "bonus_missed_per_quarter": _round2(capturable * bonus_uplift),
            "bonus_missed_per_year": _round2(capturable * bonus_uplift * 4),
            # categories the Prime Visa pays extra on that saw no spend at all
            "reroute": [
                {"name": display_names.get(k, k), "avg_mo": _round2(cats_by_key[k]["avg_mo"]),
                 "uplift_pct": u,
                 "gain_yr": _round2(cats_by_key[k]["avg_mo"] * (u / 100.0) * 12)}
                for k, u in (config.get("card_reroute_categories") or {}).items()
                if k in cats_by_key and cats_by_key[k]["avg_mo"] > 5
            ],
        }
        rewards["reroute_gain_yr"] = _round2(sum(r["gain_yr"] for r in rewards["reroute"]))

    # ---- the fixed floor: what life costs before any decision is made ----
    # A monthly total mixes commitments with choices. Separating them answers a different and more
    # useful question -- how much of each paycheck is already spoken for when it lands.
    fixed_keys = config.get("fixed_floor_categories", []) or []
    floor_lines = [
        {"key": k, "name": display_names.get(k, k.replace("_", " ").title()),
         "amount": _round2(next((c["avg_mo"] for c in categories_list if c["key"] == k), 0.0))}
        for k in fixed_keys
    ]
    floor_lines = [l for l in floor_lines if l["amount"] > 1]
    floor_lines.sort(key=lambda l: -l["amount"])
    floor_total = sum(l["amount"] for l in floor_lines)
    avg_spend_for_floor = observed_spend / n_avg_months
    fixed_floor = {
        "lines": floor_lines,
        "total": _round2(floor_total),
        "take_home_mo": _round2(take_home_mo),
        "pct_take_home": round(100.0 * floor_total / take_home_mo, 1) if take_home_mo else 0,
        "checks_to_cover": round(floor_total / pay_per_check, 2) if pay_per_check else 0,
        "discretionary": _round2(avg_spend_for_floor - floor_total),
        "pct_spend_discretionary": round(100.0 * (avg_spend_for_floor - floor_total) / avg_spend_for_floor, 1)
                                   if avg_spend_for_floor else 0,
        "avg_spend": _round2(avg_spend_for_floor),
    }

    # ---- per-paycheck savings: strips the calendar out of the savings rate ----
    # A few months a year carry a third payday. Those months read far better on a monthly rate for
    # a reason that has nothing to do with behaviour. Measuring per paycheck removes it.
    paid_months = [r for r in monthly_rows if r["n_paychecks"]]
    per_check = [
        {"month": r["month"], "checks": r["n_paychecks"],
         "saved_per_check": _round2(r["saved_salary"] / r["n_paychecks"]),
         "pct_of_check": round(100.0 * (r["saved_salary"] / r["n_paychecks"]) / pay_per_check, 1)
                          if pay_per_check else 0}
        for r in paid_months
    ]
    two_chk = [r for r in paid_months if r["n_paychecks"] == 2]
    three_chk = [r for r in paid_months if r["n_paychecks"] >= 3]
    paycheck_view = {
        "series": per_check,
        "mean_saved_per_check": _round2(sum(p["saved_per_check"] for p in per_check) / max(1, len(per_check))),
        "check_net": _round2(pay_per_check),
        "two_check_months": len(two_chk),
        "three_check_months": len(three_chk),
        "two_check_rate": round(sum(r["rate_salary"] for r in two_chk) / max(1, len(two_chk)), 1),
        "three_check_rate": round(sum(r["rate_salary"] for r in three_chk) / max(1, len(three_chk)), 1),
        "calendar_bonus_pts": round(
            sum(r["rate_salary"] for r in three_chk) / max(1, len(three_chk))
            - sum(r["rate_salary"] for r in two_chk) / max(1, len(two_chk)), 1),
    }

    # ---- 457(b)/403(b) deferral arithmetic ----
    # Pure tax arithmetic from the paystub, not a recommendation: a dollar deferred is a dollar
    # off taxable wages, and the observed withholding rate says what that dollar is worth today.
    ded = pay.get("deductions_per_check", {})
    taxable_wages = (pay["per_check_gross"] - ded.get("contrib_403b", 0) - ded.get("pension", 0)
                     - ded.get("social_security", 0) - ded.get("medicare", 0))
    income_tax = ded.get("fed_withholding", 0) + ded.get("state_withholding", 0) + ded.get("local_withholding", 0)
    eff_rate = (income_tax / taxable_wages) if taxable_wages else 0.0
    cap457 = pay.get("limits_2026", {}).get("contrib_457b_cap", 0)
    deferral_math = {
        "effective_income_tax_rate": round(eff_rate * 100, 1),
        "taxable_wages_per_check": _round2(taxable_wages),
        "income_tax_per_check": _round2(income_tax),
        "cap_457b": cap457,
        "scenarios": [
            {"per_check": a, "annual": a * pay["checks_per_year"],
             "tax_saved": _round2(a * pay["checks_per_year"] * eff_rate)}
            for a in (100, 200, 400)
        ],
        "full_cap_tax_saved": _round2(cap457 * eff_rate),
        "surplus_mo": _round2(total_saved_salary / n_scored),
    }

    # ---- eras: did the card pivot change the spending, or just the rails? ----
    # The obvious read (post-pivot months are ~$1,000/mo higher) is wrong twice over: the rise began
    # months BEFORE the pivot, and the post-pivot months carry one-time furnishing and cat setup.
    # Both corrections are computed, not asserted.
    pivot = config.get("events", {}).get("card_points_pivot")
    era_analysis = None
    if pivot:
        pivot_p = pd.Timestamp(str(pivot)).to_period("M")
        onetime_cfg = config.get("one_time_costs", {}) or {}
        rows_by_month = {r["month"]: r for r in monthly_rows}
        complete_bank_months = [
            m for m in bank_months if m not in incomplete_months and m != current_month
        ]

        def _era(months, label):
            rs = [rows_by_month[_month_label(m)] for m in months
                  if _month_label(m) in rows_by_month and rows_by_month[_month_label(m)]["n_paychecks"]]
            if not rs:
                return None
            spends = [r["spend"] for r in rs]
            onetime = sum(float(onetime_cfg.get(r["month"], 0.0)) for r in rs)
            return {
                "label": label, "months": len(rs),
                "first": rs[0]["month"], "last": rs[-1]["month"],
                "spend_avg": _round2(sum(spends) / len(spends)),
                "spend_median": _round2(statistics.median(spends)),
                "saved_avg": _round2(sum(r["saved_salary"] for r in rs) / len(rs)),
                "rate_avg": round(sum(r["rate_salary"] for r in rs) / len(rs), 1),
                "onetime": _round2(onetime),
                "underlying_avg": _round2((sum(spends) - onetime) / len(rs)),
            }

        # category-level decomposition: baseline year vs the most recent quarter. This is what
        # answers "where did the extra money actually go" -- the era totals alone can't.
        base_ms = complete_bank_months[:12]
        recent_ms = complete_bank_months[-3:]
        era_cats = []
        for key, months in cat_month.items():
            a = sum(months.get(m, 0.0) for m in base_ms) / max(1, len(base_ms))
            bb = sum(months.get(m, 0.0) for m in recent_ms) / max(1, len(recent_ms))
            if abs(bb - a) < 12:
                continue
            era_cats.append({
                "key": key,
                "name": display_names.get(key, key.replace("_", " ").title()),
                "baseline": _round2(a), "recent": _round2(bb), "delta": _round2(bb - a),
                # furnishing/one-off buckets inflate the recent quarter and will fall away
                "transient": key in ("shopping", "shopping_costco", "healthcare", "cash"),
            })
        era_cats.sort(key=lambda c: -c["delta"])
        transient_delta = sum(c["delta"] for c in era_cats if c["transient"] and c["delta"] > 0)
        structural_delta = sum(c["delta"] for c in era_cats if not c["transient"])

        pre_all = [m for m in complete_bank_months if m < pivot_p]
        post = [m for m in complete_bank_months if m >= pivot_p]
        recent_pre = pre_all[-3:] if len(pre_all) >= 3 else pre_all
        baseline = pre_all[:12]
        eras = [e for e in (_era(baseline, "First year (baseline)"),
                            _era(recent_pre, "3 months before the pivot"),
                            _era(post, "Since the pivot")) if e]
        if len(eras) >= 2:
            b, rp, po = eras[0], eras[-2], eras[-1]
            era_analysis = {
                "pivot_month": _month_label(pivot_p),
                "pivot_date": str(pivot),
                "eras": eras,
                "headline_delta": _round2(po["spend_avg"] - rp["spend_avg"]),
                "underlying_delta": _round2(po["underlying_avg"] - rp["spend_avg"]),
                "vs_baseline": _round2(po["underlying_avg"] - b["spend_avg"]),
                "rise_predates_pivot": rp["spend_avg"] > b["spend_avg"] * 1.1,
                "categories": era_cats,
                "baseline_label": f"{_month_label(base_ms[0])}–{_month_label(base_ms[-1])}",
                "recent_label": f"{_month_label(recent_ms[0])}–{_month_label(recent_ms[-1])}",
                "transient_delta": _round2(transient_delta),
                "structural_delta": _round2(structural_delta),
            }

    # ---- data quality: what this dashboard is actually standing on ----
    # Every number here is only as good as the files behind it, so the provenance is published
    # rather than assumed: which sources, what window each covers, where the holes are.
    def _src_rows(df, col, name_col="_source_file"):
        out = []
        if df is None or df.empty or name_col not in df.columns:
            return out
        for f, g in df.groupby(name_col):
            d = pd.to_datetime(g[col], errors="coerce")
            out.append({"file": str(f), "rows": int(len(g)),
                        "start": None if d.isna().all() else str(d.min().date()),
                        "end": None if d.isna().all() else str(d.max().date())})
        return sorted(out, key=lambda r: (r["start"] or ""))

    verified_newest = max(bank_max, card_max)
    recorded_newest = max([verified_newest] + [r["date"] for r in manual_txns]
                          + [pd.Timestamp(r["date"]) for r in alert_rows])
    stale_days = int((today(config).normalize() - verified_newest.normalize()).days)
    data_quality = {
        "missing_months": [_month_label(m) for m in sorted(incomplete_months)],
        "window_months": n_bank_months,
        "avg_months": n_avg_months,
        "scored_months": n_scored,
        "current_month": _month_label(current_month),
        "newest_transaction": recorded_newest.date().isoformat(),
        "newest_verified_transaction": verified_newest.date().isoformat(),
        "stale_days": stale_days,
        "pending_manual_count": len(manual_txns),
        "pending_manual_total": _round2(manual_spend_total),
        "pending_manual_as_of": (max(r["date"] for r in manual_txns).date().isoformat()
                                  if manual_txns else None),
        "bank_sources": _src_rows(bank, "Date"),
        "card_sources": _src_rows(cards, "Transaction Date"),
        "rows": {
            "bank": int(len(bank)), "cards": int(len(cards)),
            "amazon": int(len(amazon)) if amazon is not None else 0,
            "venmo": int(len(venmo)) if venmo is not None else 0,
            "chewy": int(len(loaded.get("chewy"))) if loaded.get("chewy") is not None and not loaded["chewy"].empty else 0,
        },
        "balances_as_of": net_worth.get("as_of"),
    }

    # ---- this month in review: what changed, and is it structural or one-off? ----
    # Every month here is lumpy (2- vs 3-paycheck, a furnishing burst, a card bill's timing), so a
    # bare total says little. This compares the current month against the trailing average of the
    # months before it, category by category, and projects the rest of the month at the observed
    # run-rate -- because the newest month is nearly always partial.
    cur_m = bank_months[-1]
    cur_row = monthly_rows[-1]
    trailing = monthly_rows[-13:-1] if len(monthly_rows) > 12 else monthly_rows[:-1]
    n_trail = max(1, len(trailing))
    month_end = (cur_m.to_timestamp() + pd.offsets.MonthEnd(0)).normalize()
    days_elapsed = max(1, (bank_max.normalize() - cur_m.to_timestamp()).days + 1)
    days_in_month = month_end.day
    days_left = max(0, days_in_month - days_elapsed)

    cat_deltas = []
    for key, months in cat_month.items():
        cur = months.get(cur_m, 0.0)
        prior_vals = [months.get(m, 0.0) for m in bank_months[-13:-1]] or [0.0]
        avg = sum(prior_vals) / len(prior_vals)
        if abs(cur - avg) < 15 and cur < 50:
            continue
        cat_deltas.append({
            "key": key, "name": display_names.get(key, key.replace("_", " ").title()),
            "amount": _round2(cur), "avg": _round2(avg), "delta": _round2(cur - avg),
        })
    cat_deltas.sort(key=lambda c: -abs(c["delta"]))

    # Exact merchant-level drivers behind the category deltas. The category table answers where
    # the month ran hot; this block answers the natural follow-up: "what did I actually buy?"
    # Group Amazon marketplace postings together because each card charge has an opaque reference
    # code, then expose the itemized order-history rows separately below.
    hot_keys = {c["key"] for c in cat_deltas if c["delta"] > 0 and c["key"] != "rent"}
    purchase_groups_acc = {}
    for row in spend_rows:
        if row["month"] != cur_m:
            continue
        key = _cat_of(row)
        if key not in hot_keys:
            continue
        desc = str(row["description"])
        if key == "shopping" and "amazon" in desc.lower():
            merchant = "Amazon purchases"
        else:
            merchant = _merchant_key(desc)
        g = purchase_groups_acc.setdefault((key, merchant), {"total": 0.0, "count": 0})
        g["total"] += float(row["amount"])
        g["count"] += 1
    purchase_groups = [
        {
            "merchant": merchant,
            "category": display_names.get(key, key.replace("_", " ").title()),
            "total": _round2(values["total"]),
            "count": values["count"],
        }
        for (key, merchant), values in purchase_groups_acc.items()
    ]
    purchase_groups.sort(key=lambda row: -row["total"])

    amazon_month = amazon[amazon["order date"].dt.to_period("M") == cur_m].copy()
    amazon_month_items = [
        {
            "date": pd.Timestamp(row["order date"]).date().isoformat(),
            "description": str(row["description"]),
            "amount": _round2(row["line_total"]),
        }
        for _, row in amazon_month.sort_values("line_total", ascending=False).head(10).iterrows()
    ]
    # ---- what each hot category was actually made of ----
    # The variance table says a category ran hot; this says what was in it. Every charge in the
    # month is listed, and where a receipt exists the charge opens into its line items: Amazon
    # order history is matched back onto the card charge it paid for, and merchants whose contents
    # only exist in email carry a note from `merchant_notes`. Anything with no receipt anywhere
    # (an in-store swipe) says so instead of pretending, because a drill-down that quietly omits
    # the unexplainable half is worse than one that names it.
    month_purchases = []
    if cat_deltas:
        notes_cfg = {k.lower(): v for k, v in (config.get("merchant_notes") or {}).items()}

        # Amazon: build this month's orders, then match each to the card charge that paid it.
        # Item prices exclude tax and shipping, so a charge is allowed to run a little above its
        # order; the window is tight enough that two orders never claim the same charge.
        az_orders = []
        az_month = amazon[amazon["order date"].dt.to_period("M") == cur_m]
        for oid, grp in az_month.groupby("order id"):
            az_orders.append({
                "order": str(oid),
                "date": grp["order date"].max(),
                "subtotal": float(grp["line_total"].sum()),
                "items": [{"description": str(r["description"]), "amount": _round2(r["line_total"])}
                          for _, r in grp.sort_values("line_total", ascending=False).iterrows()],
            })
        az_orders.sort(key=lambda o: o["date"])

        def _claim_amazon(charge_amt, charge_date):
            best, best_gap = None, None
            for o in az_orders:
                if o.get("_used"):
                    continue
                lo, hi = o["subtotal"] * 0.999, o["subtotal"] * 1.12 + 0.75
                if not (lo <= charge_amt <= hi):
                    continue
                gap = abs((pd.Timestamp(charge_date) - o["date"]).days)
                if gap > 6:
                    continue
                if best is None or gap < best_gap:
                    best, best_gap = o, gap
            if best is not None:
                best["_used"] = True
            return best

        for c in cat_deltas:
            if c["delta"] <= 0 or c["key"] in ("rent", "family"):
                continue
            rows = [r for r in spend_rows
                    if r["month"] == cur_m and _cat_of(r) == c["key"]]
            if not rows:
                continue
            charges = []
            for r in sorted(rows, key=lambda r: (r["date"], -r["amount"])):
                merchant = _merchant_key(r["description"])
                entry = {
                    "date": pd.Timestamp(r["date"]).date().isoformat(),
                    "merchant": merchant,
                    "amount": _round2(r["amount"]),
                    "source": str(r.get("source", "")),
                    "items": [],
                    # a note pinned to this exact charge beats the merchant-wide one: it is the
                    # difference between "Target emails no receipt" and "that one was medication"
                    "note": ((_txn_note_for(r) or {}).get("note")
                             or notes_cfg.get(merchant.lower(), "")),
                }
                if "amazon" in str(r["description"]).lower() and "prime" not in str(r["description"]).lower():
                    # the merchant cleaner leaves Amazon's opaque posting code as the "name"
                    # ("5678G6N50"); the store is the useful label, the code only the receipt id
                    entry["merchant"] = "Amazon"
                    entry["ref"] = str(r["description"]).split("*")[-1].strip()
                    o = _claim_amazon(float(r["amount"]), r["date"])
                    if o:
                        entry["items"] = o["items"]
                        entry["order"] = o["order"]
                _n = _txn_note_for(r)
                if _n and _n.get("category"):
                    entry["refiled_from"] = _categorize(r["description"], cats_cfg)
                # a basket recalled in part is not the same claim as one recalled in full, and the
                # panel should not let the two look alike
                if _n and _n.get("partial"):
                    entry["partial"] = True
                charges.append(entry)
            leftover = [{"description": i["description"], "amount": i["amount"]}
                        for o in az_orders if not o.get("_used") for i in o["items"]] \
                if c["key"] == "shopping" else []
            # A charge re-filed OUT of this category would otherwise just vanish from it, leaving
            # the drill-down short of the card total with no explanation. Leave the breadcrumb.
            moved_out = []
            for r2 in spend_rows:
                if r2["month"] != cur_m:
                    continue
                nn = _txn_note_for(r2)
                if not (nn and nn.get("category")):
                    continue
                if _categorize(r2["description"], cats_cfg) != c["key"] or nn["category"] == c["key"]:
                    continue
                moved_out.append({
                    "date": pd.Timestamp(r2["date"]).date().isoformat(),
                    "merchant": _merchant_key(r2["description"]),
                    "amount": _round2(r2["amount"]),
                    "to": display_names.get(nn["category"], str(nn["category"]).title()),
                    "note": nn.get("note", ""),
                })
            month_purchases.append({
                "key": c["key"], "name": c["name"],
                "total": _round2(sum(x["amount"] for x in charges)),
                "count": len(charges),
                "itemized": sum(1 for x in charges if x["items"]),
                "charges": charges,
                "unmatched_items": leftover,
                "moved_out": moved_out,
            })

    post_period_manual = [
        {
            "date": row["date"].date().isoformat(),
            "description": row["desc"],
            "amount": _round2(row["amount"]),
            "source": row["source"],
        }
        for row in manual_txns
    ]

    # rent is a fixed lump that lands whole on day 1 -- projecting it forward would double-count it
    rent_cur = cat_month.get("rent", {}).get(cur_m, 0.0)
    daily_var = max(0.0, cur_row["spend"] - rent_cur) / days_elapsed
    projected_spend = cur_row["spend"] + daily_var * days_left
    # a biweekly cycle puts 2 or 3 paydays in a month; project the rest from the last observed payday
    pay_dates = sorted(pd.to_datetime(
        bank[(bank["bucket"] == "INCOME") & bank["is_salary"]]["Date"]).dt.normalize().unique())
    projected_checks = cur_row["n_paychecks"]
    if pay_dates:
        nxt = pd.Timestamp(pay_dates[-1]) + pd.Timedelta(days=14)
        while nxt <= month_end:
            projected_checks += 1
            nxt += pd.Timedelta(days=14)
    projected_salary = projected_checks * pay_per_check
    projected_saved = projected_salary - projected_spend - cur_row["family"]

    month_review = {
        "month": cur_row["month"],
        "partial": days_left > 0,
        "days_elapsed": days_elapsed, "days_in_month": days_in_month, "days_left": days_left,
        "as_of": bank_max.date().isoformat(),
        "salary": _round2(cur_row["salary"]), "nonsalary": cur_row["nonsalary"],
        "income": _round2(cur_row["income"]), "spend": _round2(cur_row["spend"]),
        "family": _round2(cur_row["family"]),
        "saved": _round2(cur_row["saved"]), "rate": round(cur_row["rate"], 1),
        "saved_salary": _round2(cur_row["saved_salary"]), "rate_salary": round(cur_row["rate_salary"], 1),
        "checks_landed": cur_row["n_paychecks"], "checks_expected": projected_checks,
        "projected_spend": _round2(projected_spend),
        "projected_salary": _round2(projected_salary),
        "projected_saved": _round2(projected_saved),
        "projected_rate": round(projected_saved / projected_salary * 100, 1) if projected_salary else 0,
        "daily_var_spend": _round2(daily_var),
        "trailing_spend_avg": _round2(sum(r["spend"] for r in trailing) / n_trail),
        "trailing_rate_salary_avg": round(sum(r["rate_salary"] for r in trailing) / n_trail, 1),
        "trailing_months": n_trail,
        "cat_deltas": cat_deltas[:12],
        "purchase_groups": purchase_groups[:12],
        "month_purchases": month_purchases,
        "amazon_item_subtotal": _round2(amazon_month["line_total"].sum()),
        "amazon_items": amazon_month_items,
        "post_period_manual": post_period_manual,
        "nonsalary_items": [i for i in nonsalary_items if i["month"] == cur_row["month"]],
    }

    # venmo decode (current bank window, itemized -- informational, see Sec.5d)
    venmo_window = venmo_r[(venmo_r["Datetime"] >= bank_min) & (venmo_r["Datetime"] <= bank_max)]
    venmo_out_window = venmo_window[venmo_window["amount"] < 0].copy()
    venmo_out_window["out"] = -venmo_out_window["amount"]
    venmo_tag_totals = venmo_out_window.groupby("entity_tag")["out"].sum()
    fruit_runs = int((venmo_out_window["entity_tag"] == "fruit").sum())
    venmo_decode = {
        "fruit": _round2(venmo_tag_totals.get("fruit", 0.0)),
        "fruit_runs": fruit_runs,
        "movies": _round2(venmo_tag_totals.get("movies", 0.0)),
        "shared_meals": _round2(venmo_tag_totals.get("other", 0.0)),
        "vendor": config["entities"]["fruit_vendor"],
    }

    # ---- food ----
    cooking_started = pd.Timestamp(str(config["events"]["cooking_started"]))
    food_rows = []
    groceries_by_month, eating_out_by_month = {}, {}
    for row in spend_rows:
        key = _cat_of(row)
        if key == "groceries":
            groceries_by_month[row["month"]] = groceries_by_month.get(row["month"], 0.0) + row["amount"]
        elif key == "food_away":
            eating_out_by_month[row["month"]] = eating_out_by_month.get(row["month"], 0.0) + row["amount"]
    before_groc, before_out, after_groc, after_out, n_before, n_after = 0.0, 0.0, 0.0, 0.0, 0, 0
    for m in bank_months:
        g = groceries_by_month.get(m, 0.0)
        o = eating_out_by_month.get(m, 0.0)
        food_rows.append({"month": _month_label(m), "groceries": _round2(g), "eating_out": _round2(o)})
        # Keep the partial current month visible in the chart, but do not let a
        # 20-day period masquerade as a full post-cooking month in the comparison.
        if m in incomplete_months or m == current_month:
            continue
        month_start = m.to_timestamp()
        if month_start < cooking_started.to_period("M").to_timestamp():
            before_groc += g; before_out += o; n_before += 1
        else:
            after_groc += g; after_out += o; n_after += 1
    food = {
        "monthly": food_rows,
        "before": {
            "groceries_mo": _round2(before_groc / n_before) if n_before else 0,
            "eating_out_mo": _round2(before_out / n_before) if n_before else 0,
        },
        "after": {
            "groceries_mo": _round2(after_groc / n_after) if n_after else 0,
            "eating_out_mo": _round2(after_out / n_after) if n_after else 0,
        },
        "cooking_started": str(config["events"]["cooking_started"]),
    }

    # ---- recurring (subscriptions + fixed bills, driven by config keywords) ----
    # Uses full available history (not just the bank window) so annually-billed
    # items (e.g. Amazon Prime) are identified and monthly-equivalenced correctly.
    # Each transaction is claimed by the FIRST keyword that matches it (config order), so
    # overlapping keywords ("lakeview power" / "lakeview", "granite state servicing" / "granite")
    # can never count the same charge twice.
    all_rows = []
    for _, r in bank[bank["bucket"] == rc.BUCKET_DIRECT_SPEND].iterrows():
        all_rows.append({"description": r["Description"], "amount": r["Amount"], "date": r["Date"],
                         "source": "bank"})
    for _, r in cards[cards["is_purchase"]].iterrows():
        all_rows.append({"description": r["Description"], "amount": r["spend_amount"],
                         "date": r["Transaction Date"], "source": "card"})

    data_end = max(bank_max, card_max)

    def _cadence_label(days):
        if days <= 10:
            return "weekly"
        if days <= 20:
            return "biweekly"
        if days <= 45:
            return "monthly"
        if days <= 135:
            return "quarterly"
        if days <= 430:
            return "annual"
        return "irregular"

    def _price_step(matches):
        """Detect a sustained price increase: the latest price held for >=2 charges, and the
        price before it also held for >=2 charges (so variable bills like electricity never trigger)."""
        amts = [round(m["amount"], 2) for m in matches]
        if len(amts) < 4:
            return None

        def _near(a, b):
            return abs(a - b) <= max(0.02 * b, 0.02)

        last = amts[-1]
        run = 0
        for a in reversed(amts):
            if _near(a, last):
                run += 1
            else:
                break
        if run < 2 or run >= len(amts):
            return None
        prev = amts[-run - 1]
        prev_run = 0
        for a in reversed(amts[:-run]):
            if _near(a, prev):
                prev_run += 1
            else:
                break
        if prev_run < 2 or last <= prev * 1.02 + 0.01:
            return None
        return {
            "from": _round2(prev),
            "to": _round2(last),
            "pct": _round2((last / prev - 1) * 100),
            "since": str(matches[len(amts) - run]["date"].date()),
        }

    recurring = []
    for cat_key, cat in cats_cfg.items():
        if cat["tag"] != "fixed":
            continue
        kws = [k.lower() for k in cat["keywords"]]
        groups = {}
        for r in all_rows:
            desc_l = str(r["description"]).lower()
            for kw in kws:
                if kw in desc_l:
                    groups.setdefault(kw, []).append(r)
                    break
        for kw in kws:
            matches = sorted(groups.get(kw, []), key=lambda r: r["date"])
            if not matches:
                continue
            latest = matches[-1]
            n = len(matches)
            if n >= 2:
                gaps = [(matches[i + 1]["date"] - matches[i]["date"]).days for i in range(n - 1)]
                gaps = [g for g in gaps if g > 0] or [30.44]
                med_gap = statistics.median(gaps)
                # A biller that switches billing rhythm keeps its old median gap for years,
                # so read the cadence off the newest interval when that interval has clearly
                # broken step: a subscription that moves from monthly to an annual renewal would
                # otherwise have its renewal priced as a monthly bill by the stale median.
                if gaps[-1] > 2.5 * med_gap:
                    # Only one charge has landed at the new rhythm, so it is the whole
                    # evidence -- averaging it against the old monthly prices would price
                    # the annual renewal as if it were still a monthly bill.
                    med_gap = float(gaps[-1])
                    typical = latest["amount"]
                else:
                    # Pricing off the single latest charge is fragile the other way: a one-off
                    # fee posting after the real bill hijacks the line (a rent processor that
                    # bills the rent on the 7th and a small fee on the 10th would read as
                    # "rent is $131/mo"). Take the median charge inside the trailing 3
                    # cadence periods -- outlier-resistant, and still follows a real price
                    # change within 3 cycles.
                    window_start = latest["date"] - pd.Timedelta(days=3 * med_gap)
                    recent_amts = [m["amount"] for m in matches if m["date"] >= window_start]
                    typical = statistics.median(recent_amts) if recent_amts else latest["amount"]
                avg_mo = typical * (30.44 / med_gap)
            else:
                med_gap = 30.44
                avg_mo = latest["amount"]  # single observation; assume monthly until proven otherwise
            # active = a fresh charge is still landing on its usual rhythm; otherwise it's an
            # ended service (old rent processor, superseded biller) and must not inflate totals
            days_since = (data_end - latest["date"]).days
            active = days_since <= max(2.2 * med_gap, 75)
            recurring.append(
                {
                    "name": kw.title(),
                    "category": cat_key,
                    "avg_mo": _round2(avg_mo),
                    "latest_amount": _round2(latest["amount"]),
                    "latest_date": str(latest["date"].date()),
                    "count": n,
                    "cadence": _cadence_label(med_gap) if n >= 2 else "single charge",
                    "active": bool(active),
                    "confirmed": n >= 2,  # one observation isn't proof it recurs
                    "price_change": _price_step(matches) if active else None,
                    # where the money leaves from decides whether a future charge is cash owed
                    # in the next 30 days (bank) or spend that lands on a later card statement
                    "pays_from": ("card" if sum(1 for m in matches if m.get("source") == "card")
                                  > len(matches) / 2 else "bank"),
                    # the same cadence that priced the line also says when the next one lands
                    "next_due": str((latest["date"] + pd.Timedelta(days=med_gap)).date()),
                    "cadence_days": round(float(med_gap), 1),
                }
            )
    recurring.sort(key=lambda r: (not r["active"], -r["avg_mo"]))
    recurring_active_mo = sum(r["avg_mo"] for r in recurring if r["active"] and r["confirmed"])

    # ---- the next 30 days: what is already committed, and does the cash cover it ----
    # Everything else on this dashboard looks backward (what a month cost) or hypothetical (what
    # happens if the paycheck stops). Neither answers the question that actually decides whether a
    # month goes smoothly: what is already owed before any new decision is made, when does it land,
    # and is there enough cash on the day it lands. Every line here is committed -- a statement that
    # has already closed, or a bill that has been charging on the same rhythm for months.
    #
    # Card-paid subscriptions are deliberately NOT counted as cash outflows: they land on a
    # statement that closes later, so counting them here would charge the same dollar twice, once
    # as a future swipe and once inside the statement balance already listed.
    forward_30 = None
    if net_worth.get("assets_total"):
        start = bank_max.normalize() + pd.Timedelta(days=1)
        end = start + pd.Timedelta(days=29)
        liquid = float(net_worth.get("by_tax", {}).get("cash", 0.0))
        card_now = sum(l["balance"] for l in net_worth.get("liabilities", [])
                       if l.get("source_type") == "credit_card")
        ledger = []

        # committed: each card's closed statement, due on its printed due date
        for l in net_worth.get("liabilities", []):
            if l.get("source_type") != "credit_card" or not l.get("due_date"):
                continue
            d = pd.Timestamp(l["due_date"])
            if start <= d <= end:
                ledger.append({"date": str(d.date()), "label": l["name"],
                               "detail": f"statement closed {l.get('statement_date', '?')}",
                               "amount": -_round2(float(l.get("statement_balance") or l["balance"])),
                               "kind": "card"})

        # committed: bank-paid recurring bills, projected one cadence past their last charge
        for r in recurring:
            if not (r["active"] and r["confirmed"] and r.get("next_due") and r.get("pays_from") == "bank"):
                continue
            d = pd.Timestamp(r["next_due"])
            # A projection made from the last charge can already be in the past by the time the
            # statements arrive (a July gas bill projects to late August). Roll it on by
            # its own cadence until it reaches the window, so a real monthly bill is not dropped
            # just because the export lagged it.
            gap = max(1.0, float(r.get("cadence_days") or 30.44))
            guard = 0
            while d < start and guard < 60:
                d = d + pd.Timedelta(days=gap)
                guard += 1
            if start <= d <= end:
                ledger.append({"date": str(d.date()), "label": r["name"],
                               "detail": f"{r['cadence']} · last was ${r['latest_amount']:,.2f}",
                               "amount": -_round2(r["latest_amount"]), "kind": "bill"})

        # already spent, just not inside the reconciled window yet: a confirmed payment dated
        # after the newest statement is deliberately kept out of the month's averages, but it is
        # real cash already gone, so the forward view is exactly where it belongs
        for r in manual_txns:
            d = pd.Timestamp(r["date"]).normalize()
            if start <= d <= end:
                ledger.append({"date": str(d.date()), "label": r["desc"],
                               "detail": "already paid · not yet on a statement",
                               "amount": -_round2(r["amount"]), "kind": "manual"})

        # expected: payroll keeps its observed rhythm
        pay_rows = bank[(bank["bucket"] == "INCOME") & bank["is_salary"]]
        if not pay_rows.empty:
            last_pay = pay_rows["Date"].max().normalize()
            step = int(round(365.0 / max(1, int(config["pay"]["checks_per_year"]))))
            nxt = last_pay + pd.Timedelta(days=step)
            while nxt <= end:
                if nxt >= start:
                    ledger.append({"date": str(nxt.date()), "label": "Paycheck",
                                   "detail": "same rhythm as your last one",
                                   "amount": _round2(pay_per_check), "kind": "income"})
                nxt = nxt + pd.Timedelta(days=step)

        ledger.sort(key=lambda x: (x["date"], -x["amount"]))
        # start from cash the cards have no claim on -- treating gross cash as runway is the
        # single easiest way to feel richer than you are
        running = liquid - card_now
        low = running
        for row in ledger:
            running = _round2(running + row["amount"])
            row["balance"] = running
            low = min(low, running)
        committed_out = sum(-r["amount"] for r in ledger if r["amount"] < 0)
        expected_in = sum(r["amount"] for r in ledger if r["amount"] > 0)
        forward_30 = {
            "start": str(start.date()), "end": str(end.date()),
            "liquid_cash": _round2(liquid),
            "card_balances": _round2(card_now),
            "opening": _round2(liquid - card_now),
            "committed_out": _round2(committed_out),
            "expected_in": _round2(expected_in),
            "net": _round2(expected_in - committed_out),
            "closing": _round2(running),
            "low_point": _round2(low),
            "covered_by_income": bool(expected_in >= committed_out),
            "ledger": ledger,
            "n_paychecks": sum(1 for r in ledger if r["kind"] == "income"),
        }


    # ---- amazon ----
    amazon_cfg = config["amazon_categories"]

    # Short keywords whose bare substring produces false positives (carpet->pet, locator->cat,
    # versatile->tile, panels->pan). These must match as a whole word (optionally plural). Every
    # other keyword stays a substring match, which specific multi-word terms need (e.g. "n-acetyl").
    whole_word_kws = set(config.get("amazon_whole_word_keywords", ["cat", "pet", "pan", "tile", "pot", "rug"]))
    _ww_re = {kw: re.compile(r"\b" + re.escape(kw) + r"s?\b") for kw in whole_word_kws}
    # explicit per-item overrides (ASIN or description substring -> category), checked first so cat
    # gear with no obvious keyword can be forced into "pets". See config.amazon_category_overrides.
    overrides = config.get("amazon_category_overrides", {}) or {}

    def _amazon_cat(desc, asin=""):
        a = str(asin).strip()
        desc_l = str(desc).lower()
        for ov_key, ov_cat in overrides.items():
            k = str(ov_key).strip()
            if (a and k == a) or (k and k.lower() in desc_l):
                return ov_cat
        for key, kws in amazon_cfg.items():
            for kw in kws:
                k = kw.lower()
                if k in _ww_re:
                    if _ww_re[k].search(desc_l):
                        return key
                elif k in desc_l:
                    return key
        return "other"

    amazon = amazon.copy()
    asin_col = "ASIN" if "ASIN" in amazon.columns else None
    amazon["category"] = amazon.apply(
        lambda r: _amazon_cat(r["description"], r[asin_col] if asin_col else ""), axis=1
    )
    n_amazon_months = len(amazon_months)
    amazon_cat_totals = amazon.groupby("category")["line_total"].sum().sort_values(ascending=False)
    amazon_by_category = [
        {"name": k, "avg_mo": _round2(v / n_amazon_months), "total": _round2(v)}
        for k, v in amazon_cat_totals.items()
    ]
    big_ticket = amazon[amazon["line_total"] >= 100].sort_values("line_total", ascending=False)
    big_ticket_list = [
        {"description": r["description"][:80], "amount": _round2(r["line_total"]), "date": str(r["order date"].date())}
        for _, r in big_ticket.head(10).iterrows()
    ]
    repeat_desc = amazon["description"].value_counts()
    repeats = int((repeat_desc > 1).sum())

    # full itemized list -- powers the searchable/filterable Amazon detail table on the dashboard
    amazon_sorted = amazon.sort_values("order date", ascending=False)
    amazon_items = [
        {
            "date": str(r["order date"].date()) if pd.notna(r["order date"]) else "",
            "description": str(r["description"]),
            "category": r["category"],
            "price": _round2(r["price"]),
            "qty": int(r["quantity"]) if pd.notna(r["quantity"]) else 1,
            "line_total": _round2(r["line_total"]),
            "sns": int(float(r["subscribe & save"])) if pd.notna(r["subscribe & save"]) else 0,
            "url": str(r.get("item url", "")) if pd.notna(r.get("item url", "")) else "",
        }
        for _, r in amazon_sorted.iterrows()
    ]
    amazon_metrics = {
        "total_items": int(len(amazon)),
        "total_spend": _round2(amazon["line_total"].sum()),
        "avg_mo": _round2(amazon["line_total"].sum() / n_amazon_months),
        "subscribe_and_save_pct": _round2(amazon["subscribe & save"].fillna(0).astype(float).mean() * 100),
        "by_category": amazon_by_category,
        "big_ticket": big_ticket_list,
        "repeat_merchants": repeats,
        "items": amazon_items,
    }

    # ---- chewy (cat care itemization; already counted on the card as CHEWY.COM -> fostering) ----
    chewy = loaded.get("chewy")
    chewy_metrics = None
    if chewy is not None and not chewy.empty:
        ccfg = config.get("chewy_categories", {})

        def _chewy_cat(brand, product):
            text = f"{brand} {product}".lower()
            for key, spec in ccfg.items():
                if any(kw in text for kw in spec["keywords"]):
                    return key
            return "other"

        chewy = chewy.copy()
        chewy["cat"] = chewy.apply(lambda r: _chewy_cat(r["brand"], r["product"]), axis=1)
        chewy["month"] = chewy["date"].dt.to_period("M")
        orders = chewy.drop_duplicates("order_id")
        order_value = float(orders["order_total"].sum())
        n_orders = int(len(orders))
        first_d, last_d = chewy["date"].min(), chewy["date"].max()
        active_mo = max(1.0, (last_d - first_d).days / 30.44)

        # reconcile to the card: what actually hit the card vs. the retail order value (gap = promo credit)
        chewy_card = cards[
            cards["is_purchase"] & cards["Description"].str.contains("chewy", case=False, na=False)
        ]
        chewy_card_win = chewy_card[chewy_card["Transaction Date"] >= (first_d - pd.Timedelta(days=3))]
        card_paid = float(chewy_card_win["spend_amount"].sum())
        promo_savings = order_value - card_paid
        run_rate_mo = (card_paid / active_mo) if card_paid else (order_value / active_mo)

        cat_names = {"food": "Food", "litter": "Litter", "treats": "Treats", "toys": "Toys",
                     "health": "Health & meds", "other": "Other"}
        by_type = []
        for key in list(ccfg.keys()) + ["other"]:
            sub = chewy[chewy["cat"] == key]
            if sub.empty:
                continue
            by_type.append({"key": key, "name": cat_names.get(key, key.title()),
                            "items": int(len(sub)), "list_total": _round2(float(sub["list_price"].sum()))})
        by_type.sort(key=lambda x: -x["list_total"])

        ess_keys = [k for k, v in ccfg.items() if v.get("essential")]
        tot_list = float(chewy["list_price"].sum()) or 1.0
        ess_list = float(chewy[chewy["cat"].isin(ess_keys)]["list_price"].sum())
        essential_pct = ess_list / tot_list * 100
        essential_run_rate_mo = run_rate_mo * essential_pct / 100
        autoship_ongoing_yr = essential_run_rate_mo * 12 * 0.05  # Chewy Autoship: 5% ongoing (35% first order)

        chewy_by_month = chewy_card_win.groupby(chewy_card_win["Transaction Date"].dt.to_period("M"))["spend_amount"].sum()
        chewy_monthly = [{"month": _month_label(m), "amount": _round2(v)} for m, v in chewy_by_month.sort_index().items()]

        items = [
            {"date": str(r["date"].date()) if pd.notna(r["date"]) else "", "brand": r["brand"],
             "product": r["product"], "cat": r["cat"], "cat_name": cat_names.get(r["cat"], r["cat"].title()),
             "list_price": _round2(r["list_price"]) if pd.notna(r["list_price"]) else None,
             "order_total": _round2(r["order_total"]) if pd.notna(r["order_total"]) else None,
             "order_id": r["order_id"]}
            for _, r in chewy.sort_values("date", ascending=False).iterrows()
        ]

        # ---- cat purchases that went through Amazon (not Chewy) ----
        # Amazon items already tagged category == "pets" (after the whole-word fix above). These are
        # mostly one-time GEAR (feeder, fountain, litter boxes/mats) plus a little food/treats.
        cat_type_names = {"food": "Food", "litter": "Litter", "treats": "Treats", "toys": "Toys",
                          "health": "Health & meds", "gear": "Gear & equipment", "other": "Other"}

        def _amz_cat_type(desc):
            t = str(desc).lower()
            if any(w in t for w in ["feeder", "fountain", "litter box", "litter pan", "litter mat",
                                    "high sided", "cat pan", "litter tray", "bowl", "scratcher", "tree", "bed"]):
                return "gear"
            if "waste sack" in t or "disposal bag" in t:
                return "litter"
            if any(w in t for w in ["toy", " ball", "teaser", "wand", "mouse", "catnip", "feather"]):
                return "toys"
            if any(w in t for w in ["churu", "temptations", "treat", "lickable"]):
                return "treats"
            if any(w in t for w in ["food", "friskies", "purina", "kibble", "wet cat", "pate"]):
                return "food"
            if "litter" in t:
                return "litter"
            return "gear"

        amazon_cat_items = []
        amz_cat_total = 0.0
        if "category" in amazon.columns:
            apets = amazon[amazon["category"] == "pets"].sort_values("order date", ascending=False)
            for _, r in apets.iterrows():
                typ = _amz_cat_type(r["description"])
                amz_cat_total += float(r["line_total"])
                amazon_cat_items.append({
                    "date": str(r["order date"].date()) if pd.notna(r["order date"]) else "",
                    "product": str(r["description"]), "cat": typ, "cat_name": cat_type_names.get(typ, typ.title()),
                    "price": _round2(r["line_total"]), "qty": int(r["quantity"]) if pd.notna(r["quantity"]) else 1,
                })
        amazon_cat = {
            "total": _round2(amz_cat_total),
            "n_items": len(amazon_cat_items),
            "items": amazon_cat_items,
        }

        # ---- combined item ledger (Chewy + Amazon) for the "see everything" table ----
        all_cat_items = []
        for it in items:
            all_cat_items.append({"date": it["date"], "source": "Chewy",
                                  "product": ((it["brand"] + " ") if it["brand"] else "") + it["product"],
                                  "cat": it["cat"], "cat_name": it["cat_name"], "price": it["list_price"]})
        for it in amazon_cat_items:
            all_cat_items.append({"date": it["date"], "source": "Amazon", "product": it["product"],
                                  "cat": it["cat"], "cat_name": it["cat_name"], "price": it["price"]})
        all_cat_items.sort(key=lambda x: x["date"], reverse=True)

        chewy_metrics = {
            "n_orders": n_orders,
            "order_value": _round2(order_value),
            "card_paid": _round2(card_paid),
            "promo_savings": _round2(promo_savings),
            "avg_order": _round2(card_paid / n_orders) if n_orders else 0,
            "run_rate_mo": _round2(run_rate_mo),
            "window": {"start": str(first_d.date()), "end": str(last_d.date())},
            "by_type": by_type,
            "essential_pct": _round2(essential_pct),
            "essential_run_rate_mo": _round2(essential_run_rate_mo),
            "autoship_ongoing_yr": _round2(autoship_ongoing_yr),
            # set once enrolled (config events) -- flips the Autoship prose from "do this" to "done"
            "autoship_started": str(config.get("events", {}).get("chewy_autoship_started") or "") or None,
            "monthly": chewy_monthly,
            "items": items,
            "n_items_captured": int(len(chewy)),
            "amazon_cat": amazon_cat,
            "all_items": all_cat_items,
            "combined_total": _round2(card_paid + amz_cat_total),
        }

    # ---- runway inputs ----
    state_max = config["runway"]["state_unemployment_weekly_max"]
    high_quarter_wages = pay["annual_salary"] / 4
    est_weekly_benefit = min(state_max, high_quarter_wages / 26)
    runway_inputs = {
        "cash_hysa": net_worth["by_tax"].get("cash", 0.0),
        "est_weekly_benefit": _round2(est_weekly_benefit),
        "state_max_weekly": state_max,
        "burn_presets": config["runway"]["default_burn_presets"],
        "default_weeks": config["runway"]["default_weeks"],
        "max_weeks": 26,
        "tax_withholding_pct": config["runway"].get("tax_withholding_pct", 12.5),
        "gross_annual": pay["annual_salary"],
        "health_premium_employee": pay["health_premium_employee"],
    }

    # ---- red flags: a data-driven audit surfaced on its own tab ----
    def _m(x):
        return "${:,.0f}".format(round(float(x)))

    avg_spend_mo = observed_spend / n_avg_months
    saved_mo = total_saved / n_scored
    liquid_cash = float(net_worth.get("by_tax", {}).get("cash", 0.0))
    red_flags = []

    def _flag(sev, cat, title, detail, metric=None):
        red_flags.append({"severity": sev, "category": cat, "title": title, "detail": detail, "metric": metric})

    # over-budget categories (snacks handled by its own richer flag below, to avoid a duplicate)
    for c in categories_list:
        if c.get("key") == "snacks":
            continue
        if c.get("budget") and c.get("variance") is not None and c["variance"] > 0:
            over_pct = c["variance"] / c["budget"] * 100
            if over_pct >= 15:
                _flag("high" if over_pct >= 50 else "medium", "Spending",
                      f"{c['name']} is over budget",
                      f"Running {_m(c['avg_mo'])}/mo against a {_m(c['budget'])} target — {over_pct:.0f}% over, "
                      f"roughly {_m(c['variance'] * 12)}/yr more than planned.",
                      f"+{_m(c['variance'])}/mo")

    # low-savings months
    low_months = [r for r in monthly_rows if r["income"] and r["rate"] < 10]
    if low_months:
        _flag("medium", "Cash flow", f"{len(low_months)} month(s) saved under 10% of income",
              f"{', '.join(r['month'] for r in low_months)} fell below a 10% savings rate — typically furnishing, "
              f"family gifts, and card bills stacking in one month. Fine as one-offs; a red flag only if it becomes the norm.",
              f"{len(low_months)} of {len(monthly_rows)} mo")

    # single-stock concentration
    conc = net_worth.get("concentration") or {}
    if conc.get("single_stock_pct_assets", 0) >= 15:
        _flag("high" if conc["single_stock_pct_assets"] >= 25 else "medium", "Investments",
              "Single-stock concentration",
              f"{_m(conc['single_stock_total'])} sits in individual stocks ({conc['single_stock_pct_assets']:.0f}% of assets), "
              f"led by {conc['top_symbol']} at {conc['top_pct_assets']:.0f}% of assets. One bad name moves your whole balance sheet.",
              f"{conc['single_stock_pct_assets']:.0f}% of assets")

    # unused tax-advantaged space
    unused_space = headroom_403b + headroom_457b
    if unused_space > 5000:
        _flag("medium", "Opportunity", "Unused tax-advantaged space",
              f"{_m(headroom_457b)} of 457(b) plus {_m(headroom_403b)} of 403(b) headroom is unused this year, while you run a "
              f"~{_m(saved_mo)}/mo surplus into taxable accounts. Shifting some in would cut this year's taxable income.",
              f"{_m(unused_space)}/yr")

    # Chase Freedom quarterly bonus never activated -- the largest free item on the board
    if rewards and not rewards["bonus_activated"] and rewards["bonus_missed_per_year"] > 0:
        # name the statement this was actually read off, so the flag doesn't cite a stale month
        _freedom = next((c for c in rewards.get("cards", []) if "freedom" in str(c.get("card_name", "")).lower()),
                        (rewards.get("cards") or [None])[0])
        _stmt = (_freedom or {}).get("statement_date") or "the latest"
        _flag("high", "Opportunity", "Freedom 5% categories are not activated",
              f"Every point on the {_stmt} statement came off the base '1% on all purchases' line. The card pays 5% "
              f"on up to {_m(rewards['bonus_cap'])} of combined purchases per quarter, but only if you activate it "
              f"each quarter (free, at chase.com/freedom). You run ~{_m(rewards['quarterly_volume'])}/quarter through "
              f"it, so the cap is easily reachable.", f"{_m(rewards['bonus_missed_per_year'])}/yr")
    # Activated -- so the live risk is forgetting the NEXT quarter, not this one.
    if rewards and rewards.get("bonus_activated_on") and rewards["bonus_missed_per_year"] > 0:
        _flag("medium", "Opportunity",
              f"Re-activate the Freedom 5% categories for {rewards['bonus_next_quarter']}",
              f"You activated on {rewards['bonus_activated_on']}, which covers the current quarter only — "
              f"Chase resets it every quarter and pays nothing extra if you forget. The next window opens "
              f"{rewards['bonus_next_quarter_starts']} at chase.com/freedom. At ~"
              f"{_m(rewards['quarterly_volume'])}/quarter of volume you reach the "
              f"{_m(rewards['bonus_cap'])} cap comfortably.",
              f"{_m(rewards['bonus_missed_per_quarter'])}/quarter")

    if rewards and rewards["total_value_usd"] > 100:
        _flag("low", "Opportunity", "Unredeemed points sitting idle",
              f"{rewards['total_points']:,} points across both cards = {_m(rewards['total_value_usd'])} of cash back "
              f"you have earned and not taken. Points do not earn interest and are lost if a card closes.",
              _m(rewards["total_value_usd"]))

    # emergency fund depth, measured against the household's own target -- not a generic rule of
    # thumb. With a 12-month target, anything above it is deliberate liquidity: a balance past 12
    # months is a choice being executed, not idle money to be redeployed.
    if avg_spend_mo > 0:
        target_months = float(config.get("emergency_fund_months", 6))
        months_runway = liquid_cash / avg_spend_mo
        target_cash = target_months * avg_spend_mo
        if months_runway < target_months * 0.5:
            _flag("high", "Safety net", "Thin emergency fund",
                  f"{_m(liquid_cash)} liquid covers {months_runway:.1f} months of ~{_m(avg_spend_mo)} spending, "
                  f"against your {target_months:.0f}-month target ({_m(target_cash)}).",
                  f"{months_runway:.1f} mo")
        elif months_runway < target_months:
            _flag("low", "Safety net", "Emergency fund just below your target",
                  f"{_m(liquid_cash)} liquid is {months_runway:.1f} months against the {target_months:.0f} months you want "
                  f"— {_m(target_cash - liquid_cash)} short. At {_m(saved_mo)}/mo you close that in "
                  f"{max(1, round((target_cash - liquid_cash) / saved_mo)) if saved_mo > 0 else '—'} months.",
                  f"{months_runway:.1f} of {target_months:.0f} mo")
        elif months_runway > target_months * 1.5:
            _flag("low", "Opportunity", "Cash well beyond even your 12-month target",
                  f"{_m(liquid_cash)} liquid is {months_runway:.1f} months — {_m(liquid_cash - target_cash)} past the "
                  f"{target_months:.0f} months you hold by choice. Past a point, extra buffer stops buying "
                  f"much more safety.", f"{months_runway:.1f} mo")

    # disability insurance gap
    ic = config.get("insurance_coverage") or {}
    if not ic.get("disability_short_term") and not ic.get("disability_long_term"):
        _flag("medium", "Protection", "No disability insurance",
              "If illness or injury stopped you working, none of your income would be replaced — liquid savings would be the "
              "only backstop. Worth pricing, especially while you help support family.", "0 coverage")

    # price creep on recurring bills (sustained increases detected from the statements)
    creepers = [r for r in recurring if r.get("price_change")]
    if creepers:
        extra_mo = sum(
            (r["price_change"]["to"] - r["price_change"]["from"]) * (r["avg_mo"] / r["latest_amount"] if r["latest_amount"] else 1)
            for r in creepers
        )
        detail_bits = ", ".join(
            f"{r['name']} {_m(r['price_change']['from'])}→{_m(r['price_change']['to'])} (+{r['price_change']['pct']:.0f}%)"
            for r in creepers[:4]
        )
        _flag("medium" if extra_mo >= 25 else "low", "Subscriptions", "Recurring bills quietly went up",
              f"{len(creepers)} recurring charge(s) raised their price and the new price has stuck: {detail_bits}. "
              f"Together that's ~{_m(extra_mo)}/mo ({_m(extra_mo * 12)}/yr) more than you used to pay — renegotiate, downgrade, or accept deliberately.",
              f"+{_m(extra_mo)}/mo")

    # redundant recurring services
    hosting = [r for r in recurring if r.get("category") == "web_hosting" and r.get("active")]
    if len(hosting) >= 2:
        _flag("low", "Subscriptions", "Multiple web-hosting bills",
              f"{len(hosting)} hosting/domain services bill you ({', '.join(sorted(set(h['name'] for h in hosting)))}). "
              f"If any is a dead domain or unused site, cancel it.", f"{len(hosting)} services")

    # convenience / energy-drink habit
    snacks_cat = next((c for c in categories_list if c.get("key") == "snacks"), None)
    if snacks_cat and snacks_cat["avg_mo"] >= 20:
        top = (snacks_cat.get("merchants") or [{}])[0]
        top_note = f" — led by {top.get('name')} at ~{_m(top.get('avg_mo', 0))}/mo across {top.get('count', 0)} visits" if top.get("name") else ""
        sev = "high" if snacks_cat["avg_mo"] >= 150 else "medium"
        _flag(sev, "Behavioral", "Bodega & convenience habit is your top discretionary line",
              f"{_m(snacks_cat['avg_mo'])}/mo ({_m(snacks_cat['avg_mo'] * 12)}/yr) in small corner-store runs{top_note}. "
              f"Mostly energy drinks and snacks a few dollars at a time — buying the drinks in bulk and batching snack runs is the easiest money on the board.",
              f"{_m(snacks_cat['avg_mo'])}/mo")

    # chewy autoship opportunity (recurring cat necessities bought à la carte). Closed out once
    # `events.chewy_autoship_started` is set -- once enrolled, the flag would be nagging about
    # something already done.
    autoship_on = config.get("events", {}).get("chewy_autoship_started")
    if chewy_metrics and chewy_metrics["essential_run_rate_mo"] >= 30 and not autoship_on:
        _flag("low", "Opportunity", "Chewy Autoship left on the table",
              f"You're reordering cat food & litter about every couple of weeks (~{_m(chewy_metrics['essential_run_rate_mo'])}/mo "
              f"of recurring necessities) but paying à la carte. Chewy Autoship is 5% off every order (35% off the first) plus "
              f"guaranteed free shipping — set-and-forget on the food and litter you already rebuy. You've been good about promos "
              f"({_m(chewy_metrics['promo_savings'])} in eGift credit applied); this is the same money, automated.",
              f"~{_m(chewy_metrics['autoship_ongoing_yr'])}/yr")

    sev_rank = {"high": 0, "medium": 1, "low": 2}
    red_flags.sort(key=lambda f: sev_rank.get(f["severity"], 3))
    red_flags_summary = {
        "high": sum(1 for f in red_flags if f["severity"] == "high"),
        "medium": sum(1 for f in red_flags if f["severity"] == "medium"),
        "low": sum(1 for f in red_flags if f["severity"] == "low"),
        "total": len(red_flags),
    }

    card_current_total = sum(
        float(l.get("balance", 0))
        for l in net_worth.get("liabilities", [])
        if l.get("source_type") == "credit_card"
    )
    receivable_total = float(net_worth.get("by_tax", {}).get("receivable", 0))
    liquid_cash_total = float(net_worth.get("by_tax", {}).get("cash", 0))
    financial_integrity = {
        "statement_assets": _round2(net_worth.get("assets_total", 0)),
        "statement_liabilities": _round2(net_worth.get("liabilities_total", 0)),
        "statement_net_worth": _round2(net_worth.get("net_total", 0)),
        "receivables": _round2(receivable_total),
        "liquid_cash": _round2(liquid_cash_total),
        "current_card_balances": _round2(card_current_total),
        "net_liquid_cash": _round2(max(0, liquid_cash_total - card_current_total)),
        "balance_as_of_newest": net_worth.get("as_of"),
        "balance_as_of_oldest": net_worth.get("as_of_oldest"),
        "holdings_as_of": net_worth.get("holdings_as_of"),
        "pending_activity_total": _round2(manual_spend_total + card_alert_summary["net"]),
        "pending_activity_count": len(manual_txns) + card_alert_summary["count"],
    }

    return {
        "generated_at": pd.Timestamp.now().isoformat(),
        "coverage": coverage,
        "summary": summary,
        "paycheck": paycheck,
        "trends": trends,
        "categories": categories_list,
        "merchants": merchants_block,
        "savings_history": savings_history,
        "savings_stats": savings_stats,
        "month_review": month_review,
        "card_alerts": card_alert_summary,
        "rewards": rewards,
        "fixed_floor": fixed_floor,
        "paycheck_view": paycheck_view,
        "deferral_math": deferral_math,
        "data_quality": data_quality,
        "financial_integrity": financial_integrity,
        "era_analysis": era_analysis,
        "deli_decode": deli_decode,
        "energy": energy,
        "budget_5030": budget_5030,
        "sinking_funds": sinking_funds,
        "red_flags": red_flags,
        "red_flags_summary": red_flags_summary,
        "food": food,
        "recurring": recurring,
        "forward_30": forward_30,
        "recurring_active_mo": _round2(recurring_active_mo),
        "venmo_decode": venmo_decode,
        "amazon": amazon_metrics,
        "chewy": chewy_metrics,
        "runway_inputs": runway_inputs,
        "credit_health": config.get("credit_health"),
        "net_worth_detail": net_worth,
        "loans_out": open_loans,
        "insurance_coverage": config.get("insurance_coverage"),
        "credit_card_points": config.get("credit_card_points"),
        "_internal": {
            "n_bank_months": n_bank_months,
            "n_avg_months": n_avg_months,
            "n_scored_months": n_scored,
            "observed_spend": _round2(observed_spend),
            "total_income": _round2(total_income),
            "total_spend": _round2(total_spend),
            "total_family": _round2(total_family),
            "total_saved": _round2(total_saved),
            "monthly_rows": monthly_rows,
        },
    }
