from fastapi import APIRouter
from pydantic import BaseModel

from ..db import get_db

router = APIRouter()


class MsgPatch(BaseModel):
    subject: str | None = None
    body: str | None = None


@router.patch("/messages/{mid}")
def patch_message(mid: str, body: MsgPatch):
    data = body.model_dump(exclude_none=True)
    if data:
        data["error"] = None  # a manual edit clears the "needs manual edit" flag
        get_db().table("messages").update(data).eq("id", mid).eq("status", "draft").execute()
    return {"ok": True}


@router.post("/messages/{mid}/retry")
def retry_message(mid: str):
    """Put a failed message back in the queue. Step 1+ gets a new time from the engine."""
    get_db().table("messages").update({"status": "approved", "error": None, "scheduled_at": None}).eq("id", mid).eq("status", "failed").execute()
    return {"ok": True}
