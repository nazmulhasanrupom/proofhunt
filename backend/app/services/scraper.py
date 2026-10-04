"""Read one page. Crawl4AI first (free), Firecrawl if that fails. Pages already saved are never read again."""
from ..db import get_db
from ..services import crawl4ai, firecrawl
from ..services.usage import log_event


async def scrape(url: str, formats: list[str], only_main_content: bool,
                 company_id: str, kind: str = "other", run_id: str | None = None) -> dict:
    """Returns {'markdown','links','raw_html','status','cached','source'}. Raises firecrawl.ScrapeError on failure."""
    db = get_db()
    cached = db.table("pages").select("markdown,raw_html").eq("company_id", company_id).eq("url", url).execute().data
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
    db.table("pages").upsert({
        "company_id": company_id, "url": url, "kind": kind,
        "markdown": out["markdown"], "raw_html": out["raw_html"] if kind == "home" else None,
    }, on_conflict="company_id,url").execute()
    return out
