"""Fetch card alert emails from Gmail and merge them into the alert store.

    python tools/sync_alerts.py --install-client "<client_secret_....json>"   # once
    python tools/sync_alerts.py --connect                                     # once
    python tools/sync_alerts.py                                               # every time
    python tools/sync_alerts.py --days 30 --rebuild

Read-only Gmail access. The refresh token is encrypted with Windows DPAPI and kept
in %LOCALAPPDATA%\\NorthstarFinance, outside OneDrive and outside this folder.

Re-running is safe and idempotent: rows dedupe on the Gmail message id and on the
issuer's Notification-Id, so over-fetching a wide window costs time, never accuracy.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from finlib import alerts as alerts_mod            # noqa: E402
from finlib import gmail_sync                      # noqa: E402

CSV_PATH = ROOT / "data" / "alerts" / "alerts.csv"
REVIEW_PATH = ROOT / "data" / "alerts" / "review.json"
SKIP_PATH = ROOT / "data" / "alerts" / "not-spending.json"
STMT_PATH = ROOT / "data" / "alerts" / "statement-balances.json"
LEGACY_CSV = ROOT / "data" / "alerts" / "chase_alerts.csv"


def _config():
    import yaml
    return yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))


def _known_ids():
    """Message ids already in the store, so their bodies are never re-downloaded."""
    import csv as _csv
    ids = set()
    for path in (CSV_PATH, REVIEW_PATH):
        if not path.exists():
            continue
        if path.suffix == ".csv":
            with path.open(newline="", encoding="utf-8") as fh:
                ids.update(r["alert_id"] for r in _csv.DictReader(fh))
        else:
            try:
                rows = json.loads(path.read_text(encoding="utf-8"))
                ids.update(r["alert_id"] if isinstance(r, dict) else r for r in rows)
            except (ValueError, KeyError, TypeError):
                pass
    # The skip ledger counts too. Statement mail is deliberately kept OUT of that
    # ledger by alerts.ingest(), so a new statement is always re-read for its balance.
    if SKIP_PATH.exists():
        try:
            ids.update(json.loads(SKIP_PATH.read_text(encoding="utf-8")))
        except (ValueError, TypeError):
            pass
    return ids


def _senders(config):
    """Every sender for an issuer that at least one configured card uses."""
    want = {str(c.get("issuer", "Chase")) for c in (config.get("cards") or {}).values()}
    out = []
    for issuer in alerts_mod.ISSUERS:
        if issuer.name in want:
            out.extend(issuer.senders)
    return out or [s for i in alerts_mod.ISSUERS for s in i.senders]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--install-client", metavar="JSON",
                    help="Copy a Google Desktop OAuth client into the private folder (run once).")
    ap.add_argument("--connect", action="store_true",
                    help="Run the Google consent flow in a browser (run once).")
    ap.add_argument("--days", type=int, default=90,
                    help="How far back to search. Default 90; safe to raise, dedupe handles overlap.")
    ap.add_argument("--from-json", metavar="FILE",
                    help="Ingest messages from a JSON file instead of Gmail (offline/testing).")
    ap.add_argument("--rebuild", action="store_true", help="Run update.py afterwards.")
    ap.add_argument("--status", action="store_true", help="Show connection status and exit.")
    args = ap.parse_args(argv)

    if args.status:
        st = gmail_sync.status()
        print(f"OAuth client installed : {st['client_installed']}")
        print(f"Gmail connected        : {st['connected']}")
        print(f"Private folder         : {st['private_dir']}")
        print(f"Alert store            : {CSV_PATH}")
        return 0

    if args.install_client:
        path = gmail_sync.install_client(args.install_client)
        print(f"OAuth client installed at {path}")
        print("Next: python tools/sync_alerts.py --connect")
        return 0

    if args.connect:
        gmail_sync.credentials(connect=True)
        print("Gmail connected (read-only). Token encrypted with Windows DPAPI.")
        print("Next: python tools/sync_alerts.py")
        return 0

    config = _config()
    known_cards = {str(k).zfill(4) for k in (config.get("cards") or {})}

    if args.from_json:
        messages = json.loads(Path(args.from_json).read_text(encoding="utf-8-sig"))
        print(f"Ingesting {len(messages)} message(s) from {args.from_json}")
    else:
        senders = _senders(config)
        print(f"Searching Gmail (read-only), last {args.days} days")
        print("  senders: " + ", ".join(senders))
        def _progress(n, total, skipped=0):
            if skipped:
                print(f"  {skipped} already stored, {total} new to read")
            elif total:
                print(f"  read {n}/{total}")

        try:
            messages = gmail_sync.fetch(senders, days=args.days,
                                        progress=_progress,
                                        known_ids=_known_ids())
        except ValueError as exc:
            print(f"\n{exc}")
            return 2
        except Exception as exc:                       # noqa: BLE001
            print("\nGmail request failed: " + gmail_sync.redact(exc))
            return 2
        print(f"  {len(messages)} candidate message(s)")

    # one-time migration from the single-issuer store
    if LEGACY_CSV.exists() and not CSV_PATH.exists():
        import csv as _csv
        with LEGACY_CSV.open(newline="", encoding="utf-8") as fh:
            old = list(_csv.DictReader(fh))
        CSV_PATH.parent.mkdir(parents=True, exist_ok=True)
        with CSV_PATH.open("w", newline="", encoding="utf-8") as fh:
            w = _csv.DictWriter(fh, fieldnames=alerts_mod.FIELDNAMES)
            w.writeheader()
            for r in old:
                r.setdefault("issuer", "Chase")
                r.setdefault("notification_id", "")
                try:
                    r["amount_cents"] = int(round(float(r.get("amount", 0)) * 100))
                except (TypeError, ValueError):
                    r["amount_cents"] = 0
                w.writerow({k: r.get(k, "") for k in alerts_mod.FIELDNAMES})
        LEGACY_CSV.rename(LEGACY_CSV.with_suffix(".csv.migrated"))
        print(f"  migrated {len(old)} row(s) from chase_alerts.csv")

    # cards that emit no transaction alerts still email a monthly statement; that
    # balance is the only automatic figure they offer, so keep the newest per card
    matches = {str(c["statement_subject"]).lower(): str(k).zfill(4)
               for k, c in (config.get("cards") or {}).items()
               if c.get("statement_subject")}
    if matches:
        found = {}
        if STMT_PATH.exists():
            try:
                found = {r["card_id"]: r for r in json.loads(STMT_PATH.read_text(encoding="utf-8"))}
            except (ValueError, KeyError, TypeError):
                found = {}
        for m in messages:
            row = alerts_mod.parse_statement_balance(m, matches)
            if row and row["as_of"] >= found.get(row["card_id"], {}).get("as_of", ""):
                found[row["card_id"]] = row
        if found:
            tmp = STMT_PATH.with_suffix(".tmp")
            tmp.write_text(json.dumps(sorted(found.values(), key=lambda r: r["card_id"]),
                                      indent=2), encoding="utf-8")
            tmp.replace(STMT_PATH)
            print(f"  statement balances on file for {len(found)} card(s)")

    res = alerts_mod.ingest(messages, CSV_PATH, REVIEW_PATH, known_cards, SKIP_PATH)
    print(f"\n{res['added']} new, {res['total']} on file, "
          f"{res['review']} needing review, {res['resent_skipped']} re-sent duplicate(s) skipped, "
          f"{res.get('not_spending', 0)} non-spending notice(s) ignored")
    if res["review"]:
        print(f"  review queue: {REVIEW_PATH}")
        for r in json.loads(REVIEW_PATH.read_text(encoding="utf-8"))[:5]:
            print(f"    - {r['subject'][:58]!r}: {r['reason']}")

    if args.rebuild:
        print("\nRebuilding dashboards...")
        return subprocess.call([sys.executable, str(ROOT / "update.py")], cwd=str(ROOT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
