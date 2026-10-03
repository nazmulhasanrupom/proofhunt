from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from ..db import get_db
from ..schemas import CampaignFilters

router = APIRouter()


class CampaignIn(BaseModel):
    name: str
    filters: CampaignFilters = CampaignFilters()


@router.get("/campaigns")
def list_campaigns():
    return get_db().table("campaigns").select("*").order("created_at", desc=True).execute().data


@router.post("/campaigns")
def create_campaign(body: CampaignIn):
    prof = get_db().table("profiles").select("id").eq("is_active", True).limit(1).execute().data
    if not prof:
        raise HTTPException(400, "Upload a CV first")
    return get_db().table("campaigns").insert({
        "name": body.name, "profile_id": prof[0]["id"], "filters": body.filters.model_dump()}).execute().data[0]


@router.get("/campaigns/{cid}")
def get_campaign(cid: str):
    r = get_db().table("campaigns").select("*").eq("id", cid).execute().data
    if not r:
        raise HTTPException(404)
    return r[0]


@router.put("/campaigns/{cid}")
def update_campaign(cid: str, body: CampaignIn):
    return get_db().table("campaigns").update({"name": body.name, "filters": body.filters.model_dump()}).eq("id", cid).execute().data[0]


@router.delete("/campaigns/{cid}")
def delete_campaign(cid: str):
    get_db().table("campaigns").delete().eq("id", cid).execute()
    return {"ok": True}


@router.post("/campaigns/{cid}/runs")
async def start_run(cid: str, request: Request):
    db = get_db()
    run = db.table("runs").insert({"campaign_id": cid, "status": "queued"}).execute().data[0]
    await request.app.state.arq.enqueue_job("run_campaign_task", run["id"])
    return run
