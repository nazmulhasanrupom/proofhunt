import json
import secrets

from pydantic import BaseModel

from ..db import get_db
from ..services import llm
from ..services.usage import log_event


class ReportOut(BaseModel):
    report_md: str


class DemoOut(BaseModel):
    demo_spec_md: str


def lead_context(lead: dict) -> dict:
    """Everything the asset/sequence prompts need, read from the database."""
    db = get_db()
    c = db.table("companies").select("*").eq("id", lead["company_id"]).single().execute().data
    j = db.table("judgments").select("*").eq("id", lead["judgment_id"]).single().execute().data
    p = db.table("people").select("*").eq("id", lead["person_id"]).single().execute().data
    ev_ids = j.get("evidence_ids") or []
    ev = db.table("evidence").select("id,kind,quote,url").in_("id", ev_ids).execute().data if ev_ids else []
    prof = db.table("profiles").select("parsed").eq("is_active", True).limit(1).execute().data
    parsed = prof[0]["parsed"] if prof else {}
    return {"company": c, "judgment": j, "person": p, "evidence": ev, "cv": parsed}


async def build_assets(lead: dict, campaign: dict, run_id: str | None):
    db = get_db()
    if db.table("assets").select("id").eq("lead_id", lead["id"]).execute().data:
        return  # resumable
    ctx = lead_context(lead)
    j = ctx["judgment"]
    base = {
        "company": ctx["company"]["name"], "domain": ctx["company"]["domain"],
        "quotes": [{"quote": e["quote"], "url": e["url"]} for e in ctx["evidence"] if e["kind"] != "tech"],
        "problem": j["problem"], "fix": j["fix"], "value_estimate": j["value_estimate"],
        "cv_proof_points": (ctx["cv"] or {}).get("proof_points", []),
    }
    rep = await llm.complete_json("report", "smart", llm.load_prompt("report"), json.dumps(base), ReportOut, run_id, 0.5)
    db.table("assets").insert({"lead_id": lead["id"], "kind": "report", "content_md": rep["report_md"],
                               "public_token": secrets.token_urlsafe(24)}).execute()
    if lead["score"] >= campaign["filters"]["qualify"]["demoFrom"]:
        d = await llm.complete_json("demo_spec", "smart", llm.load_prompt("demo_spec"), json.dumps(base), DemoOut, run_id, 0.5)
        db.table("assets").insert({"lead_id": lead["id"], "kind": "demo_spec", "content_md": d["demo_spec_md"]}).execute()
