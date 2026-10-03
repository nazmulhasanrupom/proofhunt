import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import tldextract
from pydantic import BaseModel

from ..db import get_db
from ..services import firecrawl, llm
from ..services.usage import log_event
from .offer_map import load_map

BLOCKLIST = {l.strip().lower() for l in (Path(__file__).resolve().parent.parent / "blocklist.txt").read_text().splitlines() if l.strip()}


class QueriesOut(BaseModel):
    queries: list[str] = []


class _V(BaseModel):
    i: int
    verdict: str


class PrescreenOut(BaseModel):
    results: list[_V] = []


def main_domain(url: str) -> str | None:
    e = tldextract.extract(url)
    if not e.domain or not e.suffix:
        return None
    return f"{e.domain}.{e.suffix}".lower()


def qhash(q: str) -> str:
    return hashlib.sha256(q.strip().lower().encode()).hexdigest()


def build_queries(filters: dict, offer_rows: list[dict]) -> list[str]:
    c = filters["company"]
    qs = [f'"{k}" agency {country}' for k in c["webKeywords"] for country in c["countries"]]
    for r in offer_rows:
        for s in r.get("signals", []):
            if s["detector_type"] == "hiring_role":
                for role in s["config"].get("roles", []):
                    qs += [f'"{k}" careers "{role}"' for k in c["webKeywords"][:2]]
    return qs


def clean_domains(results: list[dict], exclude: set[str]) -> list[dict]:
    seen, out = set(), []
    for r in results:
        d = main_domain(r.get("url") or "")
        if not d or d in BLOCKLIST or d in exclude or d in seen:
            continue
        seen.add(d)
        out.append({**r, "domain": d})
    return out


async def run(run_id: str, campaign: dict, scan_cap: int):
    """Find clean agency domains until `scan_cap` companies exist for this run."""
    db = get_db()
    f = campaign["filters"]
    c = f["company"]
    rows = [r for r in load_map(campaign["profile_id"]) if r["active"]]
    for r in rows:
        r["signals"] = [s for s in r["signals"] if s["active"]]

    have = db.table("companies").select("id", count="exact").eq("run_id", run_id).execute().count or 0
    if have >= scan_cap:
        return

    n_queries = max(1, scan_cap // 5)
    queries = build_queries(f, rows)
    extra = 0
    if len(queries) < n_queries:
        extra = min(20, n_queries - len(queries))
    if extra:
        out = await llm.complete_json(
            "queries", "fast", llm.load_prompt("queries"),
            json.dumps({"N": extra, "services": [r["service"] for r in rows], "keywords": c["webKeywords"],
                        "already": queries[:20]}), QueriesOut, run_id)
        queries += out["queries"][:extra]
    queries = queries[:n_queries]

    dnc = {r["value"] for r in db.table("do_not_contact").select("value").execute().data}
    exclude = dnc | {d.lower() for d in c["excludeDomains"]}
    cutoff = (datetime.now(timezone.utc) - timedelta(days=c["cooldownDays"])).isoformat()
    limit = 20 if scan_cap >= 20 else 10

    for q in queries:
        if have >= scan_cap:
            break
        h = qhash(q)
        if db.table("search_queries").select("id").eq("query_hash", h).execute().data:
            continue  # already searched in any run
        res = await firecrawl.search(q, limit, run_id)
        db.table("search_queries").insert({
            "run_id": run_id, "query": q, "query_hash": h, "results": res["results"],
            "result_count": len(res["results"]), "credits": res["credits"]}).execute()

        recent = {r["domain"] for r in db.table("companies").select("domain").gte("first_seen", cutoff).execute().data}
        cands = clean_domains(res["results"], exclude | recent)
        if not cands:
            continue
        # pre-screen: no credits, LLM only
        keep = []
        for i in range(0, len(cands), 20):
            batch = cands[i:i + 20]
            payload = [{"i": j, "title": b["title"], "description": b["description"], "url": b["url"]} for j, b in enumerate(batch)]
            out = await llm.complete_json(
                "prescreen", "fast", llm.load_prompt("prescreen"),
                json.dumps({"services": [r["service"] for r in rows], "results": payload}), PrescreenOut, run_id)
            verdicts = {v["i"]: v["verdict"] for v in out["results"]}
            keep += [b for j, b in enumerate(batch) if verdicts.get(j, "unsure") != "no"]
        for k in keep:
            if have >= scan_cap:
                break
            existing = db.table("companies").select("id").eq("domain", k["domain"]).execute().data
            if existing:  # outside cooldown: reuse the row for this run
                db.table("companies").update({"status": "new", "run_id": run_id, "fail_reason": None}).eq("id", existing[0]["id"]).execute()
            else:
                db.table("companies").insert({
                    "domain": k["domain"], "name": k["title"], "source": "firecrawl_search",
                    "source_ref": q, "run_id": run_id, "status": "new"}).execute()
            have += 1
        log_event(run_id, "info", "discovery", f"query done: {q}", {"kept": len(keep), "total_companies": have})
