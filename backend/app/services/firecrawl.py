"""Firecrawl API v2. Two functions only: search and scrape."""
import asyncio
import math
import time

import httpx

from ..config import settings
from ..db import get_db
from . import usage

BASE = "https://api.firecrawl.dev/v2"


class ScrapeError(Exception):
    pass


class RateLimited(ScrapeError):
    """Firecrawl kept answering 429 after all waits. The company is not at fault: try it again later."""


# ---- pacing: one gate for every Firecrawl call in this process -----------------
_gate = asyncio.Lock()
_slots: asyncio.Semaphore | None = None
_next_at = 0.0          # earliest time the next request may start
_interval = 0.0         # current wait between requests. Grows after a 429, shrinks again after successes


def _base_interval() -> float:
    return max(0.0, settings.firecrawl_min_interval)


def backoff_seconds(attempt: int, retry_after: float | None) -> float:
    """How long to wait after the n-th 429 (attempt starts at 0). Firecrawl's own hint wins when it is longer."""
    return min(90.0, max(retry_after or 0.0, 5.0 * 2 ** attempt))


async def _pace():
    """Wait until it is this caller's turn. Calls leave one by one, `_interval` seconds apart."""
    global _next_at, _interval
    async with _gate:
        if not _interval:
            _interval = _base_interval()
        wait = _next_at - time.monotonic()
        if wait > 0:
            await asyncio.sleep(wait)
        _next_at = time.monotonic() + _interval


def _slow_down(wait: float):
    """A 429 happened: every caller waits, and the gap between requests gets longer."""
    global _next_at, _interval
    _next_at = max(_next_at, time.monotonic() + wait)
    _interval = min(30.0, max(_interval, _base_interval(), 1.0) * 1.5)


def _speed_up():
    global _interval
    _interval = max(_base_interval(), _interval * 0.95)


async def _post(path: str, body: dict, run_id: str | None = None) -> dict:
    global _slots
    if not settings.firecrawl_api_key:
        raise RuntimeError("FIRECRAWL_API_KEY is not set")
    if _slots is None:
        _slots = asyncio.Semaphore(max(1, settings.firecrawl_concurrency))
    headers = {"Authorization": f"Bearer {settings.firecrawl_api_key}"}
    retries = max(0, settings.firecrawl_max_retries)
    async with httpx.AsyncClient(timeout=90) as client:
        for attempt in range(retries + 1):
            async with _slots:
                await _pace()
                r = await client.post(f"{BASE}{path}", json=body, headers=headers)
            if r.status_code == 429:
                if attempt >= retries:
                    raise RateLimited(f"Firecrawl said 429 (too many requests) {retries + 1} times")
                try:
                    hint = float(r.headers.get("Retry-After", ""))
                except ValueError:
                    hint = None
                wait = backoff_seconds(attempt, hint)
                _slow_down(wait)
                await asyncio.to_thread(usage.log_event, run_id, "warn", "firecrawl",
                                        f"Firecrawl is busy (429). Waiting {wait:.0f}s, then trying again ({attempt + 1} of {retries}). "
                                        f"Gap between requests is now {_interval:.1f}s.")
                continue
            r.raise_for_status()
            _speed_up()
            return r.json()
    raise RateLimited("Firecrawl: rate limited")


async def search(query: str, limit: int = 20, run_id: str | None = None) -> dict:
    """Returns {'results': [{title, description, url}], 'credits': int}. No scrapeOptions."""
    cost = 2 * math.ceil(limit / 10)
    await asyncio.to_thread(usage.check_credit_budget, cost, run_id)
    data = await _post("/search", {"query": query, "limit": limit}, run_id)
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
        data = await _post("/scrape", {"url": url, "formats": formats, "onlyMainContent": only_main_content}, run_id)
    except RateLimited:
        raise  # nothing was charged for a 429
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
