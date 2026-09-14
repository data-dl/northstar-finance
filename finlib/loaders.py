"""One loader per data source. Each returns a tidy DataFrame; no reconciliation here (see reconcile.py)."""
import csv
import json
import re
from pathlib import Path

import pandas as pd


def _files(data_dir: Path, subfolder: str, pattern: str = "*.csv"):
    return sorted((data_dir / subfolder).glob(pattern))


def _dedupe_multiset(df: pd.DataFrame, key_cols: list) -> pd.DataFrame:
    """Drop rows duplicated across overlapping export files WITHOUT collapsing genuine same-day
    duplicates (two identical $2.75 transit taps, back-to-back laundry payments). Each row is matched by
    key + its occurrence number within its own source file, so the Nth identical charge in one
    export only merges with the Nth identical charge in another export — never with its siblings."""
    occ = df.groupby(["_source_file"] + key_cols, dropna=False).cumcount()
    return (
        df.assign(_occ=occ)
        .drop_duplicates(subset=key_cols + ["_occ"])
        .drop(columns="_occ")
        .reset_index(drop=True)
    )


# --- credit-union PDF statement parsing (extends bank history well before the CSV exports) ---
_PDF_TXN_RE = re.compile(
    r"^(\d{2})/(\d{2})\s+\$?([\d,]+\.\d{2})(-?)\s+\$?([\d,]+\.\d{2})-?\s+"
    r"(?:Recurring\s+)?(Withdrawal|Deposit)\s+(.*)$"
)
_PDF_CHECK_RE = re.compile(r"^(\d{2})/(\d{2})\s+\$?([\d,]+\.\d{2})-?\s+\$?[\d,]+\.\d{2}-?\s+(Check\s+\d+.*)$")
_PDF_PERIOD_RE = re.compile(r"Period Ending:\s*(\d{2})/(\d{2})/(\d{4})")
_PDF_DEP_TOT = re.compile(r"Total Deposits for\s+([\d,]+\.\d{2})")
_PDF_WD_TOT = re.compile(r"Total Withdrawals for\s+-?([\d,]+\.\d{2})")


class PDFParseError(Exception):
    pass


def _pdf_num(s: str) -> float:
    return float(s.replace(",", ""))


def _normalize_pdf_desc(raw: str, config: dict):
    """Map a raw statement description onto the clean forms the reconcile rules (DESIGN Sec.5)
    expect, and derive Parent Category. Returns (description, parent_category).

    Internal checking<->savings sweeps use the credit union's generic "share" wording and are
    handled here; everything institution-specific (payroll, card autopay, brokerage buys) comes
    from `config.bank_statement_pdf.rewrites`, first match wins."""
    low = raw.lower()
    # internal checking<->savings sweeps -> canonical forms in config.bank_internal_transfer_descriptions
    if "transfer to share" in low:
        return "Transfer To Share", "Transfer"
    m = re.search(r"transfer from share (\d+)", low)
    if m:
        return f"Transfer from Account {m.group(1)}", "Transfer"
    if "transfer from share" in low:
        return "Transfer from Account 0001", "Transfer"
    for rule in (config.get("bank_statement_pdf") or {}).get("rewrites", []) or []:
        if any(str(k).lower() in low for k in rule.get("contains", [])):
            return rule.get("description", raw), rule.get("parent")
    return raw, None


def load_bank_pdfs(data_dir: Path, config: dict) -> pd.DataFrame:
    """Parse credit-union monthly statement PDFs into the same schema as the CSV exports. Every statement's
    parsed deposit/withdrawal totals are checked against its printed control totals in validate.py."""
    try:
        import pdfplumber
    except ImportError:
        return pd.DataFrame()
    rows = []
    # case-insensitive filesystems (Windows) match *.PDF and *.pdf to the same files -- dedupe by resolved path
    pdf_files = sorted({f.resolve() for f in (data_dir / "bank").glob("*") if f.suffix.lower() == ".pdf"})
    for f in pdf_files:
        with pdfplumber.open(f) as pdf:
            lines = []
            for pg in pdf.pages:
                lines += (pg.extract_text() or "").split("\n")
        period = None
        for ln in lines:
            m = _PDF_PERIOD_RE.search(ln)
            if m:
                period = (int(m.group(1)), int(m.group(3)))  # (month, year)
                break
        if not period:
            continue
        period_month, year = period
        account = None
        controls = {}   # account -> {"dep": x, "wd": y} printed totals
        sums = {}       # account -> {"dep": x, "wd": y} parsed sums
        # the statement's section headings ("Free Checking ID 0072") -> the CSV export's Account label
        account_labels = (config.get("bank_statement_pdf") or {}).get("accounts", {}) or {}
        for ln in lines:
            for heading, label in account_labels.items():
                if heading in ln:
                    account = label
            dm, wm = _PDF_DEP_TOT.search(ln), _PDF_WD_TOT.search(ln)
            if dm and account:
                controls.setdefault(account, {})["dep"] = _pdf_num(dm.group(1))
            if wm and account:
                controls.setdefault(account, {})["wd"] = _pdf_num(wm.group(1))
            s = ln.strip()
            m = _PDF_TXN_RE.match(s)
            cm = _PDF_CHECK_RE.match(s) if not m else None
            if m:
                mm, dd, amt, _sign, _bal, typ, raw_desc = m.groups()
                ttype = "Debit" if typ == "Withdrawal" else "Credit"
            elif cm:
                mm, dd, amt, raw_desc = cm.groups()
                ttype = "Debit"
            else:
                continue
            value = _pdf_num(amt)
            key = "dep" if ttype == "Credit" else "wd"
            sums.setdefault(account, {}).setdefault(key, 0.0)
            sums[account][key] += value
            yy = year - 1 if (int(mm) == 12 and period_month == 1) else year
            desc, parent = _normalize_pdf_desc(raw_desc.strip(), config)
            rows.append({
                "Date": pd.Timestamp(year=yy, month=int(mm), day=int(dd)),
                "Description": desc,
                "Original Description": raw_desc.strip(),
                "Amount": value,
                "Type": ttype,
                "Parent Category": parent,
                "Category": None,
                "Account": account,
                "_source_file": f.name,
            })
        # fail loudly (DESIGN Sec.9): parsed sums must equal the statement's printed control totals
        for acct, ctrl in controls.items():
            got = sums.get(acct, {})
            for key in ("dep", "wd"):
                want = ctrl.get(key)
                have = round(got.get(key, 0.0), 2)
                if want is not None and abs(have - want) > 0.01:
                    raise PDFParseError(
                        f"{f.name} [{acct}] {key}: parsed {have:.2f} != statement total {want:.2f}. "
                        f"A transaction line format may be unhandled."
                    )
    return pd.DataFrame(rows)


def load_bank(data_dir: Path, config: dict) -> pd.DataFrame:
    frames = []
    for f in _files(data_dir, "bank"):
        df = pd.read_csv(f)
        df["_source_file"] = f.name
        frames.append(df)
    csv_df = pd.DataFrame()
    if frames:
        csv_df = pd.concat(frames, ignore_index=True)
        csv_df["Date"] = pd.to_datetime(csv_df["Date"], format="%m/%d/%Y")
        csv_df["Amount"] = pd.to_numeric(csv_df["Amount"], errors="coerce")
        # dedupe-on-append: bank exports are year-at-a-time and can overlap at boundaries.
        # Occurrence-aware so two genuinely identical same-day transactions both survive.
        key_cols = ["Date", "Description", "Amount", "Type", "Account"]
        csv_df = _dedupe_multiset(csv_df, key_cols)

    # PDF statements cover periods the CSV exports don't. Use them for any date OUTSIDE the CSV's
    # range -- older history before its first row, and the tail of the current month after its last.
    # The CSV still wins on the overlap, so its richer categorization is preserved.
    #
    # This used to keep only `Date < csv_min`, which silently discarded a freshly downloaded current
    # statement: a Jul 31 statement is entirely inside the CSV's start, so every row was dropped and
    # the last few days of the month never loaded. Dropping in the newest statement looked like it
    # worked and changed nothing.
    pdf_df = load_bank_pdfs(data_dir, config)
    if not pdf_df.empty:
        if not csv_df.empty:
            csv_min, csv_max = csv_df["Date"].min(), csv_df["Date"].max()
            pdf_df = pdf_df[(pdf_df["Date"] < csv_min) | (pdf_df["Date"] > csv_max)]
        out = pd.concat([pdf_df, csv_df], ignore_index=True)
    else:
        out = csv_df
    if out.empty:
        return out
    return out.sort_values("Date").reset_index(drop=True)


def load_cards(data_dir: Path, card_config: dict) -> pd.DataFrame:
    frames = []
    for f in _files(data_dir, "cards"):
        m = re.search(r"(\d{4})", f.name)
        card_id = m.group(1) if m else "unknown"
        df = pd.read_csv(f)
        df["_source_file"] = f.name
        df["card_id"] = card_id
        df["card_name"] = card_config.get(card_id, {}).get("name", card_id)
        frames.append(df)
    if not frames:
        return pd.DataFrame()
    out = pd.concat(frames, ignore_index=True)
    out["Transaction Date"] = pd.to_datetime(out["Transaction Date"], format="%m/%d/%Y")
    out["Amount"] = pd.to_numeric(out["Amount"], errors="coerce")
    # Overlapping full-history pulls dedupe safely; occurrence-aware so repeated same-day
    # charges (multiple transit taps, laundry machines, corner-store runs) are all kept.
    out = _dedupe_multiset(out, ["Transaction Date", "Description", "Amount", "Type", "card_id"])
    return out


def _parse_card_points(page) -> dict | None:
    """Pull the rewards summary off a Chase statement's first page.

    The rewards box sits in the right-hand column, and plain text extraction interleaves it with
    the calendar widget ("S M T W T F S Previous points balance 4,120") and, on the Prime Visa,
    overlaps the total with marketing copy ("Rreewdarde ymourp rotuitionen 3Vis2a8" -- 328 woven
    into "Reward your routine Visa").  So the block is rebuilt from word positions instead, and
    the closing balance is derived as previous + earned - redeemed rather than scraped.  Any total
    that IS legible is used as a cross-check, so a layout change fails loudly.
    """
    words = [w for w in page.extract_words() if w["x0"] > page.width * 0.5]
    if not words:
        return None
    lines: dict[int, list] = {}
    for w in words:
        lines.setdefault(round(w["top"] / 4), []).append(w)
    rendered = [" ".join(x["text"] for x in sorted(v, key=lambda a: a["x0"])) for _, v in sorted(lines.items())]

    num = r"([\d,]+)"
    prev = earned_total = redeemed = None
    earn_lines = []
    for ln in rendered:
        # The Freedom letter-spaces its labels ("Pre vi ous po ints ba lan ce 12,406") while the
        # Prime Visa does not, so fixed labels are matched against a whitespace-stripped copy.
        flat = re.sub(r"\s+", "", ln)
        m = re.match(rf"Previouspointsbalance{num}$", flat, re.I)
        if m:
            prev = int(m.group(1).replace(",", ""))
            continue
        m = re.match(rf"[-−]?Pointsredeemedthisstatementperiod{num}$", flat, re.I)
        if m:
            redeemed = int(m.group(1).replace(",", ""))
            continue
        m = re.match(rf"\+\s*(.+?)\s+{num}$", ln)
        if m:
            pts = int(m.group(2).replace(",", ""))
            earn_lines.append({"label": m.group(1).strip(), "points": pts})
    if prev is None or not earn_lines:
        return None
    earned_total = sum(e["points"] for e in earn_lines)
    redeemed = redeemed or 0
    total = prev + earned_total - redeemed

    # cross-check against a legible printed total, if the layout gave us one
    printed = None
    for ln in rendered:
        m = re.search(rf"^(?:Total points available.*?|.*Ultimate Rewards.*?)\s{num}$", ln, re.I)
        if m:
            cand = int(m.group(1).replace(",", ""))
            if cand > 100:
                printed = cand
                break
    if printed is not None and printed != total:
        raise PDFParseError(
            f"points block does not reconcile: {prev} + {earned_total} - {redeemed} = {total}, "
            f"but the statement prints {printed}")
    return {
        "previous": prev, "earned": earned_total, "redeemed": redeemed, "total": total,
        "printed_total_verified": printed is not None,
        "earn_lines": earn_lines,
        # Chase values points at 1 cent for cash back on both of these products; the Prime Visa
        # statement states it outright ("Each $1 in % back rewards earned is equal to 100 points").
        "value_usd": round(total / 100.0, 2),
        "earned_value_usd": round(earned_total / 100.0, 2),
    }


def load_card_statements(data_dir: Path, card_config: dict) -> pd.DataFrame:
    """Load the latest Chase statement balance for each card.

    Transaction CSVs answer "what did I spend?"; statement PDFs answer "what do I
    owe?".  An optional data/balances/credit_cards.csv can supply a newer current
    balance snapshot.  A later statement automatically supersedes an older snapshot.
    """
    try:
        import pdfplumber
    except ImportError:
        pdfplumber = None

    folder = data_dir / "cards"
    pdfs = sorted(p for p in folder.glob("*") if p.suffix.lower() == ".pdf") if folder.exists() else []
    rows = []
    money = r"([\d,]+\.\d{2})"
    for f in pdfs if pdfplumber else []:
        with pdfplumber.open(f) as pdf:
            page0 = pdf.pages[0]
            text = page0.extract_text() or ""
            points = _parse_card_points(page0)
        acct = re.search(r"Account Number:\s*(?:X{2,}\s*)+(\d{4})", text, re.I)
        if not acct:
            continue  # a non-Chase PDF can coexist in data/cards without breaking the run
        card_id = acct.group(1)
        balance = re.search(rf"New Balance\s+\$?{money}", text, re.I)
        period = re.search(r"Opening/Closing Date\s+(\d{2}/\d{2}/\d{2})\s*-\s*(\d{2}/\d{2}/\d{2})", text, re.I)
        if not balance or not period:
            raise PDFParseError(f"{f.name}: found Chase card {card_id}, but could not parse its balance/closing date")
        minimum = re.search(rf"Minimum Payment Due:?\s+\$?{money}", text, re.I)
        due = re.search(r"Payment Due Date:?\s+(\d{2}/\d{2}/\d{2})", text, re.I)
        close_date = pd.to_datetime(period.group(2), format="%m/%d/%y")
        rows.append({
            "card_id": card_id,
            "card_name": card_config.get(card_id, {}).get("name", f"Chase x{card_id}"),
            "statement_balance": _pdf_num(balance.group(1)),
            "statement_date": close_date,
            "minimum_payment": _pdf_num(minimum.group(1)) if minimum else 0.0,
            "due_date": pd.to_datetime(due.group(1), format="%m/%d/%y") if due else pd.NaT,
            "points": points,
            "source_file": f.name,
        })

    # data/cards/statements.json: the same facts transcribed by hand (or generated), for cards
    # whose PDF is not on file. Same shape as a parsed statement; the newest statement per card
    # wins regardless of which source it came from.
    rows.extend(_statement_summaries(folder, card_config))

    statements = pd.DataFrame(rows)
    if not statements.empty:
        statements = (
            statements.sort_values(["card_id", "statement_date", "source_file"])
            .groupby("card_id", as_index=False)
            .tail(1)
            .reset_index(drop=True)
        )

    snapshot_path = data_dir / "balances" / "credit_cards.csv"
    snapshots = pd.DataFrame()
    if snapshot_path.exists():
        snapshots = pd.read_csv(snapshot_path, dtype={"card_id": str})
        snapshots["card_id"] = snapshots["card_id"].str.zfill(4)
        snapshots["current_balance"] = pd.to_numeric(snapshots["current_balance"], errors="coerce")
        snapshots["as_of"] = pd.to_datetime(snapshots["as_of"], errors="coerce")
        snapshots = (
            snapshots.dropna(subset=["card_id", "current_balance", "as_of"])
            .sort_values(["card_id", "as_of"])
            .groupby("card_id", as_index=False)
            .tail(1)
            .reset_index(drop=True)
        )

    card_ids = sorted(set(statements.get("card_id", [])) | set(snapshots.get("card_id", [])))
    result = []
    for card_id in card_ids:
        stmt_rows = statements[statements["card_id"] == card_id] if not statements.empty else pd.DataFrame()
        snap_rows = snapshots[snapshots["card_id"] == card_id] if not snapshots.empty else pd.DataFrame()
        stmt = stmt_rows.iloc[-1].to_dict() if not stmt_rows.empty else {}
        snap = snap_rows.iloc[-1].to_dict() if not snap_rows.empty else {}
        stmt_date = stmt.get("statement_date", pd.NaT)
        snap_date = snap.get("as_of", pd.NaT)
        use_snapshot = bool(snap) and (pd.isna(stmt_date) or snap_date >= stmt_date)
        chosen_balance = snap.get("current_balance") if use_snapshot else stmt.get("statement_balance")
        chosen_date = snap_date if use_snapshot else stmt_date
        result.append({
            **stmt,
            "card_id": card_id,
            "card_name": snap.get("card_name") or stmt.get("card_name") or card_config.get(card_id, {}).get("name", f"Chase x{card_id}"),
            "liability_balance": float(chosen_balance),
            "balance_kind": "current" if use_snapshot else "statement",
            "as_of": chosen_date,
            "snapshot_source": snap.get("source_file") if use_snapshot else None,
        })
    return pd.DataFrame(result).sort_values("card_id").reset_index(drop=True) if result else pd.DataFrame()


def _statement_summaries(folder: Path, card_config: dict) -> list:
    path = folder / "statements.json"
    if not path.exists():
        return []
    try:
        entries = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return []
    out = []
    for e in entries if isinstance(entries, list) else []:
        card_id = str(e.get("card_id", "")).zfill(4)
        if not card_id.strip("0"):
            continue
        points = None
        p = e.get("points") or {}
        if p and p.get("earn_lines"):
            earn_lines = [{"label": str(x.get("label", "")), "points": int(x.get("points", 0))}
                          for x in p["earn_lines"]]
            prev, redeemed = int(p.get("previous", 0)), int(p.get("redeemed", 0))
            earned = sum(x["points"] for x in earn_lines)
            total = prev + earned - redeemed
            printed = p.get("total")
            if printed is not None and int(printed) != total:
                raise PDFParseError(
                    f"statements.json [{card_id}]: points do not reconcile: {prev} + {earned} - {redeemed} "
                    f"= {total}, but the summary says {printed}")
            points = {"previous": prev, "earned": earned, "redeemed": redeemed, "total": total,
                      "printed_total_verified": printed is not None, "earn_lines": earn_lines,
                      "value_usd": round(total / 100.0, 2), "earned_value_usd": round(earned / 100.0, 2)}
        out.append({
            "card_id": card_id,
            "card_name": card_config.get(card_id, {}).get("name", f"Card x{card_id}"),
            "statement_balance": float(e.get("statement_balance", 0.0)),
            "statement_date": pd.to_datetime(e.get("statement_date")),
            "minimum_payment": float(e.get("minimum_payment", 0.0) or 0.0),
            "due_date": pd.to_datetime(e.get("due_date")) if e.get("due_date") else pd.NaT,
            "points": points,
            "source_file": "statements.json",
        })
    return out


def load_amazon(data_dir: Path) -> pd.DataFrame:
    frames = []
    for f in _files(data_dir, "amazon"):
        df = pd.read_csv(f)
        df["_source_file"] = f.name
        frames.append(df)
    if not frames:
        return pd.DataFrame()
    out = pd.concat(frames, ignore_index=True)
    out["price"] = (
        out["price"].astype(str).str.replace(r"[$,]", "", regex=True)
    )
    out["price"] = pd.to_numeric(out["price"], errors="coerce")
    out = out[out["price"].notna() & (out["price"] > 0)].copy()
    out["quantity"] = pd.to_numeric(out["quantity"], errors="coerce").fillna(1)
    out["line_total"] = out["price"] * out["quantity"]
    out["order date"] = pd.to_datetime(out["order date"], errors="coerce")
    out = _dedupe_multiset(out, ["order id", "description", "price", "quantity"])
    return out


def _parse_venmo_amount(s: str) -> float:
    s = str(s).strip()
    sign = -1.0 if s.startswith("-") else 1.0
    num = re.sub(r"[^0-9.]", "", s)
    return sign * float(num) if num else 0.0


def load_venmo(data_dir: Path, owner_name: str) -> pd.DataFrame:
    """`owner_name` is the account holder as Venmo prints it (config.identity.venmo_name)."""
    frames = []
    for f in _files(data_dir, "venmo"):
        df = pd.read_csv(f, header=2)
        df = df[df["Datetime"].notna() & df["Type"].notna()].copy()
        df["_source_file"] = f.name
        frames.append(df)
    if not frames:
        return pd.DataFrame()
    out = pd.concat(frames, ignore_index=True)
    out["Datetime"] = pd.to_datetime(out["Datetime"], errors="coerce")
    out["amount"] = out["Amount (total)"].apply(_parse_venmo_amount)
    out["counterparty"] = out.apply(
        lambda r: r["To"] if isinstance(r["From"], str) and owner_name in r["From"] else r["From"],
        axis=1,
    )
    out = out.drop_duplicates(subset=["ID"]).reset_index(drop=True)
    return out


def _chewy_price(dollars: str, cents: str) -> float:
    d = re.sub(r"[^0-9]", "", str(dollars or ""))
    c = re.sub(r"[^0-9]", "", str(cents or ""))
    if not d and not c:
        return float("nan")
    return float(f"{d or '0'}.{(c or '0').zfill(2)[:2]}")


def load_chewy(data_dir: Path) -> pd.DataFrame:
    """Parse Chewy's order-history export (a scraped CSV with cosmetic column names) into one row per
    (order, captured item). Chewy already appears on the card as CHEWY.COM, so this is *itemization*
    (like Amazon) -- it never adds to the spend total; it explains what the cat-care money buys.

    The export only surfaces the top 1-2 products per order, so item prices are a representative
    SAMPLE and are the pre-discount 'Chewy Price'; the reliable money figure is `order_total`
    (post-discount, what Chewy billed). Callers should sum order_total per unique order, not items."""
    folder = data_dir / "chewy"
    files = sorted(folder.glob("*.csv")) if folder.exists() else []
    rows = []
    for f in files:
        with open(f, encoding="utf-8-sig", newline="") as fh:
            reader = csv.DictReader(fh)
            for rec in reader:
                oid = (rec.get("styles_orderId__9auMd") or "").strip()
                date_raw = (rec.get("client-date") or "").strip()
                total_raw = rec.get("styles_orderTotal__W2t1h") or ""
                order_total = _pdf_num(re.sub(r"[^0-9.]", "", total_raw)) if re.search(r"\d", total_raw) else float("nan")
                status = (rec.get("styles_orderStatusContentMessage__mXOb7") or "").strip()
                # two item slots: base column names, then the " 2"-suffixed set
                for suf in ("", " 2"):
                    brand = (rec.get("kib-product-title__text" + suf) or "").strip()
                    product = (rec.get("styles_itemContentTitleName__vouPu" + suf) or "").strip()
                    if not brand and not product:
                        continue
                    price = _chewy_price(
                        rec.get("kib-product-price__dollars" + suf),
                        rec.get("kib-product-price__cents" + suf),
                    )
                    rows.append({
                        "order_id": oid,
                        "date": pd.to_datetime(date_raw, errors="coerce"),
                        "order_total": order_total,
                        "brand": brand,
                        "product": product,
                        "list_price": price,
                        "status": status,
                        "_source_file": f.name,
                    })
    if not rows:
        return pd.DataFrame()
    out = pd.DataFrame(rows)
    # overlapping exports: same order+product across pulls dedupe; genuine repeats within an order kept
    out = _dedupe_multiset(out, ["order_id", "product", "list_price"])
    return out.sort_values("date").reset_index(drop=True)


def load_balances(data_dir: Path) -> pd.DataFrame:
    """balances.csv: one row per account (assets + a LIABILITY marker row). Positive balances."""
    f = data_dir / "balances" / "balances.csv"
    if not f.exists():
        return pd.DataFrame()
    df = pd.read_csv(f)
    df["balance"] = pd.to_numeric(df["balance"], errors="coerce").fillna(0.0)
    df = df[df["account"].notna()].copy()
    return df.reset_index(drop=True)


def load_vanguard_holdings(data_dir: Path) -> pd.DataFrame:
    """Parse only the top holdings block of VANGUARD_ACCOUNT_LIST.csv (positions), stopping at
    the transaction-history section. Columns: account_number, name, symbol, shares, price, value."""
    f = data_dir / "balances" / "VANGUARD_ACCOUNT_LIST.csv"
    if not f.exists():
        return pd.DataFrame()
    rows = []
    with open(f, encoding="utf-8-sig") as fh:
        header_seen = False
        for line in fh:
            line = line.rstrip("\n")
            if not line.strip():
                continue
            if line.startswith("Account Number,Investment Name"):
                header_seen = True
                continue
            # the second header marks the start of the transaction block -> stop
            if line.startswith("Account Number,Trade Date"):
                break
            if not header_seen:
                continue
            parts = line.split(",")
            if len(parts) < 6:
                continue
            # Investment Name may itself contain commas -> value is always the field before trailing empties
            acct = parts[0].strip()
            # rebuild from the right: [.., Symbol, Shares, Price, Value, (trailing '')]
            # take last 4 meaningful numeric-ish fields
            trimmed = [p for p in parts if p != ""]
            try:
                value = float(trimmed[-1])
                price = float(trimmed[-2])
                shares = float(trimmed[-3])
            except (ValueError, IndexError):
                continue
            symbol = trimmed[-4]
            name = ",".join(trimmed[1:-4]) if len(trimmed) > 5 else trimmed[1]
            rows.append({
                "account_number": acct,
                "name": name.strip(),
                "symbol": symbol.strip(),
                "shares": shares,
                "price": price,
                "value": value,
            })
    return pd.DataFrame(rows)


def load_card_alerts(data_dir: Path) -> pd.DataFrame:
    """Chase transaction-alert emails, parsed into pending card rows.

    Written by `tools/sync_alerts.py` (Gmail API fetch) or `tools/ingest_alerts.py` (a saved export).
    These are authorisations, not settled charges, so `metrics` keeps them strictly
    in the pending lane and lets the card CSV supersede them per card.
    """
    cols = ["alert_id", "notification_id", "datetime", "date", "card_id", "merchant",
            "amount", "amount_cents", "kind", "issuer", "subject"]
    files = [f for f in _files(data_dir, "alerts", "*.csv")
             if not f.name.endswith(".migrated")]
    if not files:
        return pd.DataFrame(columns=cols)
    frames, mtimes = [], []
    for f in files:
        df = pd.read_csv(f, dtype={"card_id": str})
        mtimes.append(f.stat().st_mtime)
        if df.empty:
            continue
        frames.append(df)
    if not frames:
        return pd.DataFrame(columns=cols)
    out = pd.concat(frames, ignore_index=True)
    out["date"] = pd.to_datetime(out["date"], errors="coerce")
    out["datetime"] = pd.to_datetime(out["datetime"], errors="coerce")
    out["amount"] = pd.to_numeric(out["amount"], errors="coerce").fillna(0.0)
    out["card_id"] = out["card_id"].astype(str).str.zfill(4)
    out = out.dropna(subset=["date"])
    # the Gmail message id is the natural key, so re-ingesting a window is safe
    out = out.drop_duplicates(subset=["alert_id"]).sort_values("datetime").reset_index(drop=True)
    # when the mailbox was last swept -- distinct from when a transaction happened
    out["_ingested_at"] = pd.Timestamp.fromtimestamp(max(mtimes)) if mtimes else pd.NaT
    return out


def load_alert_review(data_dir: Path) -> list:
    """Alerts the parser refused to count, kept visible rather than dropped.

    A silently discarded alert is indistinguishable from a quieter month, so the
    parser quarantines anything ambiguous and the dashboard reports the backlog.
    """
    path = data_dir / "alerts" / "review.json"
    if not path.exists():
        return []
    try:
        rows = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return []
    return rows if isinstance(rows, list) else []


def load_statement_balances(data_dir: Path) -> list:
    """Balances scraped from 'statement is ready' emails.

    The only automatic figure a card without transaction alerts can offer. It is a
    balance at a closing date, not spending, and is labelled that way.
    """
    path = data_dir / "alerts" / "statement-balances.json"
    if not path.exists():
        return []
    try:
        rows = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return []
    return rows if isinstance(rows, list) else []
