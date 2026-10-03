"""Gmail: OAuth over httpx, Fernet-encrypted refresh token, send, read.

The Google client is sync. Callers run these functions with asyncio.to_thread.
"""
import base64
from email.message import EmailMessage
from email.utils import formataddr
from urllib.parse import urlencode

import httpx
from cryptography.fernet import Fernet, InvalidToken
from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from ..config import settings
from ..db import get_db

SCOPES = ["https://www.googleapis.com/auth/gmail.send", "https://www.googleapis.com/auth/gmail.readonly"]
AUTH_URI = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URI = "https://oauth2.googleapis.com/token"
REVOKE_URI = "https://oauth2.googleapis.com/revoke"
PROFILE_URI = "https://gmail.googleapis.com/gmail/v1/users/me/profile"
RATE_REASONS = {"rateLimitExceeded", "userRateLimitExceeded", "dailyLimitExceeded", "sendingLimitExceeded"}


class GmailError(Exception):
    """Permanent error. Do not retry."""


class GmailAuthError(GmailError):
    """Token is no longer valid. The user must reconnect Gmail."""


class GmailTransient(GmailError):
    """Rate limit or server error. Try again later."""


# ---- token storage -------------------------------------------------------

def _fernet() -> Fernet:
    try:
        return Fernet(settings.app_secret_key.encode())
    except (ValueError, TypeError):
        raise GmailError("APP_SECRET_KEY in .env is not a valid key. Make one with: "
                         "python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\"") from None


def encrypt(text: str) -> str:
    return _fernet().encrypt(text.encode()).decode()


def decrypt(text: str) -> str:
    try:
        return _fernet().decrypt(text.encode()).decode()
    except InvalidToken:  # APP_SECRET_KEY changed since the token was saved
        raise GmailAuthError("Saved Gmail login cannot be read (APP_SECRET_KEY changed). Reconnect Gmail.") from None


def _settings_row() -> dict:
    return (get_db().table("settings").select("gmail_address,gmail_refresh_token_enc").eq("id", 1).execute().data or [{}])[0]


def is_connected() -> bool:
    return bool(_settings_row().get("gmail_refresh_token_enc"))


def clear_token(keep_address: bool = True):
    """Forget the token. Keeping the address lets the UI show 'Reconnect Gmail'."""
    data = {"gmail_refresh_token_enc": None}
    if not keep_address:
        data["gmail_address"] = None
    get_db().table("settings").update(data).eq("id", 1).execute()


# ---- OAuth ---------------------------------------------------------------

def auth_url(state: str) -> str:
    q = {
        "client_id": settings.google_client_id, "redirect_uri": settings.google_redirect_uri,
        "response_type": "code", "scope": " ".join(SCOPES), "state": state,
        "access_type": "offline", "prompt": "consent",  # prompt=consent makes Google return a refresh token
    }
    return f"{AUTH_URI}?{urlencode(q)}"


async def exchange_code(code: str) -> dict:
    """Swap the OAuth code for tokens. Returns {refresh_token, email}."""
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.post(TOKEN_URI, data={
            "code": code, "client_id": settings.google_client_id, "client_secret": settings.google_client_secret,
            "redirect_uri": settings.google_redirect_uri, "grant_type": "authorization_code",
        })
        if r.status_code != 200:
            raise GmailError(f"Google refused the code: {r.json().get('error_description') or r.text[:200]}")
        tok = r.json()
        granted = set((tok.get("scope") or "").split())
        if not set(SCOPES) <= granted:
            raise GmailError("Missing permission. Tick every box on the Google consent screen.")
        if not tok.get("refresh_token"):
            raise GmailError("Google sent no refresh token. Remove the app at myaccount.google.com/permissions and retry.")
        p = await c.get(PROFILE_URI, headers={"Authorization": f"Bearer {tok['access_token']}"})
        if p.status_code != 200:
            raise GmailError("Could not read the Gmail profile.")
        return {"refresh_token": tok["refresh_token"], "email": p.json()["emailAddress"].lower()}


async def revoke(refresh_token: str):
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            await c.post(REVOKE_URI, data={"token": refresh_token})
    except httpx.HTTPError:
        pass  # best effort: we clear our copy anyway


def save_connection(refresh_token: str, email: str):
    get_db().table("settings").update({
        "gmail_address": email, "gmail_refresh_token_enc": encrypt(refresh_token), "updated_at": "now",
    }).eq("id", 1).execute()


def stored_refresh_token() -> str | None:
    enc = _settings_row().get("gmail_refresh_token_enc")
    return decrypt(enc) if enc else None


# ---- API client ----------------------------------------------------------

def _service():
    token = stored_refresh_token()
    if not token:
        raise GmailAuthError("Gmail is not connected")
    creds = Credentials(None, refresh_token=token, token_uri=TOKEN_URI,
                        client_id=settings.google_client_id, client_secret=settings.google_client_secret)
    try:
        creds.refresh(Request())
    except RefreshError as e:
        if "invalid_grant" in str(e) or "invalid_client" in str(e) or "unauthorized" in str(e).lower():
            clear_token()
            raise GmailAuthError("Gmail token is no longer valid. Reconnect Gmail.") from e
        raise GmailTransient(f"token refresh failed: {str(e)[:200]}") from e
    except Exception as e:  # network trouble
        raise GmailTransient(f"token refresh failed: {type(e).__name__}") from e
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


def _call(fn):
    """Run one API request and turn Google errors into our three error types."""
    try:
        return fn()
    except HttpError as e:
        status = int(e.resp.status)
        reason = ""
        try:
            reason = (e.error_details or [{}])[0].get("reason", "") if e.error_details else ""
        except Exception:
            pass
        if status == 401:
            clear_token()
            raise GmailAuthError("Gmail rejected the token. Reconnect Gmail.") from e
        if status == 429 or status >= 500 or reason in RATE_REASONS:
            raise GmailTransient(f"Gmail {status} {reason}".strip()) from e
        raise GmailError(f"Gmail {status}: {str(e)[:200]}") from e
    except (httpx.HTTPError, OSError) as e:
        raise GmailTransient(f"network error: {type(e).__name__}") from e


# ---- send ----------------------------------------------------------------

def build_message(from_name: str, from_addr: str, to: str, subject: str, body: str,
                  root_rfc_id: str | None = None) -> EmailMessage:
    """Plain text mail. Follow-ups point at the main email through In-Reply-To and References."""
    msg = EmailMessage()
    msg["From"] = formataddr((from_name, from_addr)) if from_name else from_addr
    msg["To"] = to
    msg["Subject"] = " ".join((subject or "").split())  # no line breaks in a header
    msg["List-Unsubscribe"] = f"<mailto:{from_addr}?subject=unsubscribe>"
    if root_rfc_id:
        msg["In-Reply-To"] = root_rfc_id
        msg["References"] = root_rfc_id
    msg.set_content(body, charset="utf-8")
    return msg


def send(msg: EmailMessage, thread_id: str | None = None) -> dict:
    """Send one message. Returns {gmail_message_id, gmail_thread_id, rfc_message_id}."""
    svc = _service()
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    body = {"raw": raw}
    if thread_id:
        body["threadId"] = thread_id
    sent = _call(lambda: svc.users().messages().send(userId="me", body=body).execute())
    meta = _call(lambda: svc.users().messages().get(
        userId="me", id=sent["id"], format="metadata", metadataHeaders=["Message-ID"]).execute())
    return {"gmail_message_id": sent["id"], "gmail_thread_id": sent["threadId"],
            "rfc_message_id": header(meta, "Message-ID")}


# ---- read ----------------------------------------------------------------

def header(msg: dict, name: str) -> str | None:
    for h in (msg.get("payload") or {}).get("headers", []):
        if h["name"].lower() == name.lower():
            return h["value"]
    return None


def get_thread(thread_id: str) -> dict:
    svc = _service()
    return _call(lambda: svc.users().threads().get(
        userId="me", id=thread_id, format="metadata",
        metadataHeaders=["From", "Message-ID", "Auto-Submitted"]).execute())


def get_message(message_id: str) -> dict:
    svc = _service()
    return _call(lambda: svc.users().messages().get(userId="me", id=message_id, format="full").execute())


def search_ids(query: str, limit: int = 25) -> list[str]:
    svc = _service()
    r = _call(lambda: svc.users().messages().list(userId="me", q=query, maxResults=limit).execute())
    return [m["id"] for m in r.get("messages", [])]
