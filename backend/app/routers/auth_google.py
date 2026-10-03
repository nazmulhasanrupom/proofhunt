import secrets
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse

from ..config import settings
from ..services import gmail

router = APIRouter(prefix="/auth/google")


def _back(status: str, reason: str = "") -> RedirectResponse:
    url = f"{settings.frontend_url}/settings?gmail={status}"
    return RedirectResponse(url + (f"&reason={quote(reason)}" if reason else ""))


@router.post("/start")
async def start(request: Request):
    """Returns the Google login URL. The browser opens it. (POST, so the password header can be sent.)"""
    if not settings.google_client_id or not settings.google_client_secret:
        raise HTTPException(400, "GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET are not set in .env")
    state = secrets.token_urlsafe(24)
    await request.app.state.arq.set(f"oauth:state:{state}", "1", ex=600)  # CSRF check in the callback
    return {"url": gmail.auth_url(state)}


@router.get("/callback")
async def callback(request: Request, code: str | None = None, state: str | None = None, error: str | None = None):
    if error:
        return _back("error", "Google said: " + error)
    if not code or not state or not await request.app.state.arq.getdel(f"oauth:state:{state}"):
        return _back("error", "Login link expired. Click Connect Gmail again.")
    try:
        got = await gmail.exchange_code(code)
    except gmail.GmailError as e:
        return _back("error", str(e))
    gmail.save_connection(got["refresh_token"], got["email"])
    return _back("connected")


@router.post("/disconnect")
async def disconnect():
    token = gmail.stored_refresh_token()
    if token:
        await gmail.revoke(token)
    gmail.clear_token(keep_address=False)
    return {"ok": True}
