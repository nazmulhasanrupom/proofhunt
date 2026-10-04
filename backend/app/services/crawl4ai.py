"""Crawl4AI client: read one page. Free. Firecrawl is the fallback (see scraper.py)."""
import asyncio
import re

import httpx

from ..config import settings


class Crawl4aiError(Exception):
    """This reader could not get the page. The caller may try Firecrawl."""


class PageGone(Crawl4aiError):
    """The site itself answered 404 or 410. A second reader would get the same answer."""


_slots: asyncio.Semaphore | None = None
MIN_CHARS = 100  # shorter than this usually means a page that needs a stronger browser: let Firecrawl try


def enabled() -> bool:
    return bool(settings.crawl4ai_url and settings.crawl4ai_token)


def _base() -> str:
    return settings.crawl4ai_url.rstrip("/")


def _links_from_html_links(links: dict | None) -> list[str]:
    out = []
    for item in (links or {}).get("internal", []) or []:
        href = item.get("href") if isinstance(item, dict) else item
        if href and "[" not in href and "#" not in href:
            out.append(href)
    return list(dict.fromkeys(out))


def _links_from_markdown(md: str) -> list[str]:
    found = re.findall(r"\]\((https?://[^)\s]+|/[^)\s]*)\)", md or "")
    return list(dict.fromkeys(u for u in found if "[" not in u and "#" not in u))


def parse_crawl(r: dict, main_only: bool) -> dict:
    """One item of the /crawl answer -> the shape the audit expects."""
    status = r.get("redirected_status_code") or r.get("status_code")
    if r.get("success") is False or (status and status in (404, 410)):
        msg = (r.get("error_message") or "").strip()
        if status in (404, 410):
            raise PageGone(f"page returned HTTP {status}")
        raise Crawl4aiError(msg[:150] or "crawl failed")
    if status and status >= 400:
        raise Crawl4aiError(f"page returned HTTP {status}")
    md = r.get("markdown")
    if isinstance(md, dict):
        text = (md.get("fit_markdown") if main_only else None) or md.get("raw_markdown") or ""
    else:
        text = md or ""
    if len(text.strip()) < MIN_CHARS:
        raise Crawl4aiError(f"page text too short ({len(text.strip())} characters)")
    links = _links_from_html_links(r.get("links")) or _links_from_markdown(text)
    return {"markdown": text, "links": links, "raw_html": r.get("html"), "status": status, "cached": False}


async def _post(path: str, body: dict) -> dict:
    global _slots
    if _slots is None:
        _slots = asyncio.Semaphore(max(1, settings.crawl4ai_concurrency))
    headers = {"Authorization": f"Bearer {settings.crawl4ai_token}"}
    try:
        async with _slots:
            async with httpx.AsyncClient(timeout=settings.crawl4ai_timeout) as client:
                r = await client.post(_base() + path, json=body, headers=headers)
    except httpx.HTTPError as e:
        raise Crawl4aiError(f"{type(e).__name__} {str(e)[:100]}".strip())
    if r.status_code in (401, 403):
        raise Crawl4aiError(f"Crawl4AI refused the token (HTTP {r.status_code})")
    if r.status_code >= 400:
        raise Crawl4aiError(f"Crawl4AI HTTP {r.status_code}: {r.text[:100]}")
    try:
        return r.json()
    except ValueError:
        raise Crawl4aiError("Crawl4AI sent an answer that is not JSON")


async def fetch(url: str, main_only: bool) -> dict:
    """Try /crawl (text, links, html and the real HTTP status in one call), then /md (text only)."""
    first: Crawl4aiError | None = None
    try:
        data = await _post("/crawl", {"urls": [url]})
        results = data.get("results") or []
        if not results:
            raise Crawl4aiError("empty answer")
        return parse_crawl(results[0], main_only)
    except PageGone:
        raise
    except Crawl4aiError as e:
        first = e
    try:
        data = await _post("/md", {"url": url, "f": "fit" if main_only else "raw"})
        text = data.get("markdown") or ""
        if data.get("success") is False or len(text.strip()) < MIN_CHARS:
            raise Crawl4aiError(f"/md gave no usable text ({len(text.strip())} characters)")
        return {"markdown": text, "links": _links_from_markdown(text), "raw_html": None, "status": None, "cached": False}
    except Crawl4aiError as e:
        raise Crawl4aiError(f"{first}; then {e}")
