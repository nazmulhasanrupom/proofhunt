"""IMA: the last stage. No judge, no report, no emails. A brand that got through the filters is qualified, and one row goes in the lead sheet (brand_leads).
Code only: no credits, no AI calls."""
from datetime import datetime, timezone

from ..db import get_db
from ..services.usage import log_event
from .contacts import GENERIC, GENERIC_IMA, NEVER
from .offer_map import load_map
from .scope import todo as scope_todo

GOOD, MANUAL = "good to go", "do manually"


def site_emails(facts: dict) -> list[dict]:
    """Emails published on the brand's own site, without the ones nobody reads (privacy@, jobs@ ...)."""
    out, seen = [], set()
    for e in (facts or {}).get("emails") or []:
        addr = (e.get("email") or "").strip()
        if addr and addr.lower() not in seen and addr.split("@")[0].lower() not in NEVER:
            seen.add(addr.lower())
            out.append(e)
    return out


def first_site_email(facts: dict) -> dict | None:
    """The best address when no person matched: an inbox made for partnerships first, then any other generic one, then the first."""
    emails = site_emails(facts)
    for names in (GENERIC_IMA + ["partnerships", "partners"], GENERIC):
        for e in emails:
            if e["email"].split("@")[0].lower() in names:
                return e
    return emails[0] if emails else None


def build_row(c: dict, person: dict | None, evidence: list[dict], signal_names: dict[str, str]) -> dict:
    """One row of the lead sheet. `evidence` is the verified evidence of the brand. `signal_names` maps a signal id to its name."""
    facts = c.get("facts") or {}
    person = person or {}
    proof = [e for e in evidence if e.get("verified") and e.get("kind") != "tech"]
    emails = [person["email"]] if person.get("email") else []
    emails += [e["email"] for e in site_emails(facts) if e["email"].lower() not in {x.lower() for x in emails}]
    names = list(dict.fromkeys(signal_names[e["signal_id"]] for e in proof if e.get("signal_id") in signal_names))
    size = c.get("size_estimate")
    url = f"https://{c['domain']}"
    return {
        "website_url": c.get("source_url") or url,
        "brand": (c.get("name") or c["domain"]).strip()[:200],
        "brand_url": url,
        "category": (facts.get("sells") or ", ".join(c.get("keyword_hits") or []))[:300],
        "sponsorships": " | ".join(f"“{e['quote'][:300]}” ({e['url']})" for e in proof),
        "creators": "; ".join(names),
        "emails": "; ".join(emails),
        "employees": str(size) if size else "",
        "type": GOOD if person.get("email") else MANUAL,
        "country": c.get("country"),
        "contact_name": person.get("name") or None,
        "contact_title": person.get("title") or None,
        "email_source": person.get("email_source"),
        "proof_count": len(proof),
        "keyword_hits": c.get("keyword_hits") or [],
    }


async def run(run_id: str, campaign: dict, should_stop, ids: list[str] | None = None, stop_when=None):
    db = get_db()
    pid = campaign["profile_id"]
    signal_names = {s["id"]: s["name"] for r in load_map(pid) for s in r["signals"]}
    for c in scope_todo(run_id, ["contacted"], ids):
        if should_stop() or (stop_when and stop_when()):  # stop_when: the leads wanted exist. The rest stays 'contacted'
            return
        try:
            person = (db.table("people").select("*").eq("company_id", c["id"]).eq("selected", True).execute().data or [None])[0]
            ev = db.table("evidence").select("signal_id,kind,quote,url,verified").eq("company_id", c["id"]).eq("verified", True).execute().data
            row = {**build_row(c, person, ev, signal_names), "company_id": c["id"], "profile_id": pid, "campaign_id": campaign["id"],
                   "updated_at": datetime.now(timezone.utc).isoformat()}
            db.table("brand_leads").upsert(row, on_conflict="company_id").execute()
            db.table("companies").update({"status": "qualified", "fail_reason": None}).eq("id", c["id"]).execute()
            log_event(run_id, "info", "brand_leads", f"{c['domain']}: qualified ({row['type']}, {row['proof_count']} proof)")
        except Exception as e:
            log_event(run_id, "error", "brand_leads", f"{c['domain']}: {e}")
