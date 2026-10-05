"""A 2-month cache for facts only: pages, and what the AI read out of them (company facts, people, evidence).
It is shared by every profile, so the same company site is read once, not once per profile.

Never put anything here that was made for a freelancer: judgments, reports, demo specs and emails stay per profile.
Never put an error here: a page that could not be read, an empty page and a failed AI read are tried again next time.
A row older than CACHE_DAYS is ignored when read and deleted by purge() (the worker runs it every day).
If the cache tables are missing (migration 004 not run) every call does nothing: the pipeline works, only without a cache."""
import hashlib
import json
import re
from datetime import datetime, timedelta, timezone

from ..db import get_db

CACHE_DAYS = 60  # 2 months

PARKED = re.compile(r"domain (is )?for sale|buy this domain|this domain may be for sale|parked (free|domain)|sedoparking", re.I)
_warned = False


def cutoff() -> str:
    """Anything saved before this moment is too old."""
    return (datetime.now(timezone.utc) - timedelta(days=CACHE_DAYS)).isoformat()


def _soft(e: Exception):
    global _warned
    if not _warned:
        _warned = True
        print(f"cache not available ({type(e).__name__}). Run backend/migrations/004_cache.sql. Going on without a cache.")


def page_ok(markdown: str | None) -> bool:
    """A real page. An empty or parked page looks like a failed read, so it is not kept."""
    md = (markdown or "").strip()
    return len(md) >= 100 and not PARKED.search(md)


def page_get(url: str) -> dict | None:
    try:
        rows = get_db().table("page_cache").select("kind,markdown,raw_html").eq("url", url).gte("cached_at", cutoff()).limit(1).execute().data
    except Exception as e:
        _soft(e)
        return None
    return rows[0] if rows else None


def page_put(url: str, kind: str, markdown: str | None, raw_html: str | None):
    if not page_ok(markdown):
        return
    try:
        get_db().table("page_cache").upsert({"url": url, "kind": kind, "markdown": markdown, "raw_html": raw_html,
                                             "cached_at": datetime.now(timezone.utc).isoformat()}, on_conflict="url").execute()
    except Exception as e:
        _soft(e)


def signal_sig(llm_signals: list[dict]) -> str:
    """The AI reads a page for the signals of the offer map. Two profiles with the same signals share a cache row."""
    items = sorted((s["name"].strip().lower(), (s.get("config") or {}).get("question") or s.get("description") or "") for s in llm_signals)
    return hashlib.sha256(json.dumps(items).encode()).hexdigest()[:16]


def extract_get(domain: str, sig: str) -> dict | None:
    try:
        rows = get_db().table("extract_cache").select("payload").eq("domain", domain).eq("sig", sig).gte("cached_at", cutoff()).limit(1).execute().data
    except Exception as e:
        _soft(e)
        return None
    return rows[0]["payload"] if rows else None


def extract_put(domain: str, sig: str, payload: dict):
    try:
        get_db().table("extract_cache").upsert({"domain": domain, "sig": sig, "payload": payload,
                                                "cached_at": datetime.now(timezone.utc).isoformat()}, on_conflict="domain,sig").execute()
    except Exception as e:
        _soft(e)


def purge() -> dict:
    """Delete everything older than 2 months. Returns how many rows went."""
    db, old, out = get_db(), cutoff(), {}
    for table in ("page_cache", "extract_cache"):
        try:
            out[table] = len(db.table(table).delete().lt("cached_at", old).execute().data)
        except Exception as e:
            _soft(e)
            out[table] = 0
    return out
