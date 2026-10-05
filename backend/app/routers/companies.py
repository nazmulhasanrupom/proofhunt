from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from ..db import get_db
from ..deps import ProfileId
from ..pipeline import judge as judge_mod
from ..pipeline.filters import apply_filters, size_bucket
from ..pipeline.scope import chunks
from ..schemas import CampaignFilters
from ..services import cache
from ..services.usage import log_event

router = APIRouter()
PAGE = 50


@router.get("/companies")
def list_companies(pid: ProfileId, status: str | None = None, q: str | None = None, page: int = 0):
    qry = get_db().table("companies").select("id,domain,name,country,size_estimate,size_bucket,keyword_hits,status,fail_reason,run_id,first_seen").eq("profile_id", pid)
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
def company_ids(pid: ProfileId, status: str | None = None, q: str | None = None):
    """Ids of every company that matches the filter (for 'select all'). Capped at 2000."""
    qry = get_db().table("companies").select("id").eq("profile_id", pid)
    if status:
        qry = qry.eq("status", status)
    if q:
        qry = qry.or_(f"domain.ilike.%{q}%,name.ilike.%{q}%")
    return [r["id"] for r in qry.order("first_seen", desc=True).limit(2000).execute().data]


class QualifyIn(BaseModel):
    ids: list[str]
    campaign_id: str | None = None


CREDITS_PER_AUDIT = 4  # home page + up to 3 more pages (Crawl4AI pages cost nothing; Firecrawl pages cost 1 each)
KEEP = {"qualified", "audited", "extracted", "contacted"}  # already on their way: continue from there


def resume_point(c: dict, has_pages: bool, has_person: bool, filters: dict) -> tuple[str, str | None]:
    """Where a company starts again. Work that is already saved is reused: pages cost nothing, and a company
    that was only filtered out is checked against the campaign's filters again, with no AI call."""
    st = c["status"]
    extracted = bool(c.get("facts"))
    if st in KEEP:
        return st, c.get("fail_reason")
    if st == "filtered_out" and extracted:
        reason = apply_filters(c, filters)
        return ("extracted", None) if reason is None else ("filtered_out", reason)
    if st in ("rejected", "maybe", "judged") and has_person:
        return "contacted", None             # only the judge runs again
    return ("audited" if has_pages else "new"), None   # no_contact, failed and the rest: read the saved pages again


@router.post("/companies/qualify")
async def qualify(body: QualifyIn, request: Request, pid: ProfileId):
    """Start qualifying these companies now: audit -> extract -> contact -> judge -> report -> emails.
    Makes a manual run (one per campaign) so it shows in Activity, with its own stage limits."""
    db = get_db()
    ids = list(dict.fromkeys(body.ids))[:1000]
    if not ids:
        raise HTTPException(422, "Pick at least one company")
    comps = []
    for part in chunks(ids):
        comps += db.table("companies").select("id,domain,status,run_id,fail_reason,facts,country,size_estimate,keyword_hits").in_("id", part).eq("profile_id", pid).execute().data
    if not comps:
        raise HTTPException(404, "Companies not found")
    with_pages: set[str] = set()
    with_person: set[str] = set()
    for part in chunks([c["id"] for c in comps]):
        # a page older than 2 months does not count: the company is read again, so the facts stay fresh
        with_pages |= {p["company_id"] for p in db.table("pages").select("company_id").in_("company_id", part).gte("fetched_at", cache.cutoff()).execute().data}
        with_person |= {p["company_id"] for p in db.table("people").select("company_id").in_("company_id", part).eq("selected", True).execute().data}

    # which campaign decides the filters: the one given, else the one that found the company, else the newest. Only campaigns of this profile
    runs = {r["id"]: r["campaign_id"] for r in db.table("runs").select("id,campaign_id").eq("profile_id", pid).execute().data}
    camps = {c["id"]: c for c in db.table("campaigns").select("id,name,filters,created_at").eq("profile_id", pid).order("created_at", desc=True).execute().data}
    newest = next(iter(camps), None)
    if body.campaign_id and body.campaign_id not in camps:
        raise HTTPException(404, "Campaign not found")
    groups: dict[str, list[str]] = {}
    credits = 0
    still_filtered = []
    for c in comps:
        camp = body.campaign_id or (runs.get(c["run_id"]) if runs.get(c["run_id"]) in camps else None) or newest
        if not camp:
            raise HTTPException(409, "Create a campaign first. Its filters decide who qualifies.")
        filters = CampaignFilters.model_validate(camps[camp]["filters"]).model_dump()
        start, reason = resume_point(c, c["id"] in with_pages, c["id"] in with_person, filters)
        if start != c["status"] or reason != c.get("fail_reason"):
            db.table("companies").update({"status": start, "fail_reason": reason}).eq("id", c["id"]).execute()
        if start == "filtered_out":
            still_filtered.append({"domain": c["domain"], "reason": reason, "campaign": camps[camp]["name"]})
            continue
        credits += CREDITS_PER_AUDIT if start == "new" else 0
        groups.setdefault(camp, []).append(c["id"])

    started = []
    for camp, gids in groups.items():
        run = db.table("runs").insert({"campaign_id": camp, "profile_id": pid, "status": "queued",
                                       "counters": {"company_ids": gids, "manual": True}}).execute().data[0]
        await request.app.state.arq.enqueue_job("run_campaign_task", run["id"])
        log_event(run["id"], "info", "qualify", f"manual qualify queued for {len(gids)} compan{'y' if len(gids) == 1 else 'ies'} "
                  f"(filters of campaign '{camps[camp]['name']}'): " + ", ".join(c["domain"] for c in comps if c["id"] in gids)[:300])
        started.append({"run_id": run["id"], "count": len(gids), "campaign": camps[camp]["name"]})
    for f_ in still_filtered:
        log_event(None, "info", "qualify", f"{f_['domain']}: still filtered out by campaign '{f_['campaign']}': {f_['reason']}", profile_id=pid)
    return {"runs": started, "companies": len(comps), "estimated_credits": credits, "still_filtered": still_filtered}


# ---- change a company by hand -------------------------------------------------
HAND_STATUS = {"new", "audited", "extracted", "contacted", "filtered_out", "no_contact", "rejected", "maybe", "failed", "qualified"}
WITH_REASON = {"filtered_out", "no_contact", "rejected", "failed"}


class StatusIn(BaseModel):
    status: str
    reason: str | None = None


class BulkStatusIn(StatusIn):
    ids: list[str]


class CompanyEdit(BaseModel):
    name: str | None = None
    country: str | None = None
    size_estimate: int | None = None


def _set_status(ids: list[str], status: str, reason: str | None, pid: str) -> int:
    if status not in HAND_STATUS:
        raise HTTPException(422, f"Status must be one of: {', '.join(sorted(HAND_STATUS))}")
    db = get_db()
    if status == "qualified":  # a qualified company needs a lead. Only a company that already has one can go back
        have = set()
        for part in chunks(ids):
            have |= {l["company_id"] for l in db.table("leads").select("company_id").in_("company_id", part).execute().data}
        if set(ids) - have:
            raise HTTPException(409, "Qualified needs a lead (a judgment and a contact). Use Qualify to run the steps, "
                                     "or set the status to 'contacted' and then press Qualify.")
    fail = (reason or "set by hand") if status in WITH_REASON else None
    for part in chunks(ids):
        db.table("companies").update({"status": status, "fail_reason": fail}).in_("id", part).execute()
    log_event(None, "info", "company", f"{len(ids)} compan{'y' if len(ids) == 1 else 'ies'} set to '{status}' by hand", profile_id=pid)
    return len(ids)


@router.post("/companies/status")
def bulk_status(body: BulkStatusIn, pid: ProfileId):
    if not body.ids:
        raise HTTPException(422, "Pick at least one company")
    return {"updated": _set_status(list(dict.fromkeys(body.ids))[:2000], body.status, body.reason, pid)}


@router.patch("/companies/{cid}/status")
def set_status(cid: str, body: StatusIn, pid: ProfileId):
    return {"updated": _set_status([cid], body.status, body.reason, pid)}


@router.patch("/companies/{cid}")
def edit_company(cid: str, body: CompanyEdit, pid: ProfileId):
    """Fix a wrong number or country by hand (for example a size the AI guessed wrong)."""
    data = body.model_dump(exclude_none=True)
    if "size_estimate" in data:
        if data["size_estimate"] < 0:
            raise HTTPException(422, "Size cannot be negative")
        data["size_bucket"] = size_bucket(data["size_estimate"] or None)
        data["size_estimate"] = data["size_estimate"] or None
    if data:
        get_db().table("companies").update(data).eq("id", cid).execute()
        log_event(None, "info", "company", f"{cid[:8]}: edited by hand ({', '.join(data)})", profile_id=pid)
    return {"ok": True}


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
    status = await judge_mod.judge_company(c, camp, None)  # not counted in the old run: it may be paused or cancelled by now
    return {"status": status}
