"""Read-only Gmail fetch for card transaction alerts.

Scope is `gmail.readonly` and nothing else: this can read mail, and cannot send,
delete, archive, or even mark a message read.

Credential handling (the same shape a parallel implementation used, for the same reasons):

* The OAuth client and the refresh token live in `%LOCALAPPDATA%\\NorthstarFinance`
  -- deliberately **outside OneDrive**, so neither ever syncs to the cloud, and
  outside the pipeline folder, so neither can be served by a local web server or
  swept up by a backup of the project.
* The token is encrypted at rest with **Windows DPAPI**, which binds it to this
  Windows user account. Copying the file to another machine or another user
  yields ciphertext that cannot be decrypted.
* Only `client_id` and `client_secret` are copied out of the client JSON; the
  original file is never read again after setup.

The search is scoped by sender to the configured issuers, so authorising this does
not mean the pipeline trawls the whole mailbox -- it asks Gmail for card alerts.
"""
from __future__ import annotations

import base64
import json
import os
import re
from pathlib import Path

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]

PRIVATE_DIR = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "NorthstarFinance"
CLIENT_FILE = PRIVATE_DIR / "google-client.json"
TOKEN_FILE = PRIVATE_DIR / "google-token.dpapi"


# --------------------------------------------------------------------------
# token at rest
# --------------------------------------------------------------------------
def _dpapi(value, decrypt=False):
    """Encrypt/decrypt with Windows DPAPI, bound to the current Windows user."""
    import ctypes
    from ctypes import wintypes

    class Blob(ctypes.Structure):
        _fields_ = [("size", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_byte))]

    raw = base64.b64decode(value) if decrypt else value.encode("utf-8")
    buf = ctypes.create_string_buffer(raw)
    src = Blob(len(raw), ctypes.cast(buf, ctypes.POINTER(ctypes.c_byte)))
    out = Blob()
    crypt = ctypes.WinDLL("crypt32", use_last_error=True)
    fn = crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
    if not fn(ctypes.byref(src), None, None, None, None, 1, ctypes.byref(out)):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        result = ctypes.string_at(out.data, out.size)
        return result.decode("utf-8") if decrypt else base64.b64encode(result).decode("ascii")
    finally:
        free = ctypes.WinDLL("kernel32").LocalFree
        free.argtypes = [ctypes.c_void_p]
        free.restype = ctypes.c_void_p
        free(out.data)


def install_client(source_json):
    """Copy client_id/client_secret into the private dir. Run once."""
    data = json.loads(Path(source_json).read_text(encoding="utf-8"))
    node = data.get("installed") or data.get("web") or {}
    if not str(node.get("client_id", "")).endswith(".apps.googleusercontent.com"):
        raise ValueError("Not a Google OAuth client file (no client_id).")
    if not node.get("client_secret"):
        raise ValueError("Not a Google *Desktop* OAuth client file (no client_secret).")
    if data.get("web"):
        raise ValueError("This is a Web client. Create a Desktop client instead.")
    PRIVATE_DIR.mkdir(parents=True, exist_ok=True)
    cfg = {"installed": {
        "client_id": node["client_id"],
        "client_secret": node["client_secret"],
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
        "redirect_uris": ["http://localhost"],
    }}
    tmp = CLIENT_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(cfg), encoding="utf-8")
    tmp.replace(CLIENT_FILE)
    try:
        os.chmod(CLIENT_FILE, 0o600)
    except OSError:
        pass
    return CLIENT_FILE


def find_client_json():
    """Locate the original Google OAuth client download, if it is still around.

    Lets `--connect` recover on its own instead of dead-ending on a missing file.
    """
    here = Path(__file__).resolve()
    roots = [here.parents[2],            # finance_pipeline
             here.parents[3],            # the project root that holds it
             Path.home() / "Downloads",
             Path.home() / "Desktop",
             Path.home() / "OneDrive" / "Desktop"]
    for root in roots:
        try:
            if not root.is_dir():
                continue
            # the download often sits one folder deep, so look there too
            cands = list(root.glob("client_secret*.json")) + \
                list(root.glob("*/client_secret*.json"))
            for cand in sorted(cands):
                try:
                    node = json.loads(cand.read_text(encoding="utf-8")).get("installed") or {}
                    if node.get("client_id", "").endswith(".apps.googleusercontent.com") \
                            and node.get("client_secret"):
                        return cand
                except (ValueError, OSError):
                    continue
        except OSError:
            continue
    return None


def _save_token(creds):
    PRIVATE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = TOKEN_FILE.with_suffix(".tmp")
    tmp.write_text(_dpapi(creds.to_json()), encoding="utf-8")
    tmp.replace(TOKEN_FILE)
    try:
        os.chmod(TOKEN_FILE, 0o600)
    except OSError:
        pass


def status():
    return {"client_installed": CLIENT_FILE.exists(),
            "connected": TOKEN_FILE.exists(),
            "private_dir": str(PRIVATE_DIR)}


def credentials(connect=False):
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow

    if connect:
        if not CLIENT_FILE.exists():
            # Self-heal rather than dead-end. The client file can be missing because
            # setup was never run, or because this process resolved a different
            # %LOCALAPPDATA% than the one it was installed under (running the
            # launcher elevated does exactly that). Either way, if the original
            # download is still on disk we can just install it again.
            found = find_client_json()
            if found:
                install_client(found)
            else:
                raise ValueError(
                    "No OAuth client installed.\n"
                    f"  Looked for : {CLIENT_FILE}\n"
                    f"  Folder exists: {CLIENT_FILE.parent.exists()}\n"
                    f"  LOCALAPPDATA : {os.environ.get('LOCALAPPDATA', '(not set)')}\n"
                    "  Searched for a client_secret*.json in Downloads, Desktop and\n"
                    "  this project, and found none.\n"
                    "  If you ran this as administrator, run it as yourself instead -\n"
                    "  an elevated process gets a different AppData folder.")
        flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_FILE), SCOPES)
        try:
            creds = flow.run_local_server(
                host="127.0.0.1", port=0, open_browser=True, timeout_seconds=900,
                authorization_prompt_message="",
                success_message="Northstar is connected to Gmail (read-only). "
                                "You can close this tab.")
        except Exception as exc:                       # noqa: BLE001
            # The consent happens in Google's own UI and needs a human click; a
            # timeout here means nobody got to the browser, not a broken setup.
            if "Timed out" in str(exc) or exc.__class__.__name__ == "WSGITimeoutError":
                raise ValueError(
                    "Nobody completed the Google sign-in within 15 minutes. "
                    "A browser tab should have opened asking you to allow read-only "
                    "Gmail access. Run this again and finish it in that tab.") from None
            raise
    else:
        if not TOKEN_FILE.exists():
            raise ValueError("Gmail is not connected yet. Run with --connect once.")
        creds = Credentials.from_authorized_user_info(
            json.loads(_dpapi(TOKEN_FILE.read_text(encoding="utf-8"), True)), SCOPES)
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
        if not creds.valid:
            raise ValueError("Google authorisation expired. Run with --connect again.")
    _save_token(creds)
    return creds


# --------------------------------------------------------------------------
# fetching
# --------------------------------------------------------------------------
def _html_part(payload):
    """Depth-first search for the text/html body of a MIME tree."""
    if payload.get("mimeType") == "text/html":
        data = payload.get("body", {}).get("data", "")
        if data:
            return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4)).decode("utf-8", "replace")
    for part in payload.get("parts", []) or []:
        found = _html_part(part)
        if found:
            return found
    return ""


def build_query(senders, days):
    """Sender-scoped query. Searches all labels but skips trash and spam, so an
    alert filed away by a Gmail filter is still found."""
    joined = " OR ".join("from:" + s for s in senders)
    return "(" + joined + ") newer_than:" + str(int(days)) + "d -in:trash -in:spam"


def fetch(senders, days=90, service=None, progress=None, known_ids=()):
    """Return raw alert messages. Read-only; nothing in the mailbox is modified.

    `known_ids` are skipped before their bodies are downloaded. Listing ids is one
    cheap call per 100 messages; fetching a body is a call each, so on a re-sync
    this is the difference between one request and a hundred.
    """
    if service is None:
        from googleapiclient.discovery import build
        service = build("gmail", "v1", credentials=credentials(), cache_discovery=False)

    query = build_query(senders, days)
    ids, page = [], None
    while True:
        res = service.users().messages().list(
            userId="me", q=query, maxResults=100, pageToken=page).execute()
        ids.extend(m["id"] for m in res.get("messages", []) or [])
        page = res.get("nextPageToken")
        if not page:
            break

    known = set(known_ids or ())
    seen_total = len(ids)
    ids = [i for i in ids if i not in known]
    if progress:
        progress(0, len(ids), seen_total - len(ids))

    out = []
    for n, mid in enumerate(ids, 1):
        full = service.users().messages().get(userId="me", id=mid, format="full").execute()
        headers = {h["name"].lower(): h["value"] for h in full["payload"].get("headers", [])}
        received = ""
        if full.get("internalDate"):
            from datetime import datetime, timezone
            received = datetime.fromtimestamp(
                int(full["internalDate"]) / 1000, timezone.utc).isoformat()
        out.append({
            "id": full["id"],
            "from": headers.get("from", ""),
            "subject": headers.get("subject", ""),
            "received": received,
            # issuers re-send the same alert as a new message; this header is stable
            "notification_id": headers.get("notification-id") or headers.get("x-notification-id", ""),
            "html": _html_part(full["payload"]),
        })
        if progress and n % 10 == 0:
            progress(n, len(ids), 0)
    return out


def redact(text):
    """Strip anything token-shaped before an error reaches a log or the screen."""
    text = re.sub(r"[A-Za-z0-9_\-]{24,}\.apps\.googleusercontent\.com", "<client-id>", str(text))
    text = re.sub(r"\b(ya29|1//)[A-Za-z0-9_\-\.]+", "<oauth-token>", text)
    return re.sub(r"GOCSPX-[A-Za-z0-9_\-]+", "<client-secret>", text)
