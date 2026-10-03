from fastapi import APIRouter, HTTPException, Request

from ..db import get_db

router = APIRouter()


@router.get("/runs")
def list_runs():
    return get_db().table("runs").select("*, campaigns(name)").order("created_at", desc=True).limit(50).execute().data


@router.get("/runs/{rid}")
def get_run(rid: str):
    r = get_db().table("runs").select("*").eq("id", rid).execute().data
    if not r:
        raise HTTPException(404)
    return r[0]


@router.post("/runs/{rid}/pause")
def pause(rid: str):
    get_db().table("runs").update({"status": "paused"}).eq("id", rid).eq("status", "running").execute()
    return {"ok": True}


@router.post("/runs/{rid}/resume")
async def resume(rid: str, request: Request):
    get_db().table("runs").update({"status": "queued", "error": None}).eq("id", rid).in_("status", ["paused", "failed"]).execute()
    await request.app.state.arq.enqueue_job("run_campaign_task", rid)
    return {"ok": True}


@router.post("/runs/{rid}/cancel")
def cancel(rid: str):
    get_db().table("runs").update({"status": "cancelled"}).eq("id", rid).in_("status", ["queued", "running", "paused"]).execute()
    return {"ok": True}


@router.get("/runs/{rid}/events")
def events(rid: str, after: int = 0):
    return get_db().table("events").select("*").eq("run_id", rid).gt("id", after).order("id").limit(200).execute().data
