import asyncio
import re
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse

from ..db import get_db
from ..services import firecrawl
from ..services.usage import BudgetExceeded, log_event
from .scope import todo as scope_todo

PRIORITY = [
    ("about", r"about|team|who-we-are|people"),
    ("contact", r"contact"),
    ("careers", r"career|jobs|join|hiring"),
    ("services", r"services|what-we-do|seo"),
]
PARKED = re.compile(r"domain (is )?for sale|buy this domain|this domain may be for sale|parked (free|domain)|sedoparking", re.I)


def pick_pages(home_url: str, links: list[str]) -> list[tuple[str, str]]:
    """Up to 3 more pages: same domain, by priority. Returns [(kind, url)]."""
    host = urlparse(home_url).netloc.lower().removeprefix("www.")
    same = []
    for l in links:
        u = urljoin(home_url, l).split("#")[0]
        p = urlparse(u)
        if p.netloc.lower().removeprefix("www.") == host and p.scheme in ("http", "https") and p.path not in ("", "/"):
            same.append(u)
    picked = []
    for kind, rx in PRIORITY:
        for u in same:
            if re.search(rx, urlparse(u).path.lower()) and all(u != x[1] for x in picked):
                picked.append((kind, u))
                break
    return picked[:3]


async def audit_company(company: dict, run_id: str) -> bool:
    db = get_db()
    cid, domain = company["id"], company["domain"]
    db.table("companies").update({"status": "auditing"}).eq("id", cid).execute()
    home_url = f"https://{domain}"
    try:
        home = await firecrawl.scrape(home_url, ["markdown", "links", "rawHtml"], False, cid, "home", run_id)
    except firecrawl.ScrapeError as e:
        db.table("companies").update({"status": "failed", "fail_reason": f"homepage: {e}"[:200]}).eq("id", cid).execute()
        log_event(run_id, "warn", "audit", f"{domain}: homepage failed: {e}")
        return False
    if len((home["markdown"] or "").strip()) < 100:
        db.table("companies").update({"status": "failed", "fail_reason": "homepage empty"}).eq("id", cid).execute()
        return False
    if PARKED.search(home["markdown"]):
        db.table("companies").update({"status": "failed", "fail_reason": "parked"}).eq("id", cid).execute()
        return False
    links = home["links"] or re.findall(r'href=["\']([^"\'#]+)', home.get("raw_html") or "")  # cached home has no link list
    picked = pick_pages(home_url, links)
    for kind, url in picked:
        try:
            await firecrawl.scrape(url, ["markdown"], kind != "contact", cid, kind, run_id)
        except firecrawl.ScrapeError as e:  # a missing sub page is fine, keep going
            log_event(run_id, "warn", "audit", f"{domain}: {kind} page failed: {e}")
    db.table("companies").update({"status": "audited", "last_audited_at": datetime.now(timezone.utc).isoformat()}).eq("id", cid).execute()
    return True


async def run(run_id: str, should_stop, ids: list[str] | None = None):
    db = get_db()
    todo = scope_todo(run_id, ["new", "auditing"], ids)
    sem = asyncio.Semaphore(3)
    stopped = False

    async def one(c):
        nonlocal stopped
        async with sem:
            if stopped or should_stop():
                return
            try:
                await audit_company(c, run_id)
            except BudgetExceeded:
                stopped = True
                db.table("companies").update({"status": "new"}).eq("id", c["id"]).execute()  # not audited yet: pick it up next time
                raise
            except Exception as e:
                db.table("companies").update({"status": "failed", "fail_reason": f"audit error: {type(e).__name__}"}).eq("id", c["id"]).execute()
                log_event(run_id, "error", "audit", f"{c['domain']}: {e}")

    results = await asyncio.gather(*(one(c) for c in todo), return_exceptions=True)
    for r in results:
        if isinstance(r, BudgetExceeded):
            raise r
