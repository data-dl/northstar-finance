"""Generate a complete, internally consistent set of raw exports for the sample household.

Everything the loaders in finlib/loaders.py read is produced here, in the exact shapes the
real exports have: the credit union's transaction CSV, Chase activity CSVs, Amazon order
history, Venmo yearly statements, Chewy's scraped order list, balance snapshots, a Vanguard
positions export, statement summaries and issuer transaction alerts.

The generator is deliberately stdlib-only and seeded, so `python -m synth` writes the same
bytes every time. Money is generated in cents and only formatted at the edge.
"""
from __future__ import annotations

import csv
import datetime as dt
import hashlib
import json
import random
from collections import defaultdict
from pathlib import Path

from synth import persona as P

BANK_COLUMNS = ["Date", "Description", "Original Description", "Amount", "Type", "Parent Category",
                "Category", "Account", "Tags", "Memo", "Pending"]
CARD_COLUMNS = ["Transaction Date", "Post Date", "Description", "Category", "Type", "Amount", "Memo"]
AMAZON_COLUMNS = ["order id", "order url", "order date", "quantity", "description", "item url", "price",
                  "subscribe & save", "ASIN"]
CHEWY_COLUMNS = ["client-date", "styles_orderId__9auMd", "styles_orderTotal__W2t1h",
                 "styles_orderStatusContentMessage__mXOb7", "kib-product-title__text",
                 "styles_itemContentTitleName__vouPu", "kib-product-price__dollars", "kib-product-price__cents",
                 "kib-product-title__text 2", "styles_itemContentTitleName__vouPu 2",
                 "kib-product-price__dollars 2", "kib-product-price__cents 2"]
VENMO_COLUMNS = ["", "ID", "Datetime", "Type", "Status", "Note", "From", "To", "Amount (total)", "Amount (tip)",
                 "Amount (tax)", "Amount (fee)", "Tax Rate", "Tax Exempt", "Funding Source", "Destination",
                 "Beginning Balance", "Ending Balance", "Statement Period Venmo Fees", "Terminal Location",
                 "Year to Date Venmo Fees", "Disclaimer"]
ALERT_COLUMNS = ["alert_id", "notification_id", "datetime", "date", "card_id", "merchant", "amount",
                 "amount_cents", "kind", "issuer", "subject"]

CITY = "LAKEVIEW OH"
CHECKING, SAVINGS = "FREE CHECKING", "SHARE SAVINGS"


def r2(x: float) -> float:
    return round(float(x) + 1e-9, 2)


def money(x: float) -> str:
    return f"{r2(x):.2f}"


def months_between(a: dt.date, b: dt.date):
    y, m = a.year, a.month
    while dt.date(y, m, 1) <= b:
        yield dt.date(y, m, 1)
        m += 1
        if m == 13:
            y, m = y + 1, 1


def days_in(month: dt.date) -> int:
    nxt = dt.date(month.year + (month.month == 12), month.month % 12 + 1, 1)
    return (nxt - month).days


def clamp_day(month: dt.date, day: int) -> dt.date:
    return dt.date(month.year, month.month, min(day, days_in(month)))


def title_merchant(desc: str) -> str:
    """The credit union's cleaned Description: title case, store numbers dropped."""
    words = [w for w in desc.split() if not (w.startswith("#") or w.replace("*", "").isdigit())]
    out = " ".join(words).title().replace("'S", "'s")
    return out


class Rng:
    def __init__(self, seed: int):
        self.r = random.Random(seed)

    def poisson(self, lam: float) -> int:
        if lam <= 0:
            return 0
        l, k, p = pow(2.718281828459045, -lam), 0, 1.0
        while True:
            k += 1
            p *= self.r.random()
            if p <= l:
                return k - 1

    def amount(self, lo: float, hi: float) -> float:
        return r2(self.r.uniform(lo, hi))

    def choice(self, seq):
        return self.r.choice(seq)

    def weighted(self, pairs):
        total = sum(w for _, w in pairs)
        x = self.r.random() * total
        for item, w in pairs:
            x -= w
            if x <= 0:
                return item
        return pairs[-1][0]

    def day(self, month: dt.date, lo: int = 1, hi: int | None = None) -> dt.date:
        return dt.date(month.year, month.month, self.r.randint(lo, hi or days_in(month)))

    def uniform(self, a, b):
        return self.r.uniform(a, b)

    def random(self):
        return self.r.random()

    def randint(self, a, b):
        return self.r.randint(a, b)


# ---------------------------------------------------------------------------------------------
# purchases
# ---------------------------------------------------------------------------------------------
class Purchase:
    __slots__ = ("date", "desc", "amount", "chase_cat", "channel", "bank_parent", "bank_cat", "kind")

    def __init__(self, date, desc, amount, chase_cat, channel, bank_parent="Food & Dining", bank_cat="", kind="Sale"):
        self.date, self.desc, self.amount, self.chase_cat = date, desc, r2(amount), chase_cat
        self.channel, self.bank_parent, self.bank_cat, self.kind = channel, bank_parent, bank_cat, kind


def deli_ticket(rng: Rng) -> float:
    basket = rng.weighted(P.DELI_BASKETS)
    pre = sum(P.DELI_ITEMS[i] for i in basket)
    return r2(pre * (1 + P.DELI_TAX))


def everyday_purchases(rng: Rng, months) -> list[Purchase]:
    """Corner stores, restaurants, groceries, transit, drugstores, entertainment, Target.

    Before the card pivot most of this ran on the debit card; afterwards nearly all of it is on
    the Freedom. Groceries rise and eating out falls once cooking starts."""
    out = []

    def channel(date: dt.date) -> str:
        on_card = rng.random() < (0.94 if date >= P.CARD_PIVOT else 0.16)
        return "freedom" if on_card else "debit"

    for m in months:
        end_day = days_in(m)
        if m.year == P.CARD_EXPORT.year and m.month == P.CARD_EXPORT.month:
            end_day = P.CARD_EXPORT.day
        cooking = m >= dt.date(P.COOKING_STARTED.year, P.COOKING_STARTED.month, 1)
        # corner stores
        n = rng.poisson(19.0 * (end_day / days_in(m)))
        for _ in range(n):
            d = rng.day(m, 1, end_day)
            out.append(Purchase(d, P.DELI, deli_ticket(rng), "Groceries", channel(d), "Food & Dining", "Convenience"))
        for desc, rate, lo, hi in P.SNACK_STORES:
            for _ in range(rng.poisson(rate * end_day / days_in(m))):
                d = rng.day(m, 1, end_day)
                out.append(Purchase(d, desc, rng.amount(lo, hi), "Groceries", channel(d), "Food & Dining", "Convenience"))
        # restaurants and groceries, with the cooking pivot
        eat_scale = 0.82 if cooking else 1.38
        groc_scale = 1.16 if cooking else 0.78
        for desc, rate, lo, hi, cat in P.RESTAURANTS:
            for _ in range(rng.poisson(rate * P.RESTAURANT_SCALE * eat_scale * end_day / days_in(m))):
                d = rng.day(m, 1, end_day)
                out.append(Purchase(d, desc, rng.amount(lo, hi), cat, channel(d), "Food & Dining", "Restaurants"))
        for desc, rate, lo, hi, cat in P.GROCERS:
            for _ in range(rng.poisson(rate * groc_scale * end_day / days_in(m))):
                d = rng.day(m, 1, end_day)
                out.append(Purchase(d, desc, rng.amount(lo, hi), cat, channel(d), "Food & Dining", "Groceries"))
        for desc, rate, lo, hi, cat in P.DRUGSTORES:
            for _ in range(rng.poisson(rate * end_day / days_in(m))):
                d = rng.day(m, 1, end_day)
                out.append(Purchase(d, desc, rng.amount(lo, hi), cat, channel(d), "Health & Fitness", "Pharmacy"))
        for desc, rate, lo, hi, cat in P.ENTERTAINMENT:
            for _ in range(rng.poisson(rate * end_day / days_in(m))):
                d = rng.day(m, 1, end_day)
                out.append(Purchase(d, desc, rng.amount(lo, hi), cat, channel(d), "Entertainment", "Movies & Music"))
        # transit taps come in pairs on the same day, like a commute
        for _ in range(rng.poisson(P.TRANSIT_TAPS_PER_MONTH / 2 * end_day / days_in(m))):
            d = rng.day(m, 1, end_day)
            ch = channel(d)
            for _ in range(2):
                out.append(Purchase(d, P.TRANSIT_TAP[0], P.TRANSIT_TAP[1], P.TRANSIT_TAP[2], ch, "Auto & Transport", "Public Transit"))
        for desc, rate, lo, hi, cat in (P.LYFT, P.PARKING):
            for _ in range(rng.poisson(rate * end_day / days_in(m))):
                d = rng.day(m, 1, end_day)
                suffix = " " + rng.choice(["MON 6PM", "TUE 8AM", "FRI 11PM", "SAT 2PM", "SUN 1PM"]) if desc.startswith("LYFT") else ""
                out.append(Purchase(d, desc + suffix, rng.amount(lo, hi), cat, channel(d), "Auto & Transport", "Rideshare"))
        desc, rate, lo, hi, cat = P.TARGET
        for _ in range(rng.poisson(rate * end_day / days_in(m))):
            d = rng.day(m, 1, end_day)
            out.append(Purchase(d, desc, rng.amount(lo, hi), cat, channel(d), "Shopping", "General Merchandise"))
    return out


def fixed_card_purchases(months_end: dt.date) -> list[Purchase]:
    out = []
    for desc, amount, day, card, first, last in P.SUBSCRIPTIONS:
        for m in months_between(first, last or months_end):
            d = clamp_day(m, day)
            if d > months_end:
                continue
            cat = "Bills & Utilities" if desc in ("MINT MOBILE", "BLUEPINE HOSTING", "LEMONADE INSURANCE") else "Entertainment"
            out.append(Purchase(d, desc, amount, cat, "freedom" if card == P.FREEDOM else "prime", "Bills & Utilities", "Subscription"))
    chase_cat = {"AMAZON PRIME": "Shopping", "MICROSOFT": "Professional Services", "AAA": "Professional Services",
                 "COSTCO": "Shopping", "DOMAIN": "Professional Services", "RIDGELINE": "Health & Wellness",
                 "LAKEVIEW REC": "Entertainment", "LAKEVIEW AQ": "Entertainment", "DENTAL": "Health & Wellness",
                 "URGENT": "Health & Wellness", "MINUTECLINIC": "Health & Wellness", "VIOLATIONS": "Professional Services",
                 "LIBRARY": "Entertainment", "MUSEUM": "Entertainment", "AMTRAK": "Travel", "SHELL": "Gas",
                 "TURBOTAX": "Professional Services", "BEST BUY": "Shopping", "IKEA": "Home", "GOODWILL": "Shopping",
                 "WWW COSTCO": "Shopping", "TARGET": "Shopping"}
    for desc, amount, dates, card in P.ANNUALS:
        cat = next((v for k, v in chase_cat.items() if k in desc), "Shopping")
        for d in dates:
            if d <= months_end:
                out.append(Purchase(d, desc, amount, cat, "freedom" if card == P.FREEDOM else "prime", "Shopping", "General Merchandise"))
    for desc, amount, d, card in P.CARD_RETURNS:
        out.append(Purchase(d, desc, amount, "Shopping", "freedom" if card == P.FREEDOM else "prime", kind="Return"))
    return out


# ---------------------------------------------------------------------------------------------
# Amazon
# ---------------------------------------------------------------------------------------------
def amazon_orders(rng: Rng, start: dt.date, end: dt.date):
    """Returns (rows, purchases). Each order becomes one Prime Visa charge a day later."""
    by_hint = defaultdict(list)
    for item in P.AMAZON_ITEMS:
        by_hint[item[2]].append(item)
    hint_weights = [("household", 5), ("toiletries", 4), ("health", 3), ("grocery", 3), ("kitchen", 2),
                    ("electronics", 2), ("clothing", 2), ("books", 1), ("office", 1), ("home", 1)]
    rows, purchases, order_no = [], [], 0

    def order_id(d: dt.date, n: int) -> str:
        h = hashlib.md5(f"{d}-{n}".encode()).hexdigest()
        return f"112-{int(h[:7], 16) % 10_000_000:07d}-{int(h[7:14], 16) % 10_000_000:07d}"

    def emit(d: dt.date, items):
        nonlocal order_no
        order_no += 1
        oid = order_id(d, order_no)
        subtotal = 0.0
        for desc, price, qty, asin, sns in items:
            subtotal += price * qty
            rows.append({
                "order id": oid,
                "order url": f"https://www.amazon.com/your-orders/order-details?orderID={oid}",
                "order date": d.isoformat(), "quantity": qty, "description": desc,
                "item url": f"https://www.amazon.com/dp/{asin}", "price": f"${price:.2f}",
                "subscribe & save": sns, "ASIN": asin,
            })
        charge_day = d + dt.timedelta(days=1)
        code = hashlib.md5(oid.encode()).hexdigest()[:9].upper()
        purchases.append(Purchase(charge_day, f"AMAZON MKTPL*{code}", r2(subtotal * 1.0675), "Shopping", "prime",
                                  "Shopping", "Online"))

    for m in months_between(start, end):
        # the standing Subscribe & Save energy-drink case, mid-month
        d = clamp_day(m, rng.randint(9, 14))
        if start <= d <= end:
            desc, price, _, asin = P.AMAZON_ITEMS[0]
            emit(d, [(desc, price, 1, asin, 1)])
        for _ in range(rng.poisson(2.1)):
            d = rng.day(m)
            if not (start <= d <= end):
                continue
            n_items = rng.weighted([(1, 5), (2, 4), (3, 2)])
            items = []
            for _ in range(n_items):
                hint = rng.weighted(hint_weights)
                desc, price, _, asin = rng.choice(by_hint[hint])
                qty = 2 if (hint in ("household", "grocery") and rng.random() < 0.15) else 1
                items.append((desc, price, qty, asin, 0))
            emit(d, items)
    one_offs = defaultdict(list)
    for d, desc, price, asin in P.AMAZON_ONE_OFFS:
        if start <= d <= end:
            one_offs[d].append((desc, price, 1, asin, 0))
    for d in sorted(one_offs):
        emit(d, one_offs[d])
    rows.sort(key=lambda r: r["order date"], reverse=True)
    return rows, purchases


# ---------------------------------------------------------------------------------------------
# Venmo
# ---------------------------------------------------------------------------------------------
def venmo_history(rng: Rng, through: dt.date):
    """Eleven years of statements: roommate rent, the 2023 loan, then a lean present."""
    rows = []          # dicts with year, datetime, type, note, frm, to, amount, funding
    counter = [0]

    def vid(when: dt.datetime) -> str:
        counter[0] += 1
        h = hashlib.md5(f"{when.isoformat()}-{counter[0]}".encode()).hexdigest()
        return str(4000000000000000000 + int(h[:15], 16) % 900000000000000000)

    def pay(d: dt.date, to: str, amount: float, note: str, charge=False, funding="Lakeshore Credit Union Checking"):
        when = dt.datetime(d.year, d.month, d.day, rng.randint(8, 22), rng.randint(0, 59), rng.randint(0, 59))
        rows.append({"year": d.year, "when": when, "type": "Charge" if charge else "Payment", "note": note,
                     "frm": to if charge else P.OWNER, "to": P.OWNER if charge else to,
                     "amount": -r2(amount), "funding": funding})

    def receive(d: dt.date, frm: str, amount: float, note: str):
        when = dt.datetime(d.year, d.month, d.day, rng.randint(8, 22), rng.randint(0, 59), rng.randint(0, 59))
        rows.append({"year": d.year, "when": when, "type": "Payment", "note": note, "frm": frm, "to": P.OWNER,
                     "amount": r2(amount), "funding": ""})

    social_notes = ["Dinner", "Foodsies", "Beersies", "Brunch", "Split the tab", "Tacos", "Pizza night", "Concert tix",
                    "Groceries for the party", "Uber home", "Trivia night", "Ramen", "Coffee", "Bowling"]
    # 2015: social only, from August
    for _ in range(14):
        d = dt.date(2015, rng.randint(8, 12), rng.randint(1, 28))
        pay(d, rng.choice(["Sam Iyer", "Priya Natarajan"]), rng.amount(60, 180), rng.choice(social_notes), charge=rng.random() < 0.4)
    # 2017-2021: rent to roommates on the 1st, plus a social life
    for name, first, last, rent in P.RENT_ROOMMATES:
        for m in months_between(first, last):
            pay(dt.date(m.year, m.month, 1), name, rent, "Rent", charge=True)
    for year in range(2017, 2022):
        for _ in range(rng.randint(10, 16)):
            d = dt.date(year, rng.randint(1, 12), rng.randint(1, 28))
            pay(d, rng.choice(["Sam Iyer", "Jo Park", "Alex Carver"]), rng.amount(12, 95), rng.choice(social_notes), charge=rng.random() < 0.5)
        for _ in range(rng.randint(2, 5)):
            d = dt.date(year, rng.randint(1, 12), rng.randint(1, 28))
            receive(d, rng.choice(["Sam Iyer", "Jo Park"]), rng.amount(10, 60), rng.choice(social_notes))
    # 2022: the move to Lakeview; rent goes through the bank from here
    for _ in range(18):
        d = dt.date(2022, rng.randint(1, 12), rng.randint(1, 28))
        pay(d, rng.choice(["Sam Iyer", "Jo Park", "Dana Whitfield"]), rng.amount(15, 120), rng.choice(social_notes), charge=rng.random() < 0.5)
    # 2023: the loan -- the careful "send $1 to test" pattern, then the real amounts
    pay(dt.date(2023, 2, 3), P.SETTLED_LOAN, 1.00, "test")
    pay(dt.date(2023, 2, 3), P.SETTLED_LOAN, 2999.00, "loan")
    pay(dt.date(2023, 2, 6), P.SETTLED_LOAN, 5000.00, "loan pt 2")
    pay(dt.date(2023, 2, 10), P.SETTLED_LOAN, 5000.00, "loan pt 3")
    pay(dt.date(2023, 3, 1), P.SETTLED_LOAN, 5000.00, "loan pt 4")
    receive(dt.date(2023, 8, 14), P.SETTLED_LOAN, 1500.00, "paying you back")
    receive(dt.date(2023, 10, 20), P.SETTLED_LOAN, 2000.00, "more")
    receive(dt.date(2023, 12, 22), P.SETTLED_LOAN, 2560.00, "rest on venmo, the remainder by check")
    for _ in range(16):
        d = dt.date(2023, rng.randint(1, 12), rng.randint(1, 28))
        pay(d, rng.choice(["Sam Iyer", "Jo Park"]), rng.amount(15, 110), rng.choice(social_notes), charge=rng.random() < 0.5)
    # 2024 -> today: fruit cart monthly, movies with Jo, shared meals, a couple of trips with Alex
    for m in months_between(dt.date(2024, 1, 1), through):
        end_day = through.day if (m.year, m.month) == (through.year, through.month) else days_in(m)
        if m >= dt.date(2024, 7, 1) and rng.random() < 0.85:
            d = rng.day(m, 1, end_day)
            pay(d, P.FRUIT_VENDOR, rng.weighted([(6.0, 3), (7.0, 4), (8.0, 3), (9.5, 1)]), "fruit")
        if rng.random() < 0.8:
            d = rng.day(m, 1, end_day)
            pay(d, P.MOVIE_BUDDY, rng.weighted([(18.5, 3), (23.5, 4), (27.0, 2)]), rng.choice(["Movie", "Tickets", "Matinee", "IMAX"]), charge=True)
        for _ in range(rng.poisson(0.6)):
            d = rng.day(m, 1, end_day)
            pay(d, rng.choice(P.MEAL_FRIENDS), rng.amount(12, 48), rng.choice(social_notes), charge=rng.random() < 0.5)
        if rng.random() < 0.15:
            d = rng.day(m, 1, end_day)
            receive(d, rng.choice(P.MEAL_FRIENDS), rng.amount(10, 45), rng.choice(social_notes))
    pay(dt.date(2024, 3, 16), "Alex Carver", 144.00, "cabin split")
    pay(dt.date(2024, 8, 24), "Alex Carver", 144.00, "camping share")
    if through >= dt.date(2026, 9, 2):
        pay(dt.date(2026, 9, 2), P.EVENT_FRIEND, 210.00, "cabin weekend share")
    rows.sort(key=lambda r: r["when"])
    return rows


# ---------------------------------------------------------------------------------------------
# bank
# ---------------------------------------------------------------------------------------------
def bank_rows(rng: Rng, purchases: list[Purchase], venmo_rows, card_payments) -> list[dict]:
    rows = []

    def add(d, desc, orig, amount, typ, parent, cat, account=CHECKING, memo=""):
        rows.append({"Date": d.strftime("%m/%d/%Y"), "Description": desc, "Original Description": orig,
                     "Amount": money(amount), "Type": typ, "Parent Category": parent, "Category": cat,
                     "Account": account, "Tags": "", "Memo": memo or orig.split(" / ", 1)[-1], "Pending": "FALSE",
                     "_date": d})

    # payroll
    d = P.FIRST_PAYDAY
    while d <= P.BANK_END:
        add(d, P.PAYROLL_DESC, P.PAYROLL_ORIG, P.PAY_NET, "Credit", "Income", "Paycheck")
        d += dt.timedelta(days=14)
    for d, desc, orig, amount in P.NONSALARY_INCOME:
        add(d, desc, orig, amount, "Credit", "Income", "Other Income")

    months = list(months_between(P.BANK_START, P.BANK_END))
    for m in months:
        # rent
        desc, orig, amount = P.RENT_NEW if m >= P.RENT_SWITCH else P.RENT_OLD
        add(dt.date(m.year, m.month, 1), desc, orig, amount, "Debit", "Home", "Rent")
        # bills
        for desc, orig, parent, cat, day, amount in P.BILLS:
            if amount is None:
                if desc == "Vantel Fiber":
                    amount = 49.00 if m >= dt.date(2026, 1, 1) else 45.00
                elif desc == "Lakeview Power & Light":
                    season = 1.0 + 0.55 * max(0.0, 1 - abs(m.month - 7.5) / 3.5)   # summer peak
                    amount = r2(rng.uniform(58, 74) * season)
                else:   # gas, winter peak
                    season = 1.0 + 0.9 * max(0.0, 1 - min(abs(m.month - 1.5), abs(m.month - 13.5)) / 4)
                    amount = r2(rng.uniform(17, 26) * season)
            add(clamp_day(m, day), desc, orig, amount, "Debit", parent, cat)
        if m.month in (1, 4, 7, 10):
            desc, orig, parent, cat, day, amount = P.LIFE_INSURANCE
            add(clamp_day(m, day), desc, orig, amount, "Debit", parent, cat)
        # family support
        fam = P.FAMILY_OVERRIDES.get((m.year, m.month), P.FAMILY_MONTHLY)
        if fam:
            add(clamp_day(m, 5), P.FAMILY_TRANSFER, f"Withdrawal ZELLE TO LINDA MORGAN / TYPE: P2P CO: ZELLE %% ACH ECC WEB",
                fam, "Debit", "Transfer", "Zelle")
        # brokerage buys out of savings
        add(clamp_day(m, rng.randint(2, 6)), "Vanguard Buy", "Withdrawal VANGUARD BUY / TYPE: INVESTMENT CO: VMC %% ACH ECC WEB",
            rng.weighted([(1000.0, 3), (1200.0, 4), (1500.0, 2), (900.0, 1)]), "Debit", "Investments", "Investment", SAVINGS)
        # month-end checking -> savings sweep, mirrored on both accounts
        sweep = rng.weighted([(500.0, 5), (750.0, 3), (400.0, 2)])
        last = clamp_day(m, 31)
        add(last, "Transfer To Share", "Transfer To Share 0001", sweep, "Debit", "Transfer", "Transfer", CHECKING)
        add(last, "Transfer from Account 0072", "Transfer from Share 0072", sweep, "Credit", "Transfer", "Transfer", SAVINGS)
        if rng.random() < 0.2:   # occasional top-up back into checking
            back = rng.weighted([(300.0, 2), (200.0, 3)])
            d = clamp_day(m, rng.randint(12, 26))
            add(d, "Transfer to Share 0072", "Transfer to Share 0072", back, "Debit", "Transfer", "Transfer", SAVINGS)
            add(d, "Transfer from Share 0001", "Transfer from Share 0001", back, "Credit", "Transfer", "Transfer", CHECKING)
        # cash
        for _ in range(rng.poisson(0.85)):
            d = rng.day(m)
            add(d, "ATM Withdrawal Lakeshore CU", "ATM Withdrawal LAKESHORE CU MAIN ST LAKEVIEW OH",
                rng.weighted([(40.0, 5), (60.0, 3), (20.0, 2)]), "Debit", "Uncategorized", "Cash")
        if rng.random() < 0.3:
            d = rng.day(m)
            add(d, "ATM Withdrawal #4471 Fourth Street", f"ATM Withdrawal #4471 FOURTH STREET {CITY}", 20.0, "Debit", "Uncategorized", "Cash")
            add(d, "ATM Surcharge", "ATM Surcharge FOURTH STREET", 3.00, "Debit", "Fees & Charges", "ATM Fee")
    # one-offs
    d, desc, orig, amount = P.STATE_TAX_PAYMENT
    add(d, desc, orig, amount, "Debit", "Taxes", "State Tax")
    add(P.LOAN_DATE, f"Zelle to {P.LOAN_BORROWER}", f"Withdrawal ZELLE TO {P.LOAN_BORROWER.upper()} / TYPE: P2P CO: ZELLE %% ACH ECC WEB",
        P.LOAN_PRINCIPAL, "Debit", "Transfer", "Zelle", SAVINGS)
    # card autopays and the Discover/Capital One card
    for d, card, amount in card_payments:
        name = P.CARDS[card]
        add(d, "Chase Credit Card", f"Withdrawal CHASE CREDIT CRD / TYPE: AUTOPAY ID: XXXXXX{card} CO: CHASE CREDIT CRD %% ACH ECC WEB",
            amount, "Debit", "Transfer", "Credit Card Payment")
    for d, desc, orig, amount in [(dt.date(2025, 11, 24), "Discover Card Payment", "Withdrawal DISCOVER / TYPE: E-PAYMENT CO: DISCOVER %% ACH ECC WEB", 96.40),
                                  (dt.date(2026, 3, 24), "Discover Card Payment", "Withdrawal DISCOVER / TYPE: E-PAYMENT CO: DISCOVER %% ACH ECC WEB", 118.75),
                                  (dt.date(2026, 8, 24), "Capital One Card Payment", "Withdrawal CAPITAL ONE / TYPE: CRCARDPMT CO: CAPITAL ONE %% ACH ECC WEB", 150.00)]:
        add(d, desc, orig, amount, "Debit", "Transfer", "Credit Card Payment")
    # Venmo funding: every bank-funded payment inside the window pulls the same amount the same day
    for v in venmo_rows:
        d = v["when"].date()
        if v["amount"] < 0 and v["funding"].startswith("Lakeshore") and P.BANK_START <= d <= P.BANK_END:
            add(d, "Transfer to Venmo", "Withdrawal VENMO / TYPE: PAYMENT CO: VENMO %% ACH ECC WEB", -v["amount"], "Debit", "Transfer", "Venmo")
    # debit-card swipes
    for pch in purchases:
        if pch.channel != "debit" or not (P.BANK_START <= pch.date <= P.BANK_END):
            continue
        clean = title_merchant(pch.desc)
        add(pch.date, clean, f"Debit Card DEBIT TRAN {pch.desc} {CITY}", pch.amount, "Debit", pch.bank_parent, pch.bank_cat)
    rows.sort(key=lambda r: (r["_date"], r["Description"]), reverse=True)
    return rows


# ---------------------------------------------------------------------------------------------
# cards, statements, balances
# ---------------------------------------------------------------------------------------------
def statement_periods(close_day: int, due_day: int, start: dt.date, end: dt.date):
    """Yield (period_start, close_date, due_date) for statements closing inside [start, end]."""
    prev_close = start - dt.timedelta(days=1)
    for m in months_between(start, end):
        close = clamp_day(m, close_day)
        if close < start or close > end:
            prev_close = close
            continue
        nxt = dt.date(m.year + (m.month == 12), m.month % 12 + 1, 1)
        yield prev_close + dt.timedelta(days=1), close, clamp_day(nxt, due_day)
        prev_close = close


def build_cards(purchases: list[Purchase]):
    """Split purchases per card, compute statements, autopays and current balances."""
    per_card = {P.FREEDOM: [], P.PRIME: []}
    for pch in purchases:
        if pch.channel in ("freedom", "prime") and pch.date <= P.CARD_EXPORT:
            per_card[P.FREEDOM if pch.channel == "freedom" else P.PRIME].append(pch)
    payments, statements, current = [], {}, {}
    for card, (close_day, due_day) in ((P.FREEDOM, (P.FREEDOM_CLOSE_DAY, P.FREEDOM_DUE_DAY)),
                                       (P.PRIME, (P.PRIME_CLOSE_DAY, P.PRIME_DUE_DAY))):
        rows = per_card[card]
        last = None
        for p_start, close, due in statement_periods(close_day, due_day, P.BANK_START, P.CARD_EXPORT):
            in_period = [p for p in rows if p_start <= p.date <= close]
            balance = r2(sum(p.amount if p.kind == "Sale" else -p.amount for p in in_period))
            if due <= P.CARD_EXPORT:
                payments.append((due, card, balance))
            last = (p_start, close, due, balance, in_period)
        p_start, close, due, balance, in_period = last
        unbilled = r2(sum(p.amount if p.kind == "Sale" else -p.amount for p in rows if close < p.date <= P.CARD_EXPORT))
        current[card] = r2(balance + unbilled)
        spend = sum(p.amount for p in in_period if p.kind == "Sale")
        if card == P.FREEDOM:
            earn = [{"label": "1% (1 Pt)/$1 earned on all purchases", "points": int(round(spend))}]
            previous = 8412
        else:
            amazon = sum(p.amount for p in in_period if p.kind == "Sale" and "AMAZON" in p.desc and "PRIME*" not in p.desc)
            earn = [{"label": "5% back on Amazon.com purchases", "points": int(round(amazon * 5))},
                    {"label": "5% back on Whole Foods Market purchases", "points": 0},
                    {"label": "2% back at gas stations", "points": 0},
                    {"label": "2% back at restaurants", "points": 0},
                    {"label": "2% back on local transit/commuting", "points": 0},
                    {"label": "1% back on all other purchases", "points": int(round(spend - amazon))}]
            previous = 2905
        earned = sum(e["points"] for e in earn)
        statements[card] = {"card_id": card, "statement_date": close.isoformat(), "statement_balance": balance,
                            "minimum_payment": r2(max(25.0, balance * 0.035)), "due_date": due.isoformat(),
                            "points": {"previous": previous, "redeemed": 0, "total": previous + earned, "earn_lines": earn}}
        for due, c, amount in payments:
            if c == card and amount > 0:
                rows.append(Purchase(due, "AUTOMATIC PAYMENT - THANK", amount, "", "freedom" if card == P.FREEDOM else "prime", kind="Payment"))
    return per_card, payments, statements, current


def card_csv_rows(rows: list[Purchase], through: dt.date, rng: Rng) -> list[dict]:
    out = []
    for p in sorted(rows, key=lambda p: (p.date, p.desc), reverse=True):
        if p.date > through:
            continue
        post = p.date + dt.timedelta(days=0 if p.kind == "Payment" else rng.weighted([(1, 5), (2, 4), (3, 1)]))
        amount = p.amount if p.kind in ("Payment", "Return") else -p.amount
        out.append({"Transaction Date": p.date.strftime("%m/%d/%Y"), "Post Date": post.strftime("%m/%d/%Y"),
                    "Description": p.desc, "Category": p.chase_cat, "Type": p.kind, "Amount": money(amount), "Memo": ""})
    return out


def vanguard_positions():
    positions, balances = [], {}
    for acct, (name, kind, fund, lots) in P.VANGUARD.items():
        total = 0.0
        for sym, shares in lots:
            if sym == "null":
                price, value, label = 1.00, r2(shares), "VANGUARD CASH PLUS"
            elif sym == "VFIFX":
                price, value, label = P.VFIFX_NAV, r2(shares * P.VFIFX_NAV), P.STOCK_NAMES["VFIFX"]
            elif sym == "VMFXX":
                price, value, label = 1.00, r2(shares), P.STOCK_NAMES["VMFXX"]
            else:
                price, value, label = P.STOCK_PX[sym], r2(shares * P.STOCK_PX[sym]), P.STOCK_NAMES[sym]
            positions.append((acct, label, sym, shares, price, value))
            total += value
        balances[acct] = r2(total)
    return positions, balances


# ---------------------------------------------------------------------------------------------
# writers
# ---------------------------------------------------------------------------------------------
def write_csv(path: Path, columns, rows, encoding="utf-8"):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding=encoding) as fh:
        w = csv.DictWriter(fh, fieldnames=columns, extrasaction="ignore", lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def write_venmo(path: Path, year: int, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow([f"Account Statement - ({P.VENMO_HANDLE}) "] + [""] * 21)
        w.writerow(["Account Activity"] + [""] * 21)
        w.writerow(VENMO_COLUMNS)
        w.writerow([""] * 16 + [f"${(year * 7919 % 20000) / 100:.2f}"] + [""] * 5)
        for r in rows:
            amt = r["amount"]
            sign = "-" if amt < 0 else "+"
            w.writerow(["", r["id"], r["when"].isoformat(timespec="seconds"), r["type"], "Complete", r["note"], r["frm"], r["to"],
                        f"{sign} ${abs(amt):,.2f}", "", "0", "", "0", "", r["funding"] or "Venmo balance", "", "", "", "", "Venmo", "", ""])
        w.writerow([""] * 17 + ["$0.00", "$0.00", "", "$0.00",
                    "In case of errors or questions about your electronic transfers, see the Cardholder Agreement (https://venmo.com/legal/cardholder-agreement)."])


def write_vanguard(path: Path, positions):
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["Account Number,Investment Name,Symbol,Shares,Share Price,Total Value,"]
    for acct, name, sym, shares, price, value in positions:
        lines.append(f"{acct},{name},{sym},{shares:g},{price:.2f},{value:.2f},")
    lines += ["", "", "Account Number,Trade Date,Settlement Date,Transaction Type,Transaction Description,Investment Name,Symbol,"
                    "Shares,Share Price,Principal Amount,Commissions and Fees,Net Amount,Accrued Interest,Account Type,"]
    for d, acct, shares in ((dt.date(2026, 8, 5), "24003142", 18.02), (dt.date(2026, 7, 6), "24003142", 15.15),
                            (dt.date(2026, 6, 3), "24008827", 22.53)):
        amt = r2(shares * P.VFIFX_NAV)
        lines.append(f"{acct},{d.isoformat()},{(d + dt.timedelta(days=1)).isoformat()},Buy,Buy,{P.STOCK_NAMES['VFIFX']},VFIFX,"
                     f"{shares},{P.VFIFX_NAV},-{amt},0.00,-{amt},0.00,CASH,")
    path.write_text("\ufeff" + "\n".join(lines) + "\n", encoding="utf-8", newline="\n")


# ---------------------------------------------------------------------------------------------
def generate(out: Path, seed: int = 20260912) -> dict:
    rng = Rng(seed)
    out = Path(out)
    months = list(months_between(P.BANK_START, P.CARD_EXPORT))

    purchases = everyday_purchases(rng, months) + fixed_card_purchases(P.CARD_EXPORT)
    amazon_rows, amazon_purchases = amazon_orders(rng, dt.date(2025, 1, 10), dt.date(2026, 8, 31))
    purchases += amazon_purchases
    for d, oid, total, charged, status, items in P.CHEWY_ORDERS:
        purchases.append(Purchase(d, "CHEWY.COM", charged, "Shopping", "freedom", "Shopping", "Pets"))

    per_card, payments, statements, current = build_cards(purchases)
    venmo = venmo_history(rng, P.AS_OF)
    bank = bank_rows(rng, purchases, venmo, payments)

    # ---- bank: two overlapping year-at-a-time exports
    def bank_file(a: dt.date, b: dt.date):
        return [r for r in bank if a <= r["_date"] <= b]
    write_csv(out / "bank" / "transactions_2024-07-01_2025-12-31.csv", BANK_COLUMNS, bank_file(dt.date(2024, 7, 1), dt.date(2025, 12, 31)))
    write_csv(out / "bank" / "transactions_2025-11-01_2026-08-31.csv", BANK_COLUMNS, bank_file(dt.date(2025, 11, 1), dt.date(2026, 8, 31)))

    # ---- cards: a full pull per card, plus an older overlapping Freedom pull
    write_csv(out / "cards" / f"Chase{P.FREEDOM}_Activity_20260801.csv", CARD_COLUMNS, card_csv_rows(per_card[P.FREEDOM], dt.date(2026, 8, 1), rng))
    write_csv(out / "cards" / f"Chase{P.FREEDOM}_Activity_20260901.csv", CARD_COLUMNS, card_csv_rows(per_card[P.FREEDOM], P.CARD_EXPORT, rng))
    write_csv(out / "cards" / f"Chase{P.PRIME}_Activity_20260901.csv", CARD_COLUMNS, card_csv_rows(per_card[P.PRIME], P.CARD_EXPORT, rng))
    (out / "cards" / "statements.json").write_text(json.dumps([statements[P.FREEDOM], statements[P.PRIME]], indent=2) + "\n", encoding="utf-8", newline="\n")

    # ---- amazon: two exports that overlap on December 2025
    write_csv(out / "amazon" / "amazon_order_history_2025.csv", AMAZON_COLUMNS,
              [r for r in amazon_rows if r["order date"] <= "2025-12-31"], encoding="utf-8-sig")
    write_csv(out / "amazon" / "amazon_order_history_2026.csv", AMAZON_COLUMNS,
              [r for r in amazon_rows if r["order date"] >= "2025-12-01"], encoding="utf-8-sig")

    # ---- venmo: one statement per year (2016 was never exported)
    by_year = defaultdict(list)
    for r in venmo:
        r["id"] = str(4000000000000000000 + int(hashlib.md5(r["when"].isoformat().encode()).hexdigest()[:15], 16) % 900000000000000000)
        by_year[r["year"]].append(r)
    for year, rows in sorted(by_year.items()):
        write_venmo(out / "venmo" / f"VenmoStatement_Jan_Dec_{year}.csv", year, rows)

    # ---- chewy
    chewy_rows = []
    for d, oid, total, charged, status, items in P.CHEWY_ORDERS:
        row = {"client-date": f"{d.strftime('%b')} {d.day}, {d.year}",
               "styles_orderId__9auMd": oid, "styles_orderTotal__W2t1h": f"${total:.2f}",
               "styles_orderStatusContentMessage__mXOb7": status}
        for i, (brand, product, dollars, cents) in enumerate(items):
            suf = "" if i == 0 else " 2"
            row["kib-product-title__text" + suf] = brand
            row["styles_itemContentTitleName__vouPu" + suf] = product
            row["kib-product-price__dollars" + suf] = dollars
            row["kib-product-price__cents" + suf] = cents
        chewy_rows.append(row)
    write_csv(out / "chewy" / "chewy_orders_2026.csv", CHEWY_COLUMNS, chewy_rows, encoding="utf-8-sig")

    # ---- balances
    positions, vg_balances = vanguard_positions()
    write_vanguard(out / "balances" / "VANGUARD_ACCOUNT_LIST.csv", positions)
    fidelity = r2(sum(sh * P.STOCK_PX[s] for s, sh in P.FIDELITY_LOTS) + P.FIDELITY_CASH)
    balance_rows = []
    for acct, (name, kind, fund, lots) in P.VANGUARD.items():
        balance_rows.append({"account": name, "institution": "Vanguard", "account_type": kind, "fund": fund,
                             "balance": money(vg_balances[acct]), "as_of": "2026-09-01", "contributing": "yes" if "IRA" in name else "n/a",
                             "source_file": "VANGUARD_ACCOUNT_LIST.csv", "notes": ""})
    balance_rows += [
        {"account": "County Library 403b", "institution": "Voya", "account_type": "403(b) pre-tax", "fund": "Target Retirement 2050 Trust",
         "balance": money(P.TDA_403B), "as_of": "2026-07", "contributing": "yes", "source_file": "voya_statement_2026-07.pdf",
         "notes": "Quarterly statement; balance moves with the target-date trust"},
        {"account": "Prior-state pension DC x2290", "institution": "State Retirement System", "account_type": "Pension DC pre-tax",
         "fund": "State 2050 Fund", "balance": money(P.STATE_DC), "as_of": "2026-07", "contributing": "no",
         "source_file": "state_dc_statement_2026-07.pdf", "notes": "Defined-contribution side of the prior employer's plan; static"},
        {"account": "Lakeshore Credit Union Savings + Checking", "institution": "Lakeshore Credit Union", "account_type": "Bank checking + savings",
         "fund": "Share Savings 0001 + Free Checking 0072", "balance": money(P.CU_BALANCE), "as_of": "2026-09-01", "contributing": "n/a",
         "source_file": "transactions_2025-11-01_2026-08-31.csv", "notes": "Ending balances from the Aug 31 statement, rolled forward"},
        {"account": "Fidelity Individual x4471", "institution": "Fidelity", "account_type": "Taxable brokerage (individual)",
         "fund": "Individual stocks + ETFs", "balance": money(fidelity), "as_of": "2026-06-30", "contributing": "n/a",
         "source_file": "fidelity_statement_2026-06.pdf", "notes": "Quarterly statement; no position-level export"},
        {"account": f"Loan to {P.LOAN_BORROWER} (due 2026-12-20)", "institution": "Personal", "account_type": "Receivable",
         "fund": "Principal lent 2026-08-20", "balance": money(P.LOAN_PRINCIPAL), "as_of": "2026-08-20", "contributing": "n/a",
         "source_file": "config.yaml", "notes": "Signed note; repayment expected in one piece"},
    ]
    write_csv(out / "balances" / "balances.csv",
              ["account", "institution", "account_type", "fund", "balance", "as_of", "contributing", "source_file", "notes"], balance_rows)
    write_csv(out / "balances" / "credit_cards.csv", ["card_id", "card_name", "current_balance", "as_of", "source_file"],
              [{"card_id": c, "card_name": P.CARDS[c], "current_balance": money(current[c]), "as_of": P.CARD_EXPORT.isoformat(),
                "source_file": f"Chase{c}_Activity_20260901.csv"} for c in (P.FREEDOM, P.PRIME)])

    # ---- alerts
    alert_rows = []
    for i, (ts, card, merchant, amount, kind) in enumerate(P.ALERTS):
        signed = -abs(amount) if kind == "credit" else abs(amount)
        h = hashlib.sha256(f"{ts}-{card}-{merchant}".encode()).hexdigest()
        subject = (f"A refund of ${abs(amount):.2f} was credited to your account" if kind == "credit"
                   else f"You made a ${amount:.2f} transaction with {merchant}")
        alert_rows.append({"alert_id": h[:16], "notification_id": f"CREDIT_REALTIME_AUTH-{h}-ver3-3-{h[:8]}-{h[8:12]}-3e6c-a41b-{h[12:24]}",
                           "datetime": ts, "date": ts[:10], "card_id": card, "merchant": merchant, "amount": f"{signed:.2f}",
                           "amount_cents": int(round(signed * 100)), "kind": kind, "issuer": "Chase", "subject": subject})
    write_csv(out / "alerts" / "alerts.csv", ALERT_COLUMNS, alert_rows)
    (out / "alerts" / "review.json").write_text(json.dumps(P.ALERT_REVIEW, indent=2) + "\n", encoding="utf-8", newline="\n")
    (out / "alerts" / "statement-balances.json").write_text(json.dumps([P.DISCOVER_STATEMENT], indent=2) + "\n", encoding="utf-8", newline="\n")
    (out / "alerts" / "not-spending.json").write_text(json.dumps([hashlib.sha256(f"notice-{i}".encode()).hexdigest()[:16] for i in range(6)]) + "\n",
                                                      encoding="utf-8", newline="\n")

    summary = {
        "seed": seed, "as_of": P.AS_OF.isoformat(),
        "bank_rows": len(bank), "card_rows": {c: len(v) for c, v in per_card.items()},
        "amazon_items": len(amazon_rows), "venmo_rows": len(venmo), "chewy_orders": len(P.CHEWY_ORDERS),
        "alerts": len(alert_rows), "card_current_balances": current,
        "statement_balances": {c: statements[c]["statement_balance"] for c in statements},
    }
    (out / "MANIFEST.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8", newline="\n")
    return summary
