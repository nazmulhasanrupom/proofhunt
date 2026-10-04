from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from ..db import get_db
from ..deps import ProfileId, require_profile
from ..pipeline import campaign_fill
from ..schemas import CampaignFilters
from ..services.usage import BudgetExceeded, log_event
from .stats import credits_left

router = APIRouter()


class CampaignIn(BaseModel):
    name: str
    filters: CampaignFilters = CampaignFilters()


class AiFillIn(BaseModel):
    name: str = ""
    hint: str = Field("", max_length=500)       # what the user wants, in their own words (optional)
    filters: CampaignFilters = CampaignFilters()  # the form now: fields the AI leaves out keep these values


@router.post("/campaigns/ai-fill")
async def ai_fill(body: AiFillIn, pid: ProfileId):
    """AI recommended fill. Returns a full set of filters for the form. Nothing is saved."""
    require_profile(pid)
    try:
        out = await campaign_fill.suggest(pid, body.name, body.hint, body.filters.model_dump(), credits_left())
    except BudgetExceeded as e:
        raise HTTPException(429, str(e))
    except Exception as e:
        log_event(None, "error", "campaign", f"AI recommended fill failed: {e}", profile_id=pid)
        raise HTTPException(502, f"The AI could not make a recommendation: {str(e)[:200]}")
    log_event(None, "info", "campaign", f"AI recommended fill made ({len(out['filters']['company']['webKeywords'])} keywords, "
                                        f"scan {out['filters']['maxCompaniesToScan']})", profile_id=pid)
    return out


def _campaign(cid: str, pid: str) -> dict:
    """The campaign, if it belongs to this profile."""
    r = get_db().table("campaigns").select("*").eq("id", cid).eq("profile_id", pid).execute().data
    if not r:
        raise HTTPException(404, "Campaign not found")
    return r[0]


@router.get("/campaigns")
def list_campaigns(pid: ProfileId):
    return get_db().table("campaigns").select("*").eq("profile_id", pid).order("created_at", desc=True).execute().data


@router.post("/campaigns")
def create_campaign(body: CampaignIn, pid: ProfileId):
    require_profile(pid)
    return get_db().table("campaigns").insert({
        "name": body.name, "profile_id": pid, "filters": body.filters.model_dump()}).execute().data[0]


@router.get("/campaigns/{cid}")
def get_campaign(cid: str, pid: ProfileId):
    return _campaign(cid, pid)


@router.put("/campaigns/{cid}")
def update_campaign(cid: str, body: CampaignIn, pid: ProfileId):
    _campaign(cid, pid)
    return get_db().table("campaigns").update({"name": body.name, "filters": body.filters.model_dump()}).eq("id", cid).execute().data[0]


@router.delete("/campaigns/{cid}")
def delete_campaign(cid: str, pid: ProfileId):
    _campaign(cid, pid)
    get_db().table("campaigns").delete().eq("id", cid).execute()
    return {"ok": True}


@router.post("/campaigns/{cid}/runs")
async def start_run(cid: str, request: Request, pid: ProfileId):
    _campaign(cid, pid)
    db = get_db()
    run = db.table("runs").insert({"campaign_id": cid, "profile_id": pid, "status": "queued"}).execute().data[0]
    await request.app.state.arq.enqueue_job("run_campaign_task", run["id"])
    return run
