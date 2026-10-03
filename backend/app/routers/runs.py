from fastapi import APIRouter, HTTPException, Request

from ..db import get_db
from ..services.usage import log_event
from ..pipeline.orchestrator import counters_for
from ..pipeline.scope import chunks

router = APIRouter()


LIVE = ("queued", "running", "paused", "failed")  # finished runs keep the numbers saved at the end


def _with_live_counters(r: dict) -> dict:
    """A run stopped in the middle of a stage has stale saved numbers. Count the companies now."""
    if r["status"] in LIVE:
        r["counters"] = counters_for(r)
    else:
        (r.get("counters") or {}).pop("company_ids", None)
    return r


@router.get("/runs")
def list_runs():
    rows = get_db().table("runs").select("*, campaigns(name)").order("created_at", desc=True).limit(50).execute().data
    return [_with_live_counters(r) for r in rows]


@router.get("/runs/{rid}")
def get_run(rid: str):
    r = get_db().table("runs").select("*, campaigns(name,filters)").eq("id", rid).execute().data
    if not r:
        raise HTTPException(404)
    return _with_live_counters(r[0])


@router.get("/runs/{rid}/companies")
def run_companies(rid: str):
    """Every company of this run (or of a manual run's list), with the newest judgment score."""
    db = get_db()
    run = db.table("runs").select("id,counters").eq("id", rid).execute().data
    if not run:
        raise HTTPException(404)
    ids = (run[0].get("counters") or {}).get("company_ids")
    cols = "id,domain,name,country,size_estimate,status,fail_reason"
    if ids is None:
        rows = db.table("companies").select(cols).eq("run_id", rid).order("first_seen", desc=True).limit(1000).execute().data
    else:
        rows = []
        for part in chunks(ids):
            rows += db.table("companies").select(cols).in_("id", part).execute().data
    for part in chunks([r["id"] for r in rows]):
        js = db.table("judgments").select("company_id,fit_score,created_at").in_("company_id", part).order("created_at").execute().data
        score = {j["company_id"]: j["fit_score"] for j in js}
        for r in rows:
            r.setdefault("score", score.get(r["id"]))
    return rows


@router.post("/runs/{rid}/pause")
def pause(rid: str):
    get_db().table("runs").update({"status": "paused"}).eq("id", rid).eq("status", "running").execute()
    return {"ok": True}


@router.post("/runs/{rid}/resume")
async def resume(rid: str, request: Request):
    """Also works on a finished run: it picks up companies a stage limit left behind. Every stage gets a fresh limit."""
    db = get_db()
    r = db.table("runs").select("status,counters").eq("id", rid).execute().data
    if not r:
        raise HTTPException(404)
    if r[0]["status"] not in ("paused", "failed", "done"):
        raise HTTPException(409, f"This run is {r[0]['status']}.")
    counters = dict(r[0].get("counters") or {})
    counters.pop("stage_usage", None)
    counters.pop("limits_hit", None)
    db.table("runs").update({"status": "queued", "error": None, "counters": counters, "finished_at": None}).eq("id", rid).execute()
    await request.app.state.arq.enqueue_job("run_campaign_task", rid)
    log_event(rid, "info", "run", "resumed. every stage has a fresh limit")
    return {"ok": True}


@router.post("/runs/{rid}/cancel")
def cancel(rid: str):
    get_db().table("runs").update({"status": "cancelled"}).eq("id", rid).in_("status", ["queued", "running", "paused"]).execute()
    return {"ok": True}


@router.get("/runs/{rid}/events")
def events(rid: str, after: int = 0):
    return get_db().table("events").select("*").eq("run_id", rid).gt("id", after).order("id").limit(200).execute().data


@router.get("/events")
def all_events(after: int = 0, limit: int = 150):
    """The backend log for the whole app: runs, sending, replies, email edits. First call (after=0): the newest lines."""
    limit = max(1, min(limit, 300))
    q = get_db().table("events").select("*")
    if after:
        return q.gt("id", after).order("id").limit(limit).execute().data
    return list(reversed(q.order("id", desc=True).limit(limit).execute().data))
