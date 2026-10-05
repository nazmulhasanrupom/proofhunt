"""The agency brief of an IMA profile. The AI reads it, then code checks every number and name against the brief text.
No number, sponsor or link the brief does not contain can get through: a field that is not in the brief stays empty."""
import re

from pydantic import BaseModel


class _Agency(BaseModel):
    name: str = ""
    sender_name: str = ""
    website: str = ""
    commission_model: str = ""


class _Creator(BaseModel):
    name: str = ""
    channel_url: str = ""
    niche: str = ""
    avg_views: str = ""
    subscribers: str = ""
    audience_countries: list[str] = []
    content_style: str = ""
    past_sponsors: list[str] = []
    open_to_deals: bool | None = None


class ParsedBrief(BaseModel):
    """What the AI returns for a brief."""
    agency: _Agency = _Agency()
    niches: list[str] = []
    roster: list[_Creator] = []


def _squash(s: str) -> str:
    return re.sub(r"[\s,]", "", (s or "").lower())


def _in_text(value: str, text_sq: str) -> bool:
    return bool(value) and _squash(value) in text_sq


def numbers_in_text(value: str, text_sq: str) -> bool:
    """Every number in `value` ('50K', '1.2M', '120,000') must be written in the brief. A value with no number is fine."""
    tokens = [t.rstrip(".") for t in re.findall(r"\d[\d.]*[kmb]?", _squash(value))]
    return all(re.search(rf"(?<![\d.]){re.escape(t)}(?!\d)", text_sq) for t in tokens)  # "10K" must not match inside "110K"


def _short(s: str, n: int = 200) -> str:
    return " ".join((s or "").split())[:n]


def _clean_list(items, text_low: str | None = None, limit: int = 12) -> list[str]:
    out: list[str] = []
    for raw in items or []:
        s = _short(str(raw), 80)
        if not s or s.lower() in (x.lower() for x in out):
            continue
        if text_low is not None and s.lower() not in text_low:
            continue  # a name that is not in the brief was made up
        out.append(s)
    return out[:limit]


def normalize(ai: dict, text: str) -> dict:
    """Returns the `parsed` value to save. It keeps the keys of a CV profile (name, headline, skills, ...), so every
    part of the app that reads a profile keeps working, and adds `kind`, `agency`, `niches` and `roster`."""
    text_sq, text_low = _squash(text), " ".join(text.lower().split())
    ag = ai.get("agency") or {}
    agency = {k: _short(ag.get(k, ""), 300) for k in ("name", "sender_name", "website", "commission_model")}
    if agency["website"] and not _in_text(agency["website"], text_sq):
        agency["website"] = ""
    niches = _clean_list(ai.get("niches"), limit=3)

    roster = []
    for c in ai.get("roster") or []:
        link = _short(c.get("channel_url", ""), 300)
        c_name = _short(c.get("name", ""), 80)
        if not (c_name or link):
            continue
        roster.append({
            "name": c_name,
            "channel_url": link if _in_text(link, text_sq) else "",
            "niche": _short(c.get("niche", ""), 80),
            "avg_views": _short(c.get("avg_views", ""), 40) if numbers_in_text(c.get("avg_views", ""), text_sq) else "",
            "subscribers": _short(c.get("subscribers", ""), 40) if numbers_in_text(c.get("subscribers", ""), text_sq) else "",
            "audience_countries": _clean_list(c.get("audience_countries"), text_low, 8),
            "content_style": _short(c.get("content_style", ""), 200),
            "past_sponsors": _clean_list(c.get("past_sponsors"), text_low, 12),
            "open_to_deals": c.get("open_to_deals") if isinstance(c.get("open_to_deals"), bool) else None,
        })
    roster = roster[:30]
    if not niches:  # the brief gave no niche list: the roster niches are the niches
        niches = _clean_list([c["niche"] for c in roster], limit=3)

    who = agency["name"] or "Agency"
    return {
        "kind": "ima",
        # the same keys a CV has, so lists, sender name and the campaign AI keep working
        "name": agency["sender_name"] or agency["name"],
        "headline": f"{who}: creator agency for {', '.join(niches)}" if niches else f"{who}: creator agency",
        "years_experience": 0,
        "skills": niches,
        "tools": [],
        "roles": [],
        "projects": [],
        "proof_points": [roster_line(c) for c in roster if roster_line(c)][:8],
        "agency": agency, "niches": niches, "roster": roster,
    }


def roster_line(c: dict) -> str:
    """One plain line for a creator, made only from fields that passed the checks."""
    bits = [c["name"] or c["channel_url"]]
    if c["niche"]:
        bits.append(c["niche"])
    if c["avg_views"]:
        bits.append(f"{c['avg_views']} average views")
    if c["subscribers"]:
        bits.append(f"{c['subscribers']} subscribers")
    return ", ".join(bits) if len(bits) > 1 else ""
