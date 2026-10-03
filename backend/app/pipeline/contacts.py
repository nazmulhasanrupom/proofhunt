"""Contact pick. Code only, no credits, no LLM."""
import asyncio
import re

import dns.resolver

OWNER = ["founder", "cofounder", "owner", "managing director", "principal", "proprietor"]
C_SUITE = [r"ceo", r"coo", r"cmo", r"cto", r"cfo", r"chief\b.*", r"president"]
HEAD = [r"head of .*", r"director of .*", r"vp\b.*", r"vice president.*"]
ENTRY = ["intern", "junior", "trainee", "apprentice", "graduate"]

GENERIC = ["hello", "info", "contact", "team", "office", "enquiries", "hi", "sales"]
NEVER = ["noreply", "no-reply", "privacy", "jobs", "careers", "hr", "support", "billing", "abuse"]


def norm_title(t: str) -> str:
    t = (t or "").lower()
    t = re.sub(r"co[\s\-]?founder", "cofounder", t)
    return re.sub(r"\s+", " ", t).strip()


def has_word(text: str, term: str) -> bool:
    return re.search(rf"(?<![a-z0-9]){re.escape(norm_title(term))}(?![a-z0-9])", norm_title(text)) is not None


def seniority(title: str) -> str:
    t = norm_title(title)
    if any(has_word(t, w) for w in ENTRY):
        return "entry"
    if re.search(r"(?<![a-z])vice president", t) or any(re.search(rf"(?<![a-z0-9]){p}(?![a-z0-9])", t) for p in HEAD):
        return "head"
    if any(has_word(t, w) for w in OWNER):
        return "owner"
    if any(re.search(rf"(?<![a-z0-9]){p}(?![a-z0-9])", t) for p in C_SUITE):
        return "c_suite"
    return "other"


def pick_person(people: list[dict], pf: dict) -> dict | None:
    """People are in page order. Returns the chosen person dict (with seniority) or None."""
    prio = pf["titlePriority"]
    best, best_rank = None, None
    for p in people:
        title = p.get("title") or ""
        sen = seniority(title)
        if any(has_word(title, x) for x in pf["excludeTitle"]) or sen in pf["excludeSeniority"]:
            continue
        rank = next((i for i, x in enumerate(prio) if has_word(title, x)), None)
        by_title = rank is not None
        by_sen = sen in pf["seniority"]
        ok = by_title if pf["matchMode"] == "title_only" else (by_title or by_sen)
        if not ok:
            continue
        rank = rank if rank is not None else len(prio)
        if best_rank is None or rank < best_rank:
            best, best_rank = {**p, "seniority": sen}, rank
    return best


def match_email(person_name: str, emails: list[dict], allow_generic: bool) -> dict | None:
    """emails: [{'email','url'}] published on the company's own site. Never guess."""
    parts = re.findall(r"[a-z]+", (person_name or "").lower())
    first, last = (parts[0], parts[-1]) if parts else ("", "")
    cand = set()
    if first and last and first != last:
        cand |= {f"{first}.{last}", f"{first}{last}", f"{first[0]}{last}", f"{first[0]}.{last}", f"{first}_{last}"}
    if first:
        cand.add(first)
    for e in emails:
        local = e["email"].split("@")[0].lower()
        if local in cand:
            return {**e, "kind": "personal"}
    if allow_generic:
        for e in emails:
            local = e["email"].split("@")[0].lower()
            if local in NEVER:
                continue
            if local in GENERIC:
                return {**e, "kind": "generic"}
    return None


async def mx_ok(domain: str) -> bool:
    def _q():
        try:
            return len(dns.resolver.resolve(domain, "MX", lifetime=5)) > 0
        except Exception:
            return False
    return await asyncio.to_thread(_q)


# ---------- stage runner (touches the database) ----------
from ..db import get_db  # noqa: E402
from ..services.usage import log_event  # noqa: E402
from .scope import todo as scope_todo  # noqa: E402


async def run(run_id: str, campaign: dict, should_stop, ids: list[str] | None = None):
    db = get_db()
    f = campaign["filters"]
    todo = scope_todo(run_id, ["extracted"], ids)
    for c in todo:
        if should_stop():
            return
        people = db.table("people").select("*").eq("company_id", c["id"]).order("created_at").execute().data
        chosen = pick_person(people, f["person"])
        emails = (c.get("facts") or {}).get("emails", [])
        match = match_email(chosen["name"], emails, f["email"]["allowGeneric"]) if chosen else None
        if match and f["email"]["requireMx"] and not await mx_ok(match["email"].split("@")[1]):
            match = None
        if not chosen or not match:
            db.table("companies").update({"status": "no_contact",
                "fail_reason": "no person" if not chosen else "no usable email"}).eq("id", c["id"]).execute()
            log_event(run_id, "info", "contact", f"{c['domain']}: no_contact")
            continue
        db.table("people").update({
            "selected": True, "seniority": chosen["seniority"], "email": match["email"],
            "email_kind": match["kind"], "email_source": match["url"], "mx_ok": True,
        }).eq("id", chosen["id"]).execute()
        db.table("companies").update({"status": "contacted"}).eq("id", c["id"]).execute()
        log_event(run_id, "info", "contact", f"{c['domain']}: {chosen['name']} ({match['kind']} email)")
