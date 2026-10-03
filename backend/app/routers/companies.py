from fastapi import APIRouter, HTTPException

from ..db import get_db
from ..pipeline import judge as judge_mod

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
