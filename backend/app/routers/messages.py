from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..db import get_db
from ..pipeline import rewrite
from ..services.usage import BudgetExceeded, log_event

router = APIRouter()

UNSENT = ["draft", "approved", "scheduled", "failed"]   # can still be changed
LIVE = ["draft", "approved", "scheduled"]


class MsgPatch(BaseModel):
    subject: str | None = None
    body: str | None = None


class RewriteIn(BaseModel):
    instruction: str = ""


def _msg(mid: str) -> dict:
    r = get_db().table("messages").select("*").eq("id", mid).execute().data
    if not r:
        raise HTTPException(404, "Message not found")
    return r[0]


def _lead_name(lead_id: str) -> str:
    r = get_db().table("leads").select("companies(domain,name)").eq("id", lead_id).execute().data
    c = (r[0]["companies"] if r else None) or {}
    return c.get("name") or c.get("domain") or "lead"


def _settle_lead(lead_id: str):
    """After a delete: a lead with nothing sent and nothing left to send is closed, not left hanging."""
    db = get_db()
    msgs = db.table("messages").select("status").eq("lead_id", lead_id).execute().data
    if not any(m["status"] in LIVE + ["sent", "sending"] for m in msgs):
        db.table("leads").update({"stage": "lost", "notes": "emails deleted", "updated_at": "now"}).eq("id", lead_id).in_("stage", ["ready", "in_sequence"]).execute()


@router.patch("/messages/{mid}")
def patch_message(mid: str, body: MsgPatch):
    m = _msg(mid)
    if m["status"] not in UNSENT:
        raise HTTPException(409, f"This email is {m['status']}. Only emails that are not sent yet can be edited.")
    data = body.model_dump(exclude_none=True)
    if data:
        data["error"] = None  # a manual edit clears the "needs manual edit" flag
        get_db().table("messages").update(data).eq("id", mid).in_("status", UNSENT).execute()
        log_event(None, "info", "email", f"{_lead_name(m['lead_id'])}: step {m['step']} edited", lead_id=m["lead_id"])
    return {"ok": True}


@router.post("/messages/{mid}/rewrite")
async def rewrite_message(mid: str, body: RewriteIn):
    """Returns a new version. Nothing is saved until the user saves it."""
    m = _msg(mid)
    if m["status"] not in UNSENT:
        raise HTTPException(409, f"This email is {m['status']}. Only emails that are not sent yet can be rewritten.")
    try:
        out = await rewrite.rewrite_message(m, body.instruction)
    except BudgetExceeded as e:
        raise HTTPException(429, str(e))
    except Exception as e:
        log_event(None, "error", "email", f"rewrite failed: {e}", lead_id=m["lead_id"])
        raise HTTPException(502, f"The AI could not rewrite this email: {str(e)[:200]}")
    log_event(None, "info", "email", f"{_lead_name(m['lead_id'])}: step {m['step']} rewritten with AI (not saved yet)", lead_id=m["lead_id"])
    return out


@router.post("/messages/{mid}/retry")
def retry_message(mid: str):
    """Put a failed message back in the queue. Step 1+ gets a new time from the engine."""
    get_db().table("messages").update({"status": "approved", "error": None, "scheduled_at": None}).eq("id", mid).eq("status", "failed").execute()
    return {"ok": True}


@router.post("/messages/{mid}/approve")
def approve_message(mid: str):
    """For a draft that belongs to a lead already in its sequence (for example after Unapprove)."""
    m = _msg(mid)
    if m["status"] != "draft":
        raise HTTPException(409, f"This email is {m['status']}, not a draft.")
    lead = get_db().table("leads").select("stage").eq("id", m["lead_id"]).single().execute().data
    if lead["stage"] != "in_sequence":
        raise HTTPException(409, "Approve the whole lead in the Review queue.")
    get_db().table("messages").update({"status": "approved", "scheduled_at": None}).eq("id", mid).eq("status", "draft").execute()
    log_event(None, "info", "email", f"{_lead_name(m['lead_id'])}: step {m['step']} approved", lead_id=m["lead_id"])
    return {"ok": True}


@router.post("/messages/{mid}/unapprove")
def unapprove_message(mid: str):
    """Back to draft: this email and every later email that is not sent. If nothing was sent, the lead returns to the Review queue."""
    db = get_db()
    m = _msg(mid)
    if m["status"] not in ["approved", "scheduled", "failed"]:
        raise HTTPException(409, f"This email is {m['status']}. Only approved, scheduled or failed emails can be unapproved.")
    db.table("messages").update({"status": "draft", "scheduled_at": None, "error": None}).eq("lead_id", m["lead_id"]).gte("step", m["step"]).in_(
        "status", ["approved", "scheduled", "failed"]).execute()
    sent = db.table("messages").select("id").eq("lead_id", m["lead_id"]).in_("status", ["sent", "sending"]).execute().data
    if not sent:
        db.table("leads").update({"stage": "ready", "updated_at": "now"}).eq("id", m["lead_id"]).eq("stage", "in_sequence").execute()
    log_event(None, "info", "email", f"{_lead_name(m['lead_id'])}: step {m['step']} unapproved" + ("" if sent else " (lead is back in the Review queue)"), lead_id=m["lead_id"])
    return {"ok": True, "back_in_review": not sent}


@router.delete("/messages/{mid}")
def delete_message(mid: str):
    """Delete an email that is not sent. Later emails of the same lead are cancelled (a follow-up needs the step before it)."""
    db = get_db()
    m = _msg(mid)
    if m["status"] in ("sent", "sending"):
        raise HTTPException(409, "This email is already sent. A sent email cannot be deleted.")
    db.table("messages").update({"status": "cancelled", "scheduled_at": None}).eq("lead_id", m["lead_id"]).gt("step", m["step"]).in_("status", LIVE + ["failed"]).execute()
    db.table("messages").delete().eq("id", mid).execute()
    _settle_lead(m["lead_id"])
    log_event(None, "info", "email", f"{_lead_name(m['lead_id'])}: step {m['step']} deleted (later unsent steps cancelled)", lead_id=m["lead_id"])
    return {"ok": True}
