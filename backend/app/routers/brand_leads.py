"""The lead sheet of an IMA profile: one row per qualified brand. List it, fix a row by hand, download it as a CSV."""
import csv
import io
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

from ..db import get_db
from ..deps import ProfileId, as_uuid
from ..pipeline.brand_leads import GOOD, MANUAL
from .export import safe

router = APIRouter()
PAGE = 50
MAX_ROWS = 5000

# the sheet: (header, column). The first nine are the columns you asked for, the rest come with them
SHEET = [("website_url", "website_url"), ("Brand", "brand"), ("brand_url", "brand_url"), ("category", "category"), ("sponsorships", "sponsorships"),
         ("creators", "creators"), ("Emails", "emails"), ("Employees", "employees"), ("type", "type"),
         ("country", "country"), ("contact_name", "contact_name"), ("contact_title", "contact_title"), ("email_found_on", "email_source"),
         ("proof_count", "proof_count")]


def _filtered(pid: str, type_: str | None, q: str | None):
    qry = get_db().table("brand_leads").select("*").eq("profile_id", pid)
    if type_ in (GOOD, MANUAL):
        qry = qry.eq("type", type_)
    if q:
        q = q.replace(",", " ").replace("(", " ").replace(")", " ")  # these break the filter text
        qry = qry.or_(f"brand.ilike.%{q}%,brand_url.ilike.%{q}%,category.ilike.%{q}%,emails.ilike.%{q}%")
    return qry.order("proof_count", desc=True).order("created_at", desc=True)


def _count(pid: str, type_: str) -> int:
    return get_db().table("brand_leads").select("id", count="exact").eq("profile_id", pid).eq("type", type_).limit(1).execute().count or 0


@router.get("/brand-leads")
def list_brand_leads(pid: ProfileId, type: str | None = None, q: str | None = None, page: int = 0):
    rows = _filtered(pid, type, q).range(page * PAGE, page * PAGE + PAGE - 1).execute().data
    return {"rows": rows, "counts": {"good": _count(pid, GOOD), "manual": _count(pid, MANUAL)}}


class BrandLeadPatch(BaseModel):
    emails: str | None = None
    type: str | None = None


@router.patch("/brand-leads/{lid}")
def patch_brand_lead(lid: str, body: BrandLeadPatch, pid: ProfileId):
    """Finish a 'do manually' row by hand: type the email you found. A row with an email becomes 'good to go', a row with none 'do manually'."""
    data: dict = {}
    if body.emails is not None:
        data["emails"] = "; ".join(x.strip() for x in body.emails.replace(",", ";").split(";") if x.strip())
        data["type"] = GOOD if data["emails"] else MANUAL
    if body.type is not None:
        if body.type not in (GOOD, MANUAL):
            raise HTTPException(422, "type must be 'good to go' or 'do manually'")
        data["type"] = body.type
    if not data:
        raise HTTPException(422, "Nothing to change")
    uid = as_uuid(lid)
    if not uid or not get_db().table("brand_leads").update({**data, "updated_at": datetime.now(timezone.utc).isoformat()}).eq("id", uid).eq("profile_id", pid).execute().data:
        raise HTTPException(404, "Brand not found")
    return {"ok": True}


class ExportIn(BaseModel):
    type: str | None = None   # only 'good to go' or only 'do manually'. Empty = all
    q: str | None = None


def make_csv(rows: list[dict]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow([h for h, _ in SHEET])
    for r in rows:
        w.writerow([safe(r.get(col)) for _, col in SHEET])
    return buf.getvalue()


@router.post("/brand-leads/export")
def export_brand_leads(body: ExportIn, pid: ProfileId):
    rows = _filtered(pid, body.type, body.q).limit(MAX_ROWS).execute().data
    if not rows:
        raise HTTPException(404, "No brands to download yet")
    name = f"brands-{datetime.now(timezone.utc):%Y-%m-%d}.csv"
    return Response("﻿" + make_csv(rows), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})
