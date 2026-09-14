"""Gmail fetch-layer checks. No credentials, no network: the API is stubbed.

Run: python tests/test_gmail_sync.py
"""
import base64
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from finlib import gmail_sync  # noqa: E402


def b64(s):
    return base64.urlsafe_b64encode(s.encode()).decode().rstrip("=")


class _Messages:
    def __init__(self, pages, bodies):
        self._pages, self._bodies = pages, bodies
        self.list_calls, self.queries = 0, []

    def list(self, userId, q, maxResults, pageToken=None):
        self.list_calls += 1
        self.queries.append(q)
        page = self._pages[pageToken]
        return type("R", (), {"execute": staticmethod(lambda: page)})()

    def get(self, userId, id, format):
        body = self._bodies[id]
        return type("R", (), {"execute": staticmethod(lambda: body)})()


class _Service:
    def __init__(self, msgs):
        self._m = msgs

    def users(self):
        return type("U", (), {"messages": lambda _self: self._m})()


def _msg(mid, html, notification=None, nested=False):
    headers = [{"name": "From", "value": "Chase <no.reply.alerts@chase.com>"},
               {"name": "Subject", "value": f"You made a $1.00 transaction ({mid})"}]
    if notification:
        headers.append({"name": "Notification-Id", "value": notification})
    if nested:
        # real Chase mail is multipart/alternative with html nested below plain text
        payload = {"mimeType": "multipart/alternative", "headers": headers, "parts": [
            {"mimeType": "text/plain", "body": {"data": b64("plain fallback")}},
            {"mimeType": "multipart/related", "parts": [
                {"mimeType": "text/html", "body": {"data": b64(html)}}]}]}
    else:
        payload = {"mimeType": "text/html", "headers": headers, "body": {"data": b64(html)}}
    return {"id": mid, "internalDate": "1788872106000", "payload": payload}


def test_query_is_sender_scoped_and_skips_trash():
    q = gmail_sync.build_query(["a@x.com", "b@y.com"], 90)
    assert "from:a@x.com OR from:b@y.com" in q, q
    assert "newer_than:90d" in q and "-in:trash" in q and "-in:spam" in q, q
    # NOT restricted to the inbox: a filter that files alerts away must not hide them
    assert "in:inbox" not in q, q
    print("  query is sender-scoped, all-label, trash/spam-excluded")


def test_pagination_collects_every_page():
    pages = {None: {"messages": [{"id": "a"}, {"id": "b"}], "nextPageToken": "p2"},
             "p2": {"messages": [{"id": "c"}]}}
    bodies = {k: _msg(k, f"<p>{k}</p>") for k in "abc"}
    m = _Messages(pages, bodies)
    out = gmail_sync.fetch(["s@x.com"], 30, service=_Service(m))
    assert [r["id"] for r in out] == ["a", "b", "c"], out
    assert m.list_calls == 2, m.list_calls
    print("  pagination walks every page ->", len(out), "messages")


def test_extracts_nested_html_and_notification_header():
    pages = {None: {"messages": [{"id": "n1"}]}}
    bodies = {"n1": _msg("n1", "<td>Amount</td><td>$1.00</td>",
                         notification="NOTIF-77", nested=True)}
    out = gmail_sync.fetch(["s@x.com"], 30, service=_Service(_Messages(pages, bodies)))
    row = out[0]
    assert "Amount" in row["html"], row["html"]
    assert row["notification_id"] == "NOTIF-77", row
    assert row["received"].startswith("2026-09-08"), row
    print("  nested multipart html + Notification-Id extracted")


def test_scope_is_readonly_only():
    assert gmail_sync.SCOPES == ["https://www.googleapis.com/auth/gmail.readonly"], gmail_sync.SCOPES
    print("  scope is gmail.readonly and nothing else")


def test_secrets_are_kept_out_of_onedrive():
    p = str(gmail_sync.PRIVATE_DIR).lower()
    assert "onedrive" not in p, p
    assert "finance_pipeline" not in p, p
    print("  token folder is outside OneDrive and outside the project:", gmail_sync.PRIVATE_DIR)


def test_redaction_strips_token_shaped_text():
    dirty = ("failed for 248497322433-abcdefghijklmnop.apps.googleusercontent.com "
             "token ya29.A0ARrdaM-SECRETVALUE and GOCSPX-abc123def456")
    clean = gmail_sync.redact(dirty)
    assert "googleusercontent" not in clean and "ya29" not in clean and "GOCSPX" not in clean, clean
    print("  error redaction removes client id, oauth token and client secret")


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in tests:
        fn()
    print(f"\nall {len(tests)} gmail-sync tests passed")
