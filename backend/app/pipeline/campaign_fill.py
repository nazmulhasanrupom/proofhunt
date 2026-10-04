"""AI recommended fill for a campaign. The AI proposes every field. Code cleans the answer and keeps it inside safe limits,
so a bad answer can never make a broken or too expensive campaign."""
import json
import re

from pydantic import BaseModel

from ..db import get_db
from ..schemas import CampaignFilters
from ..services import llm
from .offer_map import load_map


class _Company(BaseModel):
    anyCountry: bool | None = None
    countries: list[str] | None = None
    employeeRanges: list[list[float]] | None = None
    allowUnknownSize: bool | None = None
    webKeywords: list[str] | None = None
    minKeywordHits: float | None = None
    excludeDomains: list[str] | None = None
    cooldownDays: float | None = None


class _Person(BaseModel):
    titlePriority: list[str] | None = None
    excludeTitle: list[str] | None = None
    seniority: list[str] | None = None
    excludeSeniority: list[str] | None = None


class _Qualify(BaseModel):
    minFitScore: float | None = None
    maybeFrom: float | None = None
    demoFrom: float | None = None


class _Email(BaseModel):
    allowGeneric: bool | None = None
    allowNoPerson: bool | None = None
    requireMx: bool | None = None


class FillOut(BaseModel):
    """Every field is optional: a field the AI leaves out keeps the value it has now."""
    name: str = ""
    why: str = ""
    leadsWanted: float | None = None
    maxCompaniesToScan: float | None = None
    maxCreditsPerRun: float | None = None
    maxCreditsPerStage: float | None = None
    maxLlmCallsPerStage: float | None = None
    company: _Company = _Company()
    person: _Person = _Person()
    qualify: _Qualify = _Qualify()
    email: _Email = _Email()


SENIORITY = ("owner", "c_suite", "head")
EXCLUDE_SENIORITY = ("entry", "other")
COUNTRY_ALIASES = {
    "us": "United States", "usa": "United States", "u.s.": "United States", "u.s.a.": "United States", "america": "United States",
    "uk": "United Kingdom", "u.k.": "United Kingdom", "gb": "United Kingdom", "great britain": "United Kingdom", "britain": "United Kingdom",
    "england": "United Kingdom", "uae": "United Arab Emirates",
    "au": "Australia", "ca": "Canada", "nz": "New Zealand", "ie": "Ireland", "de": "Germany", "fr": "France", "in": "India", "sg": "Singapore",
}


# ---- small cleaners (pure) ------------------------------------------------

def to_int(v) -> int | None:
    if isinstance(v, bool) or v is None:
        return None
    try:
        return int(round(float(v)))
    except (TypeError, ValueError, OverflowError):  # "abc", NaN, Infinity
        return None


def clamp(v: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, v))


def clean_list(items, limit: int, fix=lambda s: s) -> list[str]:
    """Strip, drop empties, drop repeats (any case), keep the order, cap the length."""
    out, seen = [], set()
    for raw in items or []:
        s = fix(str(raw).strip())
        if s and s.lower() not in seen:
            seen.add(s.lower())
            out.append(s)
    return out[:limit]


def fix_keyword(s: str) -> str:
    return re.sub(r'["\']', "", s).lower().strip()[:60]


def fix_country(s: str) -> str:
    return COUNTRY_ALIASES.get(s.lower().strip(), s.strip().title() if s.islower() else s.strip())[:60]


def clean_ranges(raw) -> list[list[int]]:
    out = []
    for pair in raw or []:
        if not isinstance(pair, (list, tuple)) or len(pair) != 2:
            continue
        lo, hi = to_int(pair[0]), to_int(pair[1])
        if lo is None or hi is None or not 1 <= lo <= hi <= 100000:
            continue
        if [lo, hi] not in out:
            out.append([lo, hi])
    return out[:6]


def run_cost(scan: int) -> int:
    """Firecrawl credits of a run: the same estimate the campaign form shows."""
    return scan * 4 + max(1, scan // 5) * 4


def max_scan_for(credits_left: int) -> int:
    scan = max(1, int(credits_left / 4.8))
    while scan > 1 and run_cost(scan) > credits_left:
        scan -= 1
    return scan


# ---- merge the AI answer into the form (pure) -----------------------------

def merge(current: dict, out: dict, credits_left: int | None) -> tuple[dict, list[str]]:
    """Returns (filters, notes). `current` is the form now, `out` is what the AI returned (FillOut as a dict)."""
    f = CampaignFilters.model_validate(current).model_dump()
    notes: list[str] = []
    c, p, q, e = f["company"], f["person"], f["qualify"], f["email"]
    oc, op, oq, oe = (out.get(k) or {} for k in ("company", "person", "qualify", "email"))

    # who and where
    if oc.get("anyCountry") is not None:
        c["anyCountry"] = bool(oc["anyCountry"])
    if countries := clean_list(oc.get("countries"), 15, fix_country):
        c["countries"] = countries
    if keywords := clean_list(oc.get("webKeywords"), 12, fix_keyword):
        c["webKeywords"] = keywords
    if ranges := clean_ranges(oc.get("employeeRanges")):
        c["employeeRanges"] = ranges
    if oc.get("allowUnknownSize") is not None:
        c["allowUnknownSize"] = bool(oc["allowUnknownSize"])
    if (hits := to_int(oc.get("minKeywordHits"))) is not None:
        c["minKeywordHits"] = clamp(hits, 0, 5)
    c["minKeywordHits"] = min(c["minKeywordHits"], len(c["webKeywords"]))  # more hits than keywords could never be met
    c["excludeDomains"] = clean_list(c["excludeDomains"] + (oc.get("excludeDomains") or []), 50, lambda s: s.lower())  # never drop what you added
    if (days := to_int(oc.get("cooldownDays"))) is not None:
        c["cooldownDays"] = clamp(days, 0, 720)

    # which person
    if titles := clean_list(op.get("titlePriority"), 12, str.lower):
        p["titlePriority"] = titles
    if skip := clean_list(op.get("excludeTitle"), 15, str.lower):
        p["excludeTitle"] = skip
    if ranks := [r for r in clean_list(op.get("seniority"), 5, str.lower) if r in SENIORITY]:
        p["seniority"] = ranks
    if skip_ranks := [r for r in clean_list(op.get("excludeSeniority"), 5, str.lower) if r in EXCLUDE_SENIORITY]:
        p["excludeSeniority"] = skip_ranks

    # scores: maybeFrom <= minFitScore <= demoFrom <= 100
    lo = to_int(oq.get("minFitScore"))
    q["minFitScore"] = clamp(lo if lo is not None else q["minFitScore"], 40, 95)
    mb = to_int(oq.get("maybeFrom"))
    q["maybeFrom"] = clamp(mb if mb is not None else q["maybeFrom"], 20, q["minFitScore"])
    dm = to_int(oq.get("demoFrom"))
    q["demoFrom"] = clamp(dm if dm is not None else q["demoFrom"], q["minFitScore"], 100)

    for key in ("allowGeneric", "allowNoPerson", "requireMx"):
        if oe.get(key) is not None:
            e[key] = bool(oe[key])

    # budget: the AI proposes, the credits you have decide
    scan = clamp(to_int(out.get("maxCompaniesToScan")) or f["maxCompaniesToScan"], 1, 5000)
    if credits_left is not None and run_cost(scan) > credits_left:
        scan = max_scan_for(max(credits_left, 0))
        notes.append(f"Companies to scan limited to {scan}: only {max(credits_left, 0)} Firecrawl credits are left.")
    f["maxCompaniesToScan"] = scan
    f["leadsWanted"] = clamp(to_int(out.get("leadsWanted")) or f["leadsWanted"], 1, scan)
    cost = run_cost(scan)
    cap_top = 1_000_000 if credits_left is None else max(credits_left, cost)
    f["maxCreditsPerRun"] = clamp(to_int(out.get("maxCreditsPerRun")) or f["maxCreditsPerRun"], cost, cap_top)
    f["maxCreditsPerStage"] = clamp(to_int(out.get("maxCreditsPerStage")) or f["maxCreditsPerStage"], scan * 4, max(f["maxCreditsPerRun"], scan * 4))
    f["maxLlmCallsPerStage"] = clamp(to_int(out.get("maxLlmCallsPerStage")) or f["maxLlmCallsPerStage"], scan, 5000)

    if not c["webKeywords"]:
        notes.append("The AI gave no usable web keywords. Add some, or press the button again.")
    return f, notes


# ---- what the AI gets to read ---------------------------------------------

def build_context(pid: str) -> dict:
    db = get_db()
    prof = db.table("profiles").select("name,parsed").eq("id", pid).execute().data
    cv = (prof[0]["parsed"] if prof else None) or {}
    rows = [r for r in load_map(pid) if r["active"]]
    others = db.table("campaigns").select("name,filters").eq("profile_id", pid).order("created_at", desc=True).limit(5).execute().data
    return {
        "cv": {
            "name": cv.get("name"), "headline": cv.get("headline"), "years_experience": cv.get("years_experience"),
            "skills": (cv.get("skills") or [])[:20], "tools": (cv.get("tools") or [])[:20],
            "roles": [r.get("title") for r in (cv.get("roles") or [])[:4]],
            "proof_points": (cv.get("proof_points") or [])[:6],
        },
        "offer_map": [{
            "service": r["service"], "problems": r["problems"], "ideal_customer": r["ideal_customer"],
            "signals": [{"name": s["name"], "type": s["detector_type"], "config": s["config"]} for s in r["signals"] if s["active"]],
        } for r in rows],
        "other_campaigns": [{"name": c["name"], "web_keywords": (c["filters"].get("company") or {}).get("webKeywords", [])} for c in others],
    }


async def suggest(pid: str, name: str, hint: str, current: dict, credits_left: int | None) -> dict:
    ctx = build_context(pid)
    payload = {**ctx, "campaign_name": name.strip(), "note_from_freelancer": hint.strip(), "credits_left": credits_left}
    out = await llm.complete_json("campaign_fill", "smart", llm.load_prompt("campaign_fill"), json.dumps(payload), FillOut)
    filters, notes = merge(current, out, credits_left)
    return {
        "name": (out.get("name") or "").strip()[:80], "why": (out.get("why") or "").strip()[:800],
        "filters": filters, "notes": notes, "used_offer_map": bool(ctx["offer_map"]),
    }
