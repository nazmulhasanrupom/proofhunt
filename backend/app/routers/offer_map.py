from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..db import get_db
from ..deps import ProfileId, require_profile
from ..pipeline import offer_map as om

router = APIRouter()


class SignalPut(BaseModel):
    id: str | None = None
    name: str
    description: str = ""
    detector_type: str
    config: dict = {}
    weight: int = 1
    active: bool = True


class RowPut(BaseModel):
    id: str | None = None
    service: str
    problems: list[str] = []
    proof: list[str] = []
    ideal_customer: dict = {}
    active: bool = True
    signals: list[SignalPut] = []


class MapPut(BaseModel):
    rows: list[RowPut]


@router.get("/offer-map")
def get_map(pid: ProfileId):
    return {"profile_id": pid, "rows": om.load_map(pid)}


@router.put("/offer-map")
def put_map(body: MapPut, pid: ProfileId):
    require_profile(pid)
    for r in body.rows:
        for s in r.signals:
            err = om.signal_error(s.model_dump())
            if err:
                raise HTTPException(422, err)
    db = get_db()
    keep_rows = set()
    for r in body.rows:
        data = r.model_dump(exclude={"id", "signals"})
        if r.id:
            if not db.table("offer_rows").update(data).eq("id", r.id).eq("profile_id", pid).execute().data:
                raise HTTPException(404, "Offer row not found in this profile")
            rid = r.id
        else:
            rid = db.table("offer_rows").insert({**data, "profile_id": pid}).execute().data[0]["id"]
        keep_rows.add(rid)
        keep_sig = set()
        for s in r.signals:
            sd = s.model_dump(exclude={"id"})
            if s.id:
                db.table("signals").update(sd).eq("id", s.id).execute()
                keep_sig.add(s.id)
            else:
                keep_sig.add(db.table("signals").insert({**sd, "offer_row_id": rid}).execute().data[0]["id"])
        for old in db.table("signals").select("id").eq("offer_row_id", rid).execute().data:
            if old["id"] not in keep_sig:  # removed in UI: keep the row, switch it off (evidence may point to it)
                db.table("signals").update({"active": False}).eq("id", old["id"]).execute()
    for old in db.table("offer_rows").select("id").eq("profile_id", pid).execute().data:
        if old["id"] not in keep_rows:
            db.table("offer_rows").update({"active": False}).eq("id", old["id"]).execute()
    return om.load_map(pid)
