from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from ..db import get_db
from ..pipeline import sequences

router = APIRouter()


class LeadPatch(BaseModel):
    stage: str | None = None
    notes: str | None = None


class DemoUrl(BaseModel):
    demo_url: str


@router.get("/leads")
def list_leads(stage: str | None = None, q: str | None = None, page: int = 0):
    qry = get_db().table("leads").select("*, companies(domain,name,country), people(name,title,email)")
    if stage:
        qry = qry.eq("stage", stage)
    if q:
        ids = [c["id"] for c in get_db().table("companies").select("id").or_(f"domain.ilike.%{q}%,name.ilike.%{q}%").limit(200).execute().data]
        qry = qry.in_("company_id", ids or ["00000000-0000-0000-0000-000000000000"])
    return qry.order("created_at", desc=True).range(page * 50, page * 50 + 49).execute().data


@router.get("/leads/{lid}")
def get_lead(lid: str):
    db = get_db()
    r = db.table("leads").select("*, companies(*), people(*), judgments(*)").eq("id", lid).execute().data
    if not r:
        raise HTTPException(404)
    return {**r[0],
            "messages": db.table("messages").select("*").eq("lead_id", lid).order("step").execute().data,
            "assets": db.table("assets").select("*").eq("lead_id", lid).execute().data}


@router.patch("/leads/{lid}")
def patch_lead(lid: str, body: LeadPatch):
    data = body.model_dump(exclude_none=True)
    if data:
        get_db().table("leads").update({**data, "updated_at": "now"}).eq("id", lid).execute()
    return {"ok": True}


@router.patch("/leads/{lid}/demo-url")
def set_demo(lid: str, body: DemoUrl):
    get_db().table("assets").update({"demo_url": body.demo_url}).eq("lead_id", lid).eq("kind", "demo_spec").execute()
    return {"ok": True}


@router.post("/leads/{lid}/regenerate")
async def regenerate(lid: str):
    db = get_db()
    lead = db.table("leads").select("*").eq("id", lid).single().execute().data
    if db.table("messages").select("id").eq("lead_id", lid).in_("status", ["sent", "sending"]).execute().data:
        raise HTTPException(409, "Emails already sent")
    db.table("messages").delete().eq("lead_id", lid).execute()
    await sequences.build_sequence(lead, None)
    return {"ok": True}


@router.get("/review")
def review_queue():
    db = get_db()
    leads = db.table("leads").select("*, companies(domain,name), people(name,title,email,email_kind), judgments(problem,fix,fit_score)").eq("stage", "ready").order("score", desc=True).execute().data
    for l in leads:
        l["messages"] = db.table("messages").select("*").eq("lead_id", l["id"]).order("step").execute().data
        ids = sorted({i for m in l["messages"] for i in (m["evidence_ids"] or [])})
        l["evidence"] = db.table("evidence").select("id,quote,url,kind").in_("id", ids).execute().data if ids else []
        l["assets"] = db.table("assets").select("kind,content_md,public_token").eq("lead_id", l["id"]).execute().data
    return leads


@router.post("/leads/{lid}/approve")
def approve(lid: str):
    sequences.approve_lead(lid)
    return {"ok": True}


@router.post("/leads/{lid}/skip")
def skip(lid: str):
    db = get_db()
    db.table("messages").update({"status": "cancelled"}).eq("lead_id", lid).neq("status", "sent").execute()
    db.table("leads").update({"stage": "lost", "notes": "skipped in review"}).eq("id", lid).execute()
    return {"ok": True}
