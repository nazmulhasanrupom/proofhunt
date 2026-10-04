"""Which profile a request is for. The browser sends it in the X-Profile-Id header on every call."""
import uuid
from typing import Annotated

from fastapi import Depends, Header, HTTPException

from .db import get_db


def as_uuid(value: str | None) -> str | None:
    try:
        return str(uuid.UUID(value or ""))
    except ValueError:
        return None


def profile_id(x_profile_id: Annotated[str, Header()] = "") -> str:
    pid = as_uuid(x_profile_id)
    if not pid:
        raise HTTPException(400, "Pick a profile first")
    return pid


ProfileId = Annotated[str, Depends(profile_id)]


def require_profile(pid: str) -> dict:
    """The profile row, or a 404. For calls that create something that belongs to a profile."""
    r = get_db().table("profiles").select("id,name,parsed").eq("id", pid).execute().data
    if not r:
        raise HTTPException(404, "Profile not found")
    return r[0]
