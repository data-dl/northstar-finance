"""Serve the dashboards locally so the Update button can actually do something.

A `file://` page cannot fetch Gmail, run Python, or trigger anything. Serving the
same files over a loopback HTTP server gives the page one endpoint to call, which
turns the two-launcher routine into a button.

    python tools/serve.py            # serve + open a browser
    python tools/serve.py --no-open

Security posture, since this process can reach a mailbox:

* Binds **127.0.0.1 only** -- never a routable interface.
* Serves `output/` and nothing else. The OAuth client and token live in
  %LOCALAPPDATA%, outside the served tree, so they cannot be requested.
* Every mutating route requires a **random per-run token** in `X-Northstar-Token`,
  printed nowhere except the served page itself. A browser cannot attach a custom
  header cross-origin without a preflight, and the preflight is refused, so a
  malicious page in another tab cannot drive this server even though it knows the
  port. The token being per-run means a value learned once is useless next time.
* `Host` and `Origin` are both pinned to this server.
* Errors are redacted before they reach the browser or the console.
"""
from __future__ import annotations

import argparse
import json
import secrets
import subprocess
import sys
import threading
import webbrowser
from datetime import datetime
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from finlib import gmail_sync            # noqa: E402
import sync_alerts as sync_cli           # noqa: E402  (tools/ is on sys.path as cwd)

SERVE_DIR = ROOT / "output"
TOKEN = secrets.token_urlsafe(24)
BUSY = threading.Lock()
STATE = {"last_sync": None, "last_result": None}


def _do_sync(days=90):
    """Fetch -> parse -> rebuild. Returns a summary for the browser."""
    config = sync_cli._config()
    known_cards = {str(k).zfill(4) for k in (config.get("cards") or {})}
    messages = gmail_sync.fetch(sync_cli._senders(config), days=days,
                                known_ids=sync_cli._known_ids())
    res = sync_cli.alerts_mod.ingest(messages, sync_cli.CSV_PATH,
                                     sync_cli.REVIEW_PATH, known_cards,
                                     sync_cli.SKIP_PATH)
    build = subprocess.run([sys.executable, str(ROOT / "update.py")],
                           cwd=str(ROOT), capture_output=True, text=True)
    res["rebuilt"] = build.returncode == 0
    if not res["rebuilt"]:
        res["build_error"] = gmail_sync.redact((build.stderr or "")[-400:])
    res["checked_at"] = datetime.now().isoformat(sep=" ", timespec="seconds")
    STATE["last_sync"] = res["checked_at"]
    STATE["last_result"] = res
    return res


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(SERVE_DIR), **kw)

    # -- hardening ---------------------------------------------------------
    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        super().end_headers()

    def _origin_ok(self):
        host = self.headers.get("Host", "")
        if host != f"127.0.0.1:{self.server.server_port}":
            return False
        origin = self.headers.get("Origin")
        return origin in (None, f"http://127.0.0.1:{self.server.server_port}")

    def _json(self, body, status=200):
        raw = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, fmt, *args):
        pass

    # -- routes ------------------------------------------------------------
    def do_GET(self):
        if not self._origin_ok():
            return self._json({"error": "bad host"}, 403)
        route = urlsplit(self.path).path
        if route == "/api/status":
            st = gmail_sync.status()
            return self._json({"connected": st["connected"],
                               "client_installed": st["client_installed"],
                               "last_sync": STATE["last_sync"],
                               "busy": BUSY.locked(),
                               "token": TOKEN})
        return super().do_GET()

    def do_POST(self):
        if not self._origin_ok():
            return self._json({"error": "bad host or origin"}, 403)
        if self.headers.get("X-Northstar-Token") != TOKEN:
            return self._json({"error": "Open this page from the Northstar window."}, 403)
        if urlsplit(self.path).path != "/api/sync":
            return self._json({"error": "unknown action"}, 404)
        if not BUSY.acquire(blocking=False):
            return self._json({"error": "A sync is already running."}, 409)
        try:
            return self._json(_do_sync())
        except ValueError as exc:
            return self._json({"error": str(exc)}, 400)
        except Exception as exc:                                   # noqa: BLE001
            return self._json({"error": "Gmail sync failed: " + gmail_sync.redact(exc)}, 400)
        finally:
            BUSY.release()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8791)
    ap.add_argument("--no-open", action="store_true")
    args = ap.parse_args()

    if not (SERVE_DIR / "index.html").exists():
        print(f"No dashboards in {SERVE_DIR}. Run update.py first.")
        return 1

    srv = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    url = f"http://127.0.0.1:{args.port}/index.html"
    st = gmail_sync.status()
    print("  Northstar is live at " + url)
    print("  Gmail connected: " + ("yes" if st["connected"] else "NO - run '1 - Connect Gmail' first"))
    print("  The Sync button on the page works while this window is open.")
    print("  Close this window to stop.\n")
    if not args.no_open:
        webbrowser.open(url)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
