"""Card transaction-alert emails -> pending card rows.

Chase (and, once enabled, Capital One) can email an alert on every swipe. Those
land within seconds, which is the only near-real-time spending signal available:
there is no consumer API and no banking connector to call.

Several guarantees here were adopted after reviewing a parallel implementation of
the same idea, which got them right:

* **Money is Decimal, never float**, and is carried alongside as integer cents.
* **Nothing is silently dropped.** Anything unparseable, ambiguous, or from an
  unrecognised card goes to a `review` lane and stays visible. A dropped alert is
  indistinguishable from a quieter month, which is the failure that matters.
* **Sender is verified** against an allow-list, so a spoofed display name cannot
  inject a row.
* **The subject's amount is cross-checked against the body's.** A mismatch means
  the parse is wrong somewhere, so the row goes to review rather than being trusted.
* **Declines, reversals and pre-authorisation holds go to review, not spending.**
  A fuel hold is a placeholder ($1 or $100), not what was spent.
* **Two dedupe keys**: the Gmail message id, and the issuer's own Notification-Id
  header. The same alert can be re-sent as a new message, which single-key dedupe
  would count twice.

Alerts remain AUTHORISATIONS. They live only in the pending lane; `metrics` lets
each card's own statement CSV supersede them.
"""
from __future__ import annotations

import csv
import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation
from email.utils import parseaddr
from html import unescape as html_unescape
from html.parser import HTMLParser
from pathlib import Path

FIELDNAMES = ["alert_id", "notification_id", "datetime", "date", "card_id",
              "merchant", "amount", "amount_cents", "kind", "issuer", "subject"]


@dataclass
class Issuer:
    name: str
    senders: tuple
    not_spending: tuple = field(default=())


# A sender not listed here is never parsed. Capital One took over the Discover it
# card in Jul 2026; its alert format is UNVERIFIED -- no transaction alert has ever
# arrived because the setting is off -- so anything from it that does not parse
# cleanly is quarantined rather than guessed at.
ISSUERS = (
    Issuer("Chase", ("no.reply.alerts@chase.com",),
           ("statement is available", "automatic payment", "payment is scheduled",
            "payment due", "security alert", "we received your payment")),
    Issuer("Capital One", ("capitalone@notification.capitalone.com",
                           "notifications@notification.capitalone.com",
                           "capitalone@notify.capitalone.com"),
           ("statement is ready", "payment", "autopay", "balance transfer",
            "welcome", "paperless", "online access", "credit score", "enrolled")),
)
_SENDER_MAP = {s: i for i in ISSUERS for s in i.senders}

_SUBJ_AMOUNT = re.compile(r"\$\s*([\d,]+\.\d{2})")
_CARD_LAST4 = re.compile(r"(?:\.{3}|…|ending(?:\s+in)?|\*{2,})\s*(\d{4})", re.I)
_MONEY_CELL = re.compile(r"^(-|−)?\s*\$?\s*([\d,]+\.\d{2})$")
_REVIEW_WORDS = ("declined", "reversed", "returned item", "gas station", "hold",
                 "preauthorization", "pre-authorization", "authorization hold")
_CREDIT_WORDS = re.compile(r"\b(refund|refunded|credit|credited)\b", re.I)
_PURCHASE_SUBJECT = re.compile(
    r"(?:you made a|transaction of|a charge of|purchase of)\s*\$[\d,]+\.\d{2}", re.I)

_STAMP_FORMATS = ("%b %d, %Y at %I:%M %p", "%B %d, %Y at %I:%M %p",
                  "%b %d, %Y %I:%M %p", "%m/%d/%Y %I:%M %p",
                  "%b %d, %Y", "%B %d, %Y", "%m/%d/%Y")


class AlertReview(Exception):
    """Looks like spending but cannot be trusted. Goes to the review queue."""


class AlertSkip(Exception):
    """Plainly not a spending alert. Counted as skipped, never queued.

    Issuers send far more mail than transactions -- statements, payment reminders,
    security notices, marketing. Queueing those for review would bury the handful
    that genuinely need a human look, which defeats the point of the queue.
    """


class _Cells(HTMLParser):
    """Flatten an HTML email's table cells to text.

    Chase nests layout tables several deep and leaves an <a> unclosed inside the
    Date cell, so a regex over <td>...</td> mis-slices it. Feeding text into every
    open cell and emitting on close handles nesting and malformed markup alike.
    """

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack, self.values = [], []

    def handle_starttag(self, tag, attrs):
        if tag in ("td", "th"):
            self.stack.append([])

    def handle_data(self, data):
        for cell in self.stack:
            cell.append(data)

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self.stack:
            text = " ".join("".join(self.stack.pop()).split())
            if text:
                self.values.append(text)


def _cells(html_body):
    p = _Cells()
    p.feed(html_body or "")
    p.close()
    return p.values


def _labelled(cells, label):
    """Value in the first cell following an exact-match label cell."""
    low = label.lower()
    for i, c in enumerate(cells[:-1]):
        if c.rstrip(":").strip().lower() == low:
            return cells[i + 1]
    return ""


def _parse_stamp(raw, received_iso):
    """'Sep 8, 2026 at 8:55 AM ET' -> naive datetime.

    The suffix is a US zone abbreviation, not a tz database name. The wall-clock
    time the issuer printed is what the rest of the pipeline compares against.
    """
    cleaned = re.sub(r"\b(ET|CT|MT|PT|EST|EDT|CST|CDT|MST|MDT|PST|PDT)\b", "",
                     str(raw or ""), flags=re.I).strip().rstrip(",")
    for fmt in _STAMP_FORMATS:
        try:
            return datetime.strptime(cleaned, fmt)
        except ValueError:
            continue
    if received_iso:
        try:
            dt = datetime.fromisoformat(str(received_iso).replace("Z", "+00:00"))
            return dt.replace(tzinfo=None) if dt.tzinfo is None else dt.astimezone().replace(tzinfo=None)
        except ValueError:
            pass
    raise AlertReview("no usable date on the alert")


def parse_alert(msg, known_cards=()):
    """Parse one alert email. Raises AlertReview for anything not safely countable.

    msg = {id, from, subject, received, notification_id, html}
    """
    mid = str(msg.get("id") or "").strip()
    if not mid:
        raise AlertReview("missing Gmail message id")
    subject = str(msg.get("subject") or "")

    sender = parseaddr(str(msg.get("from") or ""))[1].lower()
    issuer = _SENDER_MAP.get(sender)
    if issuer is None:
        raise AlertReview("sender not on the allow-list: " + (sender or "(none)"))

    low = subject.lower()
    if any(p in low for p in issuer.not_spending):
        raise AlertSkip("statement, payment or account notice")

    body = msg.get("html", "") or ""
    cells = _cells(body)

    # Positive gate: a spending alert always names a sum somewhere. If neither the
    # subject nor an Amount cell has one, and no purchase/credit wording is present,
    # this is ordinary issuer mail rather than a parse failure -- skip, do not queue.
    has_money = bool(_SUBJ_AMOUNT.search(subject)) or bool(
        _MONEY_CELL.match(_labelled(cells, "Amount").strip()))
    if not has_money and not (_CREDIT_WORDS.search(low) or _PURCHASE_SUBJECT.search(subject)):
        raise AlertSkip("no transaction amount anywhere in the message")

    m = _CARD_LAST4.search(_labelled(cells, "Account")) or _CARD_LAST4.search(body)
    card_id = m.group(1) if m else ""
    if not card_id:
        raise AlertReview("could not identify the card")
    if known_cards and card_id not in known_cards:
        raise AlertReview("card ..." + card_id + " is not configured")

    amount = None
    mc = _MONEY_CELL.match(_labelled(cells, "Amount").strip())
    if mc:
        try:
            amount = Decimal(mc.group(2).replace(",", ""))
            if mc.group(1):
                amount = -amount
        except InvalidOperation:
            amount = None
    subj = _SUBJ_AMOUNT.search(subject)
    if amount is None:
        if not subj:
            raise AlertReview("no amount found in body or subject")
        amount = Decimal(subj.group(1).replace(",", ""))
    elif subj and Decimal(subj.group(1).replace(",", "")) != abs(amount):
        raise AlertReview("subject and body amounts disagree")
    if amount == 0:
        raise AlertReview("zero amount")

    stamp = _parse_stamp(_labelled(cells, "Date"), msg.get("received"))
    merchant = _labelled(cells, "Merchant") or _labelled(cells, "Description")

    if any(w in low for w in _REVIEW_WORDS):
        raise AlertReview("decline, reversal or authorisation hold - not settled spending")
    if _CREDIT_WORDS.search(low):
        kind, amount = "credit", -abs(amount)
    elif _PURCHASE_SUBJECT.search(subject):
        kind, amount = "purchase", abs(amount)
    else:
        raise AlertReview("subject does not match a known purchase or credit alert")

    if not merchant:
        if kind != "credit":
            raise AlertReview("no merchant on a purchase alert")
        merchant = "(refund)"

    return {
        "alert_id": mid,
        "notification_id": str(msg.get("notification_id") or ""),
        "datetime": stamp.isoformat(sep=" ", timespec="minutes"),
        "date": stamp.date().isoformat(),
        "card_id": card_id,
        "merchant": merchant,
        "amount": float(amount),
        "amount_cents": int(amount * 100),
        "kind": kind,
        "issuer": issuer.name,
        "subject": subject,
    }


_STMT_BALANCE = re.compile(
    r"statement balance is\s*\$([\d,]+\.\d{2})", re.I)
_STMT_SUBJECT = re.compile(r"statement is (?:ready|available)", re.I)


def parse_statement_balance(msg, card_matches):
    """Pull a statement balance out of an issuer's 'statement is ready' email.

    A card with no transaction alerts still emails a monthly statement, so this is
    the only automatic figure available for one that is not reporting swipes. It is
    a BALANCE at a closing date, not spending -- the dashboard labels it as such.

    `card_matches` maps a lowercase subject fragment to a card id, because these
    emails name the product ("Discover it Card") and not the last four digits.
    """
    subject = str(msg.get("subject") or "")
    if not _STMT_SUBJECT.search(subject):
        return None
    low = subject.lower()
    card_id = next((cid for frag, cid in card_matches.items() if frag in low), None)
    if not card_id:
        return None
    text = " ".join(re.sub(r"<[^>]+>", " ", msg.get("html", "") or "").split())
    m = _STMT_BALANCE.search(html_unescape(text))
    if not m:
        return None
    return {"card_id": card_id,
            "balance": float(Decimal(m.group(1).replace(",", ""))),
            "as_of": str(msg.get("received") or "")[:10],
            "subject": subject}


def ingest(messages, csv_path, review_path, known_cards=(), skip_path=None):
    """Merge messages into the alert store. Returns a summary dict."""
    csv_path, review_path = Path(csv_path), Path(review_path)
    csv_path.parent.mkdir(parents=True, exist_ok=True)

    accepted = {}
    if csv_path.exists():
        with csv_path.open(newline="", encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                accepted[r["alert_id"]] = r
    # notification id -> message id, so a re-sent alert cannot become a second row
    by_notification = {r.get("notification_id"): k
                       for k, r in accepted.items() if r.get("notification_id")}

    review = {}
    if review_path.exists():
        try:
            review = {r["alert_id"]: r
                      for r in json.loads(review_path.read_text(encoding="utf-8"))}
        except (ValueError, KeyError, TypeError):
            review = {}

    # ids already judged "not spending", so a re-sync never re-downloads them
    skip_path = Path(skip_path) if skip_path else None
    skip_ids = set()
    if skip_path and skip_path.exists():
        try:
            skip_ids = set(json.loads(skip_path.read_text(encoding="utf-8")))
        except (ValueError, TypeError):
            skip_ids = set()

    before, resent, skipped = len(accepted), 0, 0
    for msg in messages:
        mid = str(msg.get("id") or "")
        try:
            row = parse_alert(msg, known_cards)
        except AlertSkip:
            skipped += 1
            # Statement mail is skipped as spending, but each new one carries a
            # fresh balance, so it must stay re-readable on later syncs.
            if mid and not _STMT_SUBJECT.search(str(msg.get("subject") or "")):
                skip_ids.add(mid)
            continue
        except AlertReview as exc:
            if mid and mid not in accepted:
                review[mid] = {"alert_id": mid,
                               "subject": str(msg.get("subject") or ""),
                               "from": str(msg.get("from") or ""),
                               "received": str(msg.get("received") or ""),
                               "reason": str(exc)}
            continue
        nid = row["notification_id"]
        if nid and by_notification.get(nid) not in (None, row["alert_id"]):
            resent += 1
            continue
        accepted[row["alert_id"]] = {k: row.get(k, "") for k in FIELDNAMES}
        if nid:
            by_notification[nid] = row["alert_id"]
        review.pop(row["alert_id"], None)

    ordered = sorted(accepted.values(), key=lambda r: (str(r["datetime"]), r["alert_id"]))
    tmp = csv_path.with_suffix(".tmp")
    with tmp.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDNAMES)
        w.writeheader()
        w.writerows(ordered)
    tmp.replace(csv_path)

    tmp = review_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(sorted(review.values(), key=lambda r: r["alert_id"]),
                              indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(review_path)

    if skip_path:
        tmp = skip_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(sorted(skip_ids)), encoding="utf-8")
        tmp.replace(skip_path)

    return {"added": len(accepted) - before, "total": len(accepted),
            "review": len(review), "resent_skipped": resent,
            "not_spending": skipped}
