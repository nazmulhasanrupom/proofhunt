import re

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..config import settings as env
from ..db import get_db

router = APIRouter()
HIDDEN = {"gmail_refresh_token_enc"}


class SettingsPut(BaseModel):
    sender_name: str | None = None
    sender_title: str | None = None
    signature: str | None = None
    postal_address: str | None = None
    auto_send: bool | None = None
    daily_send_cap: int | None = None
    warmup_enabled: bool | None = None
    send_window_start: str | None = None
    send_window_end: str | None = None
    min_gap_seconds: int | None = None
    max_gap_seconds: int | None = None
    followup_days: list[int] | None = None
    firecrawl_start_balance: int | None = None


def _hhmm(v: str) -> str:
    if not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", v):
        raise HTTPException(422, "Time must look like 09:00")
    return v


@router.get("/settings")
def get_settings():
    r = get_db().table("settings").select("*").eq("id", 1).single().execute().data
    tok = r.get("gmail_refresh_token_enc")
    r = {k: v for k, v in r.items() if k not in HIDDEN}
    r["send_window_start"] = (r.get("send_window_start") or "09:00")[:5]
    r["send_window_end"] = (r.get("send_window_end") or "16:30")[:5]
    r["gmail_connected"] = bool(tok)
    r["dry_run"] = env.dry_run
    return r


@router.put("/settings")
def put_settings(body: SettingsPut):
    data = body.model_dump(exclude_none=True)
    if "daily_send_cap" in data:
        data["daily_send_cap"] = max(1, min(50, data["daily_send_cap"]))
    for k in ("send_window_start", "send_window_end"):
        if k in data:
            data[k] = _hhmm(data[k])
    cur = get_settings()
    lo, hi = data.get("send_window_start", cur["send_window_start"]), data.get("send_window_end", cur["send_window_end"])
    if lo >= hi:
        raise HTTPException(422, "Window start must be before window end")
    gmin, gmax = data.get("min_gap_seconds", cur["min_gap_seconds"]), data.get("max_gap_seconds", cur["max_gap_seconds"])
    if gmin < 60 or gmin > gmax:
        raise HTTPException(422, "Gap: minimum 60 seconds, and min must not be above max")
    if "followup_days" in data and (len(data["followup_days"]) != 3 or not all(1 <= d <= 30 for d in data["followup_days"])):
        raise HTTPException(422, "Follow-up days: three numbers from 1 to 30")
    if "firecrawl_start_balance" in data and "firecrawl_start_balance" not in cur:
        raise HTTPException(409, "Run backend/migrations/002_firecrawl_balance.sql in Supabase Studio first")
    if data:
        get_db().table("settings").update({**data, "updated_at": "now"}).eq("id", 1).execute()
    return get_settings()
