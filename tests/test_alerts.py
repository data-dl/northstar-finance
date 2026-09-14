"""Parser checks against the Chase alert format (see fixtures/ -- a real message's HTML with the card, merchant and amount replaced by sample values).

Run: python tests/test_alerts.py
"""
import json
import pathlib
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from finlib.alerts import AlertReview, AlertSkip, FIELDNAMES, ingest, parse_alert  # noqa: E402

FIX = pathlib.Path(__file__).parent / "fixtures" / "chase_alert_sample.html"
BODY = FIX.read_text(encoding="utf-8")
CHASE = "Chase <no.reply.alerts@chase.com>"
CARDS = {"4417", "8802", "3160"}


def msg(**kw):
    base = {"id": "m1", "from": CHASE, "html": BODY,
            "subject": "You made a $4.68 transaction with ELM & 9TH CONVENIENCE",
            "received": "2026-09-08T12:55:06Z", "notification_id": ""}
    # `from` is a keyword, so tests pass from_=... ; translate it
    if "from_" in kw:
        kw["from"] = kw.pop("from_")
    base.update(kw)
    return base


def expect_review(reason_fragment, **kw):
    try:
        parse_alert(msg(**kw), CARDS)
    except AlertReview as exc:
        assert reason_fragment in str(exc), f"got {exc!r}, wanted {reason_fragment!r}"
        return str(exc)
    raise AssertionError(f"expected review for {kw}, but it parsed")


def test_real_alert():
    row = parse_alert(msg(id="1a081162aea54e55"), CARDS)
    assert row["card_id"] == "4417", row
    assert row["merchant"] == "ELM & 9TH CONVENIENCE", row
    assert row["amount"] == 4.68 and row["amount_cents"] == 468, row
    assert row["datetime"].startswith("2026-09-08 08:55"), row
    assert row["kind"] == "purchase" and row["issuer"] == "Chase", row
    print("  real alert parses ->", row["date"], row["card_id"], row["merchant"], row["amount"])


def test_cents_are_exact():
    """Float money drifts; the cents field must be exact for a running total."""
    total = sum(parse_alert(msg(id=f"m{i}"), CARDS)["amount_cents"] for i in range(3))
    assert total == 1404, total
    print("  3 x $4.68 totals exactly 1404 cents")


def test_spoofed_sender_rejected():
    expect_review("allow-list", from_="Chase Alerts <attacker@evil.example>")
    print("  spoofed sender rejected")


def test_subject_body_mismatch_goes_to_review():
    expect_review("disagree", subject="You made a $468.00 transaction with ELM & 9TH CONVENIENCE")
    print("  subject/body amount mismatch quarantined")


def test_holds_and_declines_go_to_review():
    for subj in ("Your transaction was declined at ELM & 9TH CONVENIENCE",
                 "Gas station charge authorized",
                 "A pre-authorization hold was placed"):
        expect_review("", subject=subj)
    print("  declines, fuel holds and pre-auths quarantined")


def test_statements_are_skipped_not_queued():
    """Issuers send far more notices than transactions. Queueing those for review
    would bury the few that genuinely need a human look."""
    for subj in ("Your credit card statement is available",
                 "Chase security alert: You signed in with a new device",
                 "Your Prime Visa automatic payment is scheduled",
                 "You updated your email address",
                 "Finish your setup with Capital One"):
        try:
            parse_alert(msg(subject=subj, html="<p>no amounts here</p>"), CARDS)
        except AlertSkip:
            continue
        except AlertReview as exc:
            raise AssertionError(f"{subj!r} should be skipped, not queued: {exc}")
        raise AssertionError(f"{subj!r} parsed as a purchase")
    print("  statements, security and setup notices are skipped, not queued")


def test_ingest_counts_skips_separately():
    with tempfile.TemporaryDirectory() as tmp:
        c, r = _store(tmp)
        res = ingest([msg(id="ok"),
                      msg(id="notice", subject="Your credit card statement is available",
                          html="<p>nothing</p>")], c, r, CARDS)
        assert res["total"] == 1, res
        assert res["review"] == 0, res
        assert res["not_spending"] == 1, res
    print("  a notice counts as skipped and never reaches the review queue")


def test_unknown_card_quarantined():
    expect_review("not configured", html=BODY.replace("...4417", "...1234"))
    print("  unknown card quarantined rather than counted")


def test_refund_is_negative():
    row = parse_alert(msg(subject="A refund of $4.68 was credited to your account"), CARDS)
    assert row["kind"] == "credit" and row["amount"] == -4.68, row
    print("  refund signs negative")


def _store(tmp):
    return pathlib.Path(tmp) / "alerts.csv", pathlib.Path(tmp) / "review.json"


def test_ingest_is_idempotent():
    with tempfile.TemporaryDirectory() as tmp:
        c, r = _store(tmp)
        ingest([msg(id="same")], c, r, CARDS)
        res = ingest([msg(id="same")], c, r, CARDS)
        assert res["total"] == 1 and res["added"] == 0, res
    print("  re-ingesting the same message does not duplicate it")


def test_resent_notification_not_double_counted():
    """Chase can re-send one alert as a new message id; the Notification-Id is stable."""
    with tempfile.TemporaryDirectory() as tmp:
        c, r = _store(tmp)
        ingest([msg(id="first", notification_id="N-123")], c, r, CARDS)
        res = ingest([msg(id="second-send", notification_id="N-123")], c, r, CARDS)
        assert res["total"] == 1, res
        assert res["resent_skipped"] == 1, res
    print("  re-sent alert with the same Notification-Id counted once")


def test_review_lane_is_populated_not_dropped():
    with tempfile.TemporaryDirectory() as tmp:
        c, r = _store(tmp)
        res = ingest([msg(id="bad", from_="x@evil.example", html="")], c, r, CARDS)
        assert res["review"] == 1 and res["total"] == 0, res
        parked = json.loads(r.read_text(encoding="utf-8"))
        assert parked[0]["reason"], parked
    print("  unparseable alert lands in review, not the void:", parked[0]["reason"])


def test_csv_schema_stable():
    with tempfile.TemporaryDirectory() as tmp:
        c, r = _store(tmp)
        ingest([msg(id="s1")], c, r, CARDS)
        header = c.read_text(encoding="utf-8").splitlines()[0].split(",")
        assert header == FIELDNAMES, header
    print("  csv header matches the loader's expected schema")


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in tests:
        fn()
    print(f"\nall {len(tests)} alert-parser tests passed")
