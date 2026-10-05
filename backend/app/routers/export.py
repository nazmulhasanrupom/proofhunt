"""Download companies as a CSV file (opens in Excel, Google Sheets, Numbers)."""
import csv
import io
import re
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

from ..db import get_db
from ..deps import ProfileId
from ..pipeline.scope import chunks

router = APIRouter()
MAX_ROWS = 2000

COLUMNS = ["domain", "name", "status", "fail_reason", "country", "size_estimate", "size_bucket", "score",
           "contact_name", "contact_title", "contact_email", "contact_email_kind", "email_found_on",
           "sells", "serves", "all_emails_on_site", "tech", "keyword_hits", "has_careers",
           "problem", "fix", "value_estimate", "confidence", "evidence", "lead_stage", "first_seen", "last_audited_at"]


class ExportIn(BaseModel):
    ids: list[str]


def safe(v) -> str:
    """One cell. A text that starts with = + - @ would run as a formula in Excel, so it gets a ' in front."""
    if v is None:
        return ""
    if isinstance(v, (list, tuple)):
        v = "; ".join(str(x) for x in v)
    elif isinstance(v, dict):
        v = "; ".join(str(k) for k in v)
    elif isinstance(v, bool):
        v = "yes" if v else "no"
    v = re.sub(r"\s*\n\s*", " ", str(v)).strip()
    return "'" + v if v[:1] in ("=", "+", "-", "@") else v


def rows_for(pid: str, ids: list[str]) -> list[dict]:
    db = get_db()
    comps = []
    for part in chunks(ids):
        comps += db.table("companies").select("*").in_("id", part).eq("profile_id", pid).execute().data
    cids = [c["id"] for c in comps]
    people: dict[str, dict] = {}
    judgments: dict[str, dict] = {}
    evidence: dict[str, list[str]] = {}
    leads: dict[str, dict] = {}
    for part in chunks(cids):
        for p in db.table("people").select("*").in_("company_id", part).eq("selected", True).execute().data:
            people[p["company_id"]] = p
        for j in db.table("judgments").select("*").in_("company_id", part).order("created_at").execute().data:
            judgments[j["company_id"]] = j  # oldest first, so the newest wins
        for e in db.table("evidence").select("company_id,quote,verified").in_("company_id", part).execute().data:
            if e["verified"]:
                evidence.setdefault(e["company_id"], []).append(f"“{e['quote']}”")
        for l in db.table("leads").select("company_id,stage").in_("company_id", part).execute().data:
            leads[l["company_id"]] = l
    order = {i: n for n, i in enumerate(ids)}  # the order you picked them in
    out = []
    for c in sorted(comps, key=lambda c: order.get(c["id"], 0)):
        p, j, facts = people.get(c["id"]) or {}, judgments.get(c["id"]) or {}, c.get("facts") or {}
        out.append({
            "domain": c["domain"], "name": c["name"], "status": c["status"], "fail_reason": c["fail_reason"],
            "country": c["country"], "size_estimate": c["size_estimate"], "size_bucket": c["size_bucket"], "score": j.get("fit_score"),
            "contact_name": p.get("name"), "contact_title": p.get("title"), "contact_email": p.get("email"),
            "contact_email_kind": p.get("email_kind"), "email_found_on": p.get("email_source"),
            "sells": facts.get("sells"), "serves": facts.get("serves"),
            "all_emails_on_site": [e.get("email") for e in facts.get("emails") or []],
            "tech": c.get("tech"), "keyword_hits": c.get("keyword_hits"), "has_careers": facts.get("has_careers"),
            "problem": j.get("problem"), "fix": j.get("fix"), "value_estimate": j.get("value_estimate"), "confidence": j.get("confidence"),
            "evidence": " | ".join(evidence.get(c["id"], [])), "lead_stage": (leads.get(c["id"]) or {}).get("stage"),
            "first_seen": c["first_seen"], "last_audited_at": c["last_audited_at"],
        })
    return out


def make_csv(rows: list[dict]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(COLUMNS)
    for r in rows:
        w.writerow([safe(r.get(k)) for k in COLUMNS])
    return buf.getvalue()


@router.post("/companies/export")
def export_companies(body: ExportIn, pid: ProfileId):
    ids = list(dict.fromkeys(body.ids))[:MAX_ROWS]
    if not ids:
        raise HTTPException(422, "Pick at least one company")
    rows = rows_for(pid, ids)
    if not rows:
        raise HTTPException(404, "Companies not found")
    name = f"companies-{datetime.now(timezone.utc):%Y-%m-%d}.csv"
    # utf-8 with a BOM: Excel then shows accents and other scripts right
    return Response("﻿" + make_csv(rows), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})
