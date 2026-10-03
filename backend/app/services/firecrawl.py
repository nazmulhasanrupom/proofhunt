"""Firecrawl API v2. Two functions only: search and scrape."""
import asyncio
import math

import httpx

from ..config import settings
from ..db import get_db
from . import usage

BASE = "https://api.firecrawl.dev/v2"


class ScrapeError(Exception):
    pass


async def _post(path: str, body: dict) -> dict:
    if not settings.firecrawl_api_key:
        raise RuntimeError("FIRECRAWL_API_KEY is not set")
    headers = {"Authorization": f"Bearer {settings.firecrawl_api_key}"}
    async with httpx.AsyncClient(timeout=90) as client:
        for attempt in range(3):
            r = await client.post(f"{BASE}{path}", json=body, headers=headers)
            if r.status_code == 429 and attempt < 2:
                await asyncio.sleep(min(float(r.headers.get("Retry-After", 5)), 60))
                continue
            r.raise_for_status()
            return r.json()
    raise RuntimeError("Firecrawl: rate limited")


async def search(query: str, limit: int = 20, run_id: str | None = None) -> dict:
    """Returns {'results': [{title, description, url}], 'credits': int}. No scrapeOptions."""
    cost = 2 * math.ceil(limit / 10)
    await asyncio.to_thread(usage.check_credit_budget, cost, run_id)
    data = await _post("/search", {"query": query, "limit": limit})
    web = (data.get("data") or {}).get("web") or []
    results = [{"title": w.get("title"), "description": w.get("description"), "url": w.get("url")} for w in web]
    credits = data.get("creditsUsed") or cost
    await asyncio.to_thread(usage.add_usage, credits, 0, 0, 0, 0)
    await asyncio.to_thread(usage.bump_run, run_id, credits)
    return {"results": results, "credits": credits}


async def scrape(url: str, formats: list[str], only_main_content: bool,
                 company_id: str, kind: str = "other", run_id: str | None = None) -> dict:
    """Returns {'markdown','links','raw_html','status'}. Raises ScrapeError on failure.
    Cached: a URL already in `pages` costs no credit."""
    db = get_db()
    cached = db.table("pages").select("markdown,raw_html").eq("company_id", company_id).eq("url", url).execute().data
    if cached:
        return {"markdown": cached[0]["markdown"], "links": [], "raw_html": cached[0]["raw_html"],
                "status": 200, "cached": True}
    await asyncio.to_thread(usage.check_credit_budget, 1, run_id)
    try:
        data = await _post("/scrape", {"url": url, "formats": formats, "onlyMainContent": only_main_content})
    except httpx.HTTPError as e:
        code = getattr(getattr(e, "response", None), "status_code", None)
        if code != 429:  # a failed call may still cost 1 credit. Count it to stay safe.
            await asyncio.to_thread(usage.add_usage, 1, 0, 0, 0, 0)
            await asyncio.to_thread(usage.bump_run, run_id, 1)
        raise ScrapeError(f"{type(e).__name__} {code or ''} {str(e)[:120]}".strip())
    await asyncio.to_thread(usage.add_usage, 1, 0, 0, 0, 0)
    await asyncio.to_thread(usage.bump_run, run_id, 1)
    d = data.get("data") or {}
    status = (d.get("metadata") or {}).get("statusCode")
    out = {"markdown": d.get("markdown") or "", "links": d.get("links") or [],
           "raw_html": d.get("rawHtml"), "status": status, "cached": False}
    if status and status >= 400:
        raise ScrapeError(f"page returned HTTP {status}")
    db.table("pages").upsert({
        "company_id": company_id, "url": url, "kind": kind,
        "markdown": out["markdown"], "raw_html": out["raw_html"] if kind == "home" else None,
    }, on_conflict="company_id,url").execute()
    return out
