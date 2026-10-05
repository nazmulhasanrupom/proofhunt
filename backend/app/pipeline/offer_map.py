from pydantic import BaseModel, Field

from ..db import get_db
from ..services import llm
from .kinds import IMA, kind_of


class SignalIn(BaseModel):
    name: str
    description: str = ""
    detector_type: str
    config: dict = {}
    weight: int = 1


class RowIn(BaseModel):
    service: str
    problems: list[str] = []
    proof: list[str] = []
    ideal_customer: dict = {}
    signals: list[SignalIn] = []


class OfferMapOut(BaseModel):
    rows: list[RowIn] = Field(min_length=1)


DETECTOR_KEYS = {"phrase": "phrases", "tech_absent": "tech", "tech_present": "tech", "hiring_role": "roles", "llm": "question"}


def signal_error(s: dict) -> str | None:
    """Every signal must have a detector. Returns an error text or None."""
    t = s.get("detector_type")
    if t not in DETECTOR_KEYS:
        return f"Signal '{s.get('name')}': unknown detector type"
    if not (s.get("config") or {}).get(DETECTOR_KEYS[t]):
        return f"Signal '{s.get('name')}': detector config is empty"
    return None


def brief_for_ai(parsed: dict) -> dict:
    """What the brand map prompt reads from an IMA profile: the agency, its niches and its roster."""
    return {"agency": parsed.get("agency") or {}, "niches": parsed.get("niches") or [], "roster": parsed.get("roster") or []}


async def generate(profile_id: str) -> list[str]:
    """The offer map of a freelancer profile, or the brand map of an IMA profile. Both are saved in the same tables."""
    db = get_db()
    prof = db.table("profiles").select("parsed").eq("id", profile_id).single().execute().data
    import json
    if kind_of(profile_id) == IMA:
        out = await llm.complete_json("brand_map", "smart", llm.load_prompt("brand_map"),
                                      json.dumps(brief_for_ai(prof["parsed"] or {})), OfferMapOut)
    else:
        out = await llm.complete_json("offer_map", "smart", llm.load_prompt("offer_map"),
                                      json.dumps(prof["parsed"]), OfferMapOut)
    # old rows of this profile are replaced
    db.table("offer_rows").delete().eq("profile_id", profile_id).execute()
    ids = []
    for row in out["rows"]:
        r = db.table("offer_rows").insert({
            "profile_id": profile_id, "service": row["service"], "problems": row["problems"],
            "proof": row["proof"], "ideal_customer": row["ideal_customer"],
        }).execute().data[0]
        ids.append(r["id"])
        sigs = [s for s in row["signals"] if not signal_error(s)]
        if sigs:
            db.table("signals").insert([{**s, "offer_row_id": r["id"]} for s in sigs]).execute()
    return ids


def load_map(profile_id: str) -> list[dict]:
    db = get_db()
    rows = db.table("offer_rows").select("*").eq("profile_id", profile_id).order("created_at").execute().data
    for r in rows:
        r["signals"] = db.table("signals").select("*").eq("offer_row_id", r["id"]).execute().data
    return rows
