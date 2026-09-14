"""The reconciliation rules from docs/DESIGN.md Sec.5. This is the core of the project -- follow it exactly."""
import pandas as pd

BUCKET_INTERNAL_TRANSFER = "INTERNAL_TRANSFER"
BUCKET_INVESTING = "INVESTING"
BUCKET_FAMILY = "FAMILY"
BUCKET_FAMILY_CREDIT = "FAMILY_CREDIT"  # money received back from the family account (nets against support)
BUCKET_CARD_PAYMENT = "CARD_PAYMENT"
BUCKET_DIRECT_SPEND = "DIRECT_SPEND"
BUCKET_LOAN_OUT = "LOAN_OUT"          # principal lent to a person -- an asset, never spending


def _loan_out_match(description: str, date, config: dict) -> bool:
    """True if this debit is principal going out on a tracked loan (config `loans_out`).

    Lending money is a balance-sheet move, not consumption: the cash leaves but an equal
    receivable arrives, so counting it as spending would blow up the spend average and the
    savings rate for a month in which nothing was actually consumed. Matches are deliberately
    narrow -- a description keyword AND a date window -- so an ordinary transfer that happens to
    share a descriptor (every other "Transfer to Venmo") is never swept up.
    """
    desc_l = str(description).lower()
    d = pd.Timestamp(date).normalize()
    for loan in config.get("loans_out", []) or []:
        for m in loan.get("match", []) or []:
            if str(m.get("desc", "")).lower() not in desc_l:
                continue
            lo, hi = m.get("from"), m.get("to")
            if lo is not None and d < pd.Timestamp(lo):
                continue
            if hi is not None and d > pd.Timestamp(hi):
                continue
            return True
    return False


def _classify_debit(description: str, parent_category: str, config: dict) -> str:
    desc = str(description)
    desc_l = desc.lower()

    internal_descs = {d.lower() for d in config["bank_internal_transfer_descriptions"]}
    if desc_l in internal_descs or desc_l.startswith("comment"):
        return BUCKET_INTERNAL_TRANSFER

    if parent_category == "Investments" or config["investing_desc_match"].lower() in desc_l:
        return BUCKET_INVESTING

    if config["entities"]["family_desc_match"].lower() in desc_l:
        return BUCKET_FAMILY

    card_payment_matches = config.get("card_payment_desc_matches") or [config.get("card_payment_desc_match", "")]
    if any(m and m.lower() in desc_l for m in card_payment_matches):
        return BUCKET_CARD_PAYMENT

    return BUCKET_DIRECT_SPEND


def reconcile_bank(bank_df: pd.DataFrame, config: dict) -> pd.DataFrame:
    """Adds a `bucket` column: one of the 5 debit buckets, or INCOME / OTHER_CREDIT for credits."""
    df = bank_df.copy()

    family_match = config["entities"]["family_desc_match"].lower()

    def bucket_row(row):
        if row["Type"] == "Debit":
            if _loan_out_match(row["Description"], row["Date"], config):
                return BUCKET_LOAN_OUT
            return _classify_debit(row["Description"], row.get("Parent Category"), config)
        if row["Type"] == "Credit":
            if row.get("Parent Category") == "Income":
                return "INCOME"
            # money coming back from the family account -- offsets family support, not other income
            if family_match in str(row["Description"]).lower():
                return BUCKET_FAMILY_CREDIT
            return "OTHER_CREDIT"
        return "UNKNOWN"

    df["bucket"] = df.apply(bucket_row, axis=1)

    # split the INCOME bucket into payroll vs everything else (see salary_by_month)
    payroll = [p.lower() for p in config.get("payroll_desc_matches", [])]

    def is_salary(row):
        if row["bucket"] != "INCOME":
            return False
        blob = f"{row['Description']} {row.get('Original Description', '')} {row.get('Memo', '')}".lower()
        return any(p in blob for p in payroll)

    df["is_salary"] = df.apply(is_salary, axis=1)
    df["month"] = df["Date"].dt.to_period("M")
    return df


def reconcile_cards(cards_df: pd.DataFrame) -> pd.DataFrame:
    """Adds `is_purchase` (Type == Sale) and a positive `spend_amount` for purchases."""
    df = cards_df.copy()
    df["is_purchase"] = df["Type"] == "Sale"
    df["spend_amount"] = 0.0
    df.loc[df["is_purchase"], "spend_amount"] = df.loc[df["is_purchase"], "Amount"].abs()
    df["month"] = df["Transaction Date"].dt.to_period("M")
    return df


def reconcile_venmo(venmo_df: pd.DataFrame, config: dict) -> pd.DataFrame:
    """Excludes Standard Transfer (bank<->Venmo, internal); tags fruit/movies/rent/settled loan,
    plus loan principal and one-off events, which are not consumption and are excluded from the
    category split in metrics.compute_metrics."""
    df = venmo_df[venmo_df["Type"] != "Standard Transfer"].copy()
    df = df[df["Type"].isin(["Payment", "Charge"])].copy()

    entities = config["entities"]

    def tag(counterparty):
        cp = str(counterparty)
        if entities["fruit_vendor"].lower() in cp.lower():
            return "fruit"
        if entities["movie_buddy"].lower() in cp.lower():
            return "movies"
        if any(r.lower() in cp.lower() for r in entities["rent_recipients_venmo"]):
            return "rent_historical"
        if any(r.lower() in cp.lower() for r in entities.get("loan_recipients_venmo", [])):
            return "loan_out"
        if any(r.lower() in cp.lower() for r in entities.get("event_recipients_venmo", [])):
            return "event"
        if entities.get("settled_loan_desc_match") and entities["settled_loan_desc_match"].lower() in cp.lower():
            return "loan_settled"
        return "other"

    df["entity_tag"] = df["counterparty"].apply(tag)
    df["year"] = df["Datetime"].dt.year
    df["month"] = df["Datetime"].dt.to_period("M")
    return df


def total_spend_by_month(bank_df: pd.DataFrame, cards_df: pd.DataFrame) -> pd.Series:
    """Accrual-basis total spend = bank DIRECT_SPEND + card purchases, per month. Never adds CARD_PAYMENT (double-count)."""
    bank_direct = (
        bank_df[bank_df["bucket"] == BUCKET_DIRECT_SPEND].groupby("month")["Amount"].sum()
    )
    card_spend = cards_df[cards_df["is_purchase"]].groupby("month")["spend_amount"].sum()
    return bank_direct.add(card_spend, fill_value=0.0).sort_index()


def income_by_month(bank_df: pd.DataFrame) -> pd.Series:
    return bank_df[bank_df["bucket"] == "INCOME"].groupby("month")["Amount"].sum().sort_index()


def salary_by_month(bank_df: pd.DataFrame) -> pd.Series:
    """Payroll only. Everything else in the INCOME bucket -- a settlement payout, a deposited check,
    a refund -- is real money but not the paycheck, and it distorts a savings rate meant to answer
    'does what I earn cover how I live?'"""
    df = bank_df[(bank_df["bucket"] == "INCOME") & bank_df["is_salary"]]
    return df.groupby("month")["Amount"].sum().sort_index()


def nonsalary_income_rows(bank_df: pd.DataFrame) -> pd.DataFrame:
    """The individual non-payroll deposits, so the dashboard can name them rather than just net
    them out (an unexplained $3.3k arriving is itself worth surfacing)."""
    df = bank_df[(bank_df["bucket"] == "INCOME") & ~bank_df["is_salary"]]
    return df.sort_values("Date", ascending=False)


def family_by_month(bank_df: pd.DataFrame) -> pd.Series:
    """Net family support = transfers TO the family account minus money received back from it. Money
    is sometimes cycled through that account, so gross out-transfers overstate the actual support given."""
    out = bank_df[bank_df["bucket"] == BUCKET_FAMILY].groupby("month")["Amount"].sum()
    back = bank_df[bank_df["bucket"] == BUCKET_FAMILY_CREDIT].groupby("month")["Amount"].sum()
    net = out.subtract(back, fill_value=0.0)
    return net.sort_index()


def investing_by_month(bank_df: pd.DataFrame) -> pd.Series:
    return bank_df[bank_df["bucket"] == BUCKET_INVESTING].groupby("month")["Amount"].sum().sort_index()
