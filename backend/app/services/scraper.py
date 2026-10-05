"""Read one page. Crawl4AI first (free), Firecrawl if that fails.
A page saved less than 2 months ago is not read again, not even for another profile. An older page is read again."""
from datetime import datetime, timezone

from ..db import get_db
from ..services import cache, crawl4ai, firecrawl
from ..services.usage import log_event


async def scrape(url: str, formats: list[str], only_main_content: bool,
                 company_id: str, kind: str = "other", run_id: str | None = None) -> dict:
    """Returns {'markdown','links','raw_html','status','cached','source'}. Raises firecrawl.ScrapeError on failure."""
    db = get_db()
    fresh = cache.cutoff()
    cached = db.table("pages").select("markdown,raw_html").eq("company_id", company_id).eq("url", url).gte("fetched_at", fresh).execute().data
    if not cached:  # the same site may be saved under another profile (or an earlier run): copy it, no credit
        hit = cache.page_get(url)
        if hit:
            db.table("pages").upsert({"company_id": company_id, "url": url, "kind": hit["kind"], "markdown": hit["markdown"],
                                      "raw_html": hit["raw_html"], "fetched_at": datetime.now(timezone.utc).isoformat()},
                                     on_conflict="company_id,url").execute()
            cached = [hit]
    if cached:
        return {"markdown": cached[0]["markdown"], "links": [], "raw_html": cached[0]["raw_html"],
                "status": 200, "cached": True, "source": "saved"}

    out, source = None, None
    if crawl4ai.enabled():
        try:
            out, source = await crawl4ai.fetch(url, only_main_content), "crawl4ai"
        except crawl4ai.PageGone as e:
            raise firecrawl.ScrapeError(str(e))
        except crawl4ai.Crawl4aiError as e:
            log_event(run_id, "warn", "scrape", f"Crawl4AI failed for {url}: {e}. Trying Firecrawl.")
    if out is None:
        out, source = await firecrawl.fetch(url, formats, only_main_content, run_id), "firecrawl"
    out["source"] = source
    raw = out["raw_html"] if kind == "home" else None
    db.table("pages").upsert({
        "company_id": company_id, "url": url, "kind": kind, "markdown": out["markdown"], "raw_html": raw,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }, on_conflict="company_id,url").execute()
    cache.page_put(url, kind, out["markdown"], raw)
    return out
