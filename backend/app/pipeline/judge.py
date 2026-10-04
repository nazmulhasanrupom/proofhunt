import json

from pydantic import BaseModel

from ..db import get_db
from ..services import llm
from ..services.usage import BudgetExceeded, log_event
from .scope import todo as scope_todo
from .offer_map import load_map

# The send window is in the lead's local time. A country that is not here gets the default (New York).
TZ = {"United States": "America/New_York", "Canada": "America/Toronto",
      "United Kingdom": "Europe/London", "Australia": "Australia/Sydney",
      "Ireland": "Europe/Dublin", "New Zealand": "Pacific/Auckland", "Germany": "Europe/Berlin", "France": "Europe/Paris",
      "Netherlands": "Europe/Amsterdam", "Spain": "Europe/Madrid", "Italy": "Europe/Rome", "Portugal": "Europe/Lisbon",
      "Poland": "Europe/Warsaw", "Sweden": "Europe/Stockholm", "Denmark": "Europe/Copenhagen", "Switzerland": "Europe/Zurich",
      "Belgium": "Europe/Brussels", "India": "Asia/Kolkata", "Singapore": "Asia/Singapore", "United Arab Emirates": "Asia/Dubai",
      "Israel": "Asia/Jerusalem", "South Africa": "Africa/Johannesburg", "Brazil": "America/Sao_Paulo", "Mexico": "America/Mexico_City",
      "Philippines": "Asia/Manila", "Pakistan": "Asia/Karachi", "Bangladesh": "Asia/Dhaka"}


class JudgeOut(BaseModel):
    fit_score: int = 0
    offer_row_id: str = ""
    problem: str = ""
    fix: str = ""
    value_estimate: str = ""
    confidence: str = "low"
    evidence_ids: list[str] = []
    disqualifiers: list[str] = []


def lead_timezone(country: str | None, us_state: str | None) -> str | None:
    if country == "United States" and us_state:
        from .extract import CITY_TZ_US
        return CITY_TZ_US.get(us_state, TZ["United States"])
    return TZ.get(country or "")


def enforce_rules(out: dict, sent_ids: set[str], active_row_ids: set[str]) -> dict:
    """Hard rules, checked in code after the LLM call."""
    out["evidence_ids"] = [e for e in out["evidence_ids"] if e in sent_ids]
    if not out["evidence_ids"]:
        out["fit_score"] = min(out["fit_score"], 40)
    if out["offer_row_id"] not in active_row_ids:
        out["offer_row_id"] = None
    out["fit_score"] = max(0, min(100, out["fit_score"]))
    return out


async def judge_company(c: dict, campaign: dict, run_id: str | None) -> str:
    db = get_db()
    rows = [r for r in load_map(campaign["profile_id"]) if r["active"]]
    ev = db.table("evidence").select("id,kind,quote,url,signal_id").eq("company_id", c["id"]).eq("verified", True).execute().data
    person = db.table("people").select("*").eq("company_id", c["id"]).eq("selected", True).execute().data[0]
    payload = {
        "offer_map": [{"id": r["id"], "service": r["service"], "problems": r["problems"],
                       "ideal_customer": r["ideal_customer"],
                       "signals": [{"id": s["id"], "name": s["name"], "weight": s["weight"]} for s in r["signals"] if s["active"]]}
                      for r in rows],
        "company": {"domain": c["domain"], "name": c["name"], "country": c["country"],
                    "size": c["size_estimate"], "facts": c["facts"], "tech": list((c["tech"] or {}).keys())},
        "evidence": ev,
        "contact": {"name": person["name"], "title": person["title"], "seniority": person["seniority"],
                    "email_kind": person["email_kind"]},
    }
    out = await llm.complete_json("judge", "smart", llm.load_prompt("judge"), json.dumps(payload), JudgeOut, run_id)
    out = enforce_rules(out, {e["id"] for e in ev}, {r["id"] for r in rows})
    q = campaign["filters"]["qualify"]
    j = db.table("judgments").insert({
        "company_id": c["id"], "run_id": run_id, "offer_row_id": out["offer_row_id"],
        "fit_score": out["fit_score"], "problem": out["problem"], "fix": out["fix"],
        "value_estimate": out["value_estimate"], "confidence": out["confidence"],
        "evidence_ids": out["evidence_ids"], "disqualifiers": out["disqualifiers"],
        "model": "smart", "raw": out}).execute().data[0]
    score = out["fit_score"]
    if score >= q["minFitScore"] and out["offer_row_id"]:
        status = "qualified"
        tz = lead_timezone(c["country"], (c["facts"] or {}).get("us_state"))
        existing = db.table("leads").select("id").eq("company_id", c["id"]).execute().data
        data = {"person_id": person["id"], "campaign_id": campaign["id"], "judgment_id": j["id"],
                "profile_id": campaign["profile_id"], "score": score, "timezone": tz}
        if existing:
            db.table("leads").update(data).eq("id", existing[0]["id"]).execute()
        else:
            db.table("leads").insert({**data, "company_id": c["id"], "stage": "new"}).execute()
    elif score >= q["maybeFrom"]:
        status = "maybe"
    else:
        status = "rejected"
    db.table("companies").update({"status": status}).eq("id", c["id"]).execute()
    return status


async def run(run_id: str, campaign: dict, should_stop, ids: list[str] | None = None, stop_when=None):
    db = get_db()
    todo = scope_todo(run_id, ["contacted"], ids)
    for c in todo:
        if should_stop() or (stop_when and stop_when()):  # stop_when: the leads wanted exist. The rest stays 'contacted'
            return
        try:
            status = await judge_company(c, campaign, run_id)
            log_event(run_id, "info", "judge", f"{c['domain']}: {status}")
        except Exception as e:
            if isinstance(e, BudgetExceeded):
                raise
            log_event(run_id, "error", "judge", f"{c['domain']}: {e}")
