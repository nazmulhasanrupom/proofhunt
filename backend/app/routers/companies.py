from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from ..db import get_db
from ..pipeline import judge as judge_mod
from ..pipeline.scope import chunks
from ..services.usage import log_event

router = APIRouter()
PAGE = 50


@router.get("/companies")
def list_companies(status: str | None = None, q: str | None = None, page: int = 0):
    qry = get_db().table("companies").select("id,domain,name,country,size_estimate,size_bucket,keyword_hits,status,fail_reason,run_id,first_seen")
    if status:
        qry = qry.eq("status", status)
    if q:
        qry = qry.or_(f"domain.ilike.%{q}%,name.ilike.%{q}%")
    rows = qry.order("first_seen", desc=True).range(page * PAGE, page * PAGE + PAGE - 1).execute().data
    if rows:
        js = (get_db().table("judgments").select("company_id,fit_score,created_at")
              .in_("company_id", [r["id"] for r in rows]).order("created_at").execute().data)
        score = {j["company_id"]: j["fit_score"] for j in js}  # oldest first, so the newest wins
        for r in rows:
            r["score"] = score.get(r["id"])
    return rows


@router.get("/companies/ids")
def company_ids(status: str | None = None, q: str | None = None):
    """Ids of every company that matches the filter (for 'select all'). Capped at 2000."""
    qry = get_db().table("companies").select("id")
    if status:
        qry = qry.eq("status", status)
    if q:
        qry = qry.or_(f"domain.ilike.%{q}%,name.ilike.%{q}%")
    return [r["id"] for r in qry.order("first_seen", desc=True).limit(2000).execute().data]


class QualifyIn(BaseModel):
    ids: list[str]
    campaign_id: str | None = None


# A company in one of these states starts again. Audited pages are reused, so only a never-audited company costs credits.
RESTART = {"new", "auditing", "failed", "filtered_out", "no_contact", "rejected", "maybe", "judged"}
CREDITS_PER_AUDIT = 4  # home page + up to 3 more pages


@router.post("/companies/qualify")
async def qualify(body: QualifyIn, request: Request):
    """Start qualifying these companies now: audit -> extract -> contact -> judge -> report -> emails.
    Makes a manual run (one per campaign) so it shows in Activity, with its own stage limits."""
    db = get_db()
    ids = list(dict.fromkeys(body.ids))[:1000]
    if not ids:
        raise HTTPException(422, "Pick at least one company")
    comps = []
    for part in chunks(ids):
        comps += db.table("companies").select("id,domain,status,run_id").in_("id", part).execute().data
    if not comps:
        raise HTTPException(404, "Companies not found")
    with_pages: set[str] = set()
    for part in chunks([c["id"] for c in comps]):
        with_pages |= {p["company_id"] for p in db.table("pages").select("company_id").in_("company_id", part).execute().data}

    # which campaign decides the filters: the one given, else the one that found the company, else the newest
    runs = {r["id"]: r["campaign_id"] for r in db.table("runs").select("id,campaign_id").execute().data}
    newest = (db.table("campaigns").select("id").order("created_at", desc=True).limit(1).execute().data or [{}])[0].get("id")
    valid = {c["id"] for c in db.table("campaigns").select("id").execute().data}
    if body.campaign_id and body.campaign_id not in valid:
        raise HTTPException(404, "Campaign not found")
    groups: dict[str, list[str]] = {}
    credits = 0
    for c in comps:
        camp = body.campaign_id or runs.get(c["run_id"]) or newest
        if not camp:
            raise HTTPException(409, "Create a campaign first. Its filters decide who qualifies.")
        if c["status"] in RESTART:
            start = "audited" if c["id"] in with_pages else "new"
            db.table("companies").update({"status": start, "fail_reason": None}).eq("id", c["id"]).execute()
            credits += CREDITS_PER_AUDIT if start == "new" else 0
        groups.setdefault(camp, []).append(c["id"])

    started = []
    for camp, gids in groups.items():
        run = db.table("runs").insert({"campaign_id": camp, "status": "queued",
                                       "counters": {"company_ids": gids, "manual": True}}).execute().data[0]
        await request.app.state.arq.enqueue_job("run_campaign_task", run["id"])
        log_event(run["id"], "info", "qualify", f"manual qualify queued for {len(gids)} compan{'y' if len(gids) == 1 else 'ies'}: "
                  + ", ".join(c["domain"] for c in comps if c["id"] in gids)[:300])
        started.append({"run_id": run["id"], "count": len(gids)})
    return {"runs": started, "companies": len(comps), "estimated_credits": credits}


@router.get("/companies/{cid}")
def get_company(cid: str):
    db = get_db()
    c = db.table("companies").select("*").eq("id", cid).execute().data
    if not c:
        raise HTTPException(404)
    return {
        **c[0],
        "pages": db.table("pages").select("id,url,kind,fetched_at").eq("company_id", cid).execute().data,
        "evidence": db.table("evidence").select("*").eq("company_id", cid).execute().data,
        "people": db.table("people").select("*").eq("company_id", cid).execute().data,
        "judgments": db.table("judgments").select("*").eq("company_id", cid).order("created_at", desc=True).execute().data,
    }


@router.post("/companies/{cid}/rejudge")
async def rejudge(cid: str):
    db = get_db()
    c = db.table("companies").select("*").eq("id", cid).single().execute().data
    run = db.table("runs").select("campaign_id").eq("id", c["run_id"]).single().execute().data
    camp = db.table("campaigns").select("*").eq("id", run["campaign_id"]).single().execute().data
    status = await judge_mod.judge_company(c, camp, c["run_id"])
    return {"status": status}
