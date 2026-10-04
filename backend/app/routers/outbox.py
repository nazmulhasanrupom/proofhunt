from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..db import get_db
from ..deps import ProfileId, require_profile
from ..sending import scheduler

router = APIRouter()

TEST_DOMAIN = "test-lead.invalid"  # .invalid can never be a real site


@router.get("/sending/status")
def sending_status():
    return scheduler.status()


@router.get("/outbox")
def outbox(pid: ProfileId, status: str | None = None, page: int = 0):
    q = get_db().table("messages").select(
        "id,lead_id,step,subject,body,status,scheduled_at,sent_at,error,gmail_message_id,evidence_ids, "
        "leads(timezone, companies(domain,name), people(name,email))"
    ).eq("profile_id", pid)
    if status:
        q = q.eq("status", status)
    rows = q.order("sent_at", desc=True, nullsfirst=True).range(page * 100, page * 100 + 99).execute().data
    # a draft shows here only when its lead already started (for example after Unapprove). Other drafts live in the Review queue.
    live = {l["id"] for l in get_db().table("leads").select("id").eq("profile_id", pid).eq("stage", "in_sequence").execute().data}
    return [r for r in rows if r["status"] != "draft" or r["lead_id"] in live]


@router.get("/replies")
def replies(pid: ProfileId, page: int = 0):
    return (get_db().table("replies")
            .select("*, leads(id,stage, companies(domain,name), people(name,email))").eq("profile_id", pid)
            .order("received_at", desc=True).range(page * 100, page * 100 + 99).execute().data)


class TestLead(BaseModel):
    timezone: str = "UTC"


@router.post("/gmail/test-lead")
def make_test_lead(body: TestLead, pid: ProfileId):
    """A lead whose email is YOUR OWN Gmail address. Use it for the one real test send. No LLM, no credits."""
    require_profile(pid)
    db = get_db()
    st = db.table("settings").select("gmail_address,sender_name,postal_address").eq("id", 1).single().execute().data
    me = st.get("gmail_address")
    if not me:
        raise HTTPException(409, "Connect Gmail first")
    db.table("companies").delete().eq("domain", TEST_DOMAIN).eq("profile_id", pid).execute()  # cascade: lead, people, messages, replies
    db.table("do_not_contact").delete().eq("value", me).execute()        # a "no" reply test must not lock you out
    co = db.table("companies").insert({"domain": TEST_DOMAIN, "name": "Test Lead", "status": "qualified",
                                       "source": "test", "profile_id": pid}).execute().data[0]
    person = db.table("people").insert({"company_id": co["id"], "name": "Test Person", "title": "Founder",
                                        "email": me, "email_kind": "personal", "email_source": "test",
                                        "mx_ok": True, "selected": True}).execute().data[0]
    lead = db.table("leads").insert({"company_id": co["id"], "person_id": person["id"], "profile_id": pid, "stage": "ready",
                                     "score": 100, "timezone": body.timezone, "notes": "test lead: emails go to your own address"}).execute().data[0]
    opt = 'If this isn\'t relevant, reply "no" and I won\'t email again.'
    sig = "\n".join(x for x in [st.get("sender_name"), st.get("postal_address")] if x)
    texts = [("proofhunt test", "Hi, this is test email number 1 from Proofhunt."),
             ("Re: lead finder test", "Hi, this is test follow-up number 2."),
             ("Re: lead finder test", "Hi, this is test follow-up number 3."),
             ("Re: lead finder test", "Hi, this is the test break-up email.")]
    db.table("messages").insert([
        {"lead_id": lead["id"], "profile_id": pid, "step": i, "subject": s, "status": "draft",
         "body": f"{t}\n\n{opt}" + (f"\n\n{sig}" if sig else "")}
        for i, (s, t) in enumerate(texts)
    ]).execute()
    return {"ok": True, "lead_id": lead["id"], "email": me}
