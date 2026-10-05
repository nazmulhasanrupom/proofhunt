"""Contact pick. Code only, no credits, no LLM."""
import asyncio
import re

import dns.resolver

OWNER = ["founder", "cofounder", "owner", "managing director", "principal", "proprietor"]
C_SUITE = [r"ceo", r"coo", r"cmo", r"cto", r"cfo", r"chief\b.*", r"president"]
HEAD = [r"head of .*", r"director of .*", r"vp\b.*", r"vice president.*"]
ENTRY = ["intern", "junior", "trainee", "apprentice", "graduate"]

GENERIC = ["hello", "info", "contact", "team", "office", "enquiries", "enquiry", "inquiries", "inquiry", "hi", "hey", "sales",
           "admin", "mail", "general", "studio", "agency", "marketing", "partnerships", "partners", "business", "bookings",
           "talk", "connect", "projects", "growth"]
# IMA: a brand that wants creators often publishes one of these inboxes
GENERIC_IMA = ["creators", "influencers", "affiliates", "sponsorships", "collabs", "ambassadors"]
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


def is_outsider(title: str, own: set[str]) -> bool:
    """'CMO at Workbooks' on a team-less page is a client in a testimonial, not staff. A title that says 'at <org>'
    counts as staff only when the org is the company itself."""
    m = re.search(r"(?:\bat\b|@)\s+(.+)$", title or "", re.I)
    if not m or not own:
        return False
    org = re.sub(r"[^a-z0-9]+", "", m.group(1).lower())
    return not any(w and w in org for w in own)


def pick_person(people: list[dict], pf: dict, own: set[str] | None = None) -> dict | None:
    """People are in page order. Returns the chosen person dict (with seniority) or None."""
    prio = pf["titlePriority"]
    best, best_rank = None, None
    for p in people:
        title = p.get("title") or ""
        if is_outsider(title, own or set()):
            continue
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


def match_email(person_name: str, emails: list[dict], allow_generic: bool, extra_generic: list[str] = ()) -> dict | None:
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
            if local in GENERIC or local in extra_generic:
                return {**e, "kind": "generic"}
    return None


def pick_contact(people: list[dict], emails: list[dict], f: dict, own: set[str] | None = None, extra_generic: list[str] = ()) -> tuple[dict | None, dict | None, str | None]:
    """(person, email, why_not). With no fitting person, a generic address still makes a lead when the campaign allows it."""
    chosen = pick_person(people, f["person"], own)
    if chosen:
        match = match_email(chosen["name"], emails, f["email"]["allowGeneric"], extra_generic)
        return (chosen, match, None) if match else (None, None, "no usable email")
    if f["email"].get("allowNoPerson", True) and f["email"]["allowGeneric"]:
        match = match_email("", emails, True, extra_generic)
        if match:
            return {"id": None, "name": "", "title": "", "seniority": None}, match, None
    return None, None, "no person"


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
from .kinds import IMA, kind_of  # noqa: E402
from .scope import todo as scope_todo  # noqa: E402


async def run(run_id: str, campaign: dict, should_stop, ids: list[str] | None = None):
    db = get_db()
    f = campaign["filters"]
    todo = scope_todo(run_id, ["extracted"], ids)
    ima = kind_of(campaign["profile_id"]) == IMA
    extra = GENERIC_IMA if ima else []
    for c in todo:
        if should_stop():
            return
        people = db.table("people").select("*").eq("company_id", c["id"]).order("created_at").execute().data
        emails = (c.get("facts") or {}).get("emails", [])
        own = {re.sub(r"[^a-z0-9]+", "", x.lower()) for x in (c["domain"].split(".")[0], c.get("name") or "") if x}
        chosen, match, why = pick_contact(people, emails, f, own, extra)
        if match and f["email"]["requireMx"] and not await mx_ok(match["email"].split("@")[1]):
            chosen, match, why = None, None, "no usable email"
        if ima and not match:
            # IMA keeps every brand. Any address published on the site will do. With none, the brand stays in the sheet as "do manually"
            from .brand_leads import first_site_email  # here, not at the top: brand_leads imports this module
            chosen = pick_person(people, f["person"], own)
            match = first_site_email(c.get("facts") or {})
            if match and f["email"]["requireMx"] and not await mx_ok(match["email"].split("@")[1]):
                match = None
            if match:
                match = {**match, "kind": "generic"}
                chosen = chosen or {"id": None, "name": "", "title": "", "seniority": None}
            else:
                db.table("people").update({"selected": False}).eq("company_id", c["id"]).execute()
                if chosen:
                    db.table("people").update({"selected": True, "seniority": chosen["seniority"]}).eq("id", chosen["id"]).execute()
                db.table("companies").update({"status": "contacted", "fail_reason": None}).eq("id", c["id"]).execute()
                log_event(run_id, "info", "contact", f"{c['domain']}: no email on the site, kept as 'do manually'")
                continue
        if not match:
            db.table("companies").update({"status": "no_contact", "fail_reason": why}).eq("id", c["id"]).execute()
            log_event(run_id, "info", "contact", f"{c['domain']}: no_contact ({why})")
            continue
        db.table("people").update({"selected": False}).eq("company_id", c["id"]).execute()  # one contact per company
        fields = {"selected": True, "seniority": chosen["seniority"], "email": match["email"],
                  "email_kind": match["kind"], "email_source": match["url"], "mx_ok": True}
        if chosen["id"]:
            db.table("people").update(fields).eq("id", chosen["id"]).execute()
        else:  # nobody named on the site: the lead is the generic address
            db.table("people").insert({"company_id": c["id"], "name": "", "title": "", "source": "website", **fields}).execute()
        db.table("companies").update({"status": "contacted"}).eq("id", c["id"]).execute()
        log_event(run_id, "info", "contact", f"{c['domain']}: {chosen['name'] or 'no named person'} ({match['kind']} email)")
