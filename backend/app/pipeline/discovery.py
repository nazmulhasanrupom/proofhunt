import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import tldextract
from pydantic import BaseModel

from ..db import get_db
from ..services import firecrawl, llm
from ..services.usage import log_event
from .kinds import IMA, kind_of
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


# IMA: a brand is found by proof that it pays creators. {k} is a product keyword. The strongest search comes first,
# and the searches go template by template, so a small run still covers every keyword with the best ones.
IMA_TEMPLATES = ['"{k}" "creator program"', '"{k}" "affiliate program"', '"{k}" "partner with creators"',
                 '"{k}" careers "influencer marketing"', '"{k}" careers "creator partnerships"', '"{k}" "ambassador program"']


def build_queries_ima(filters: dict) -> list[str]:
    """Brand searches. No country in them: a brand that sells online is not tied to a place. The country filter runs later."""
    seen, out = set(), []
    for t in IMA_TEMPLATES:
        for k in filters["company"]["webKeywords"]:
            q = t.format(k=k)
            if q not in seen:
                seen.add(q)
                out.append(q)
    return out


def build_queries(filters: dict, offer_rows: list[dict], kind: str = "freelancer") -> list[str]:
    if kind == IMA:
        return build_queries_ima(filters)
    c = filters["company"]
    places = [""] if c.get("anyCountry") or not c["countries"] else c["countries"]  # no country: search the whole web
    qs = [f'"{k}" agency {place}'.strip() for k in c["webKeywords"] for place in places]
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


async def run(run_id: str, campaign: dict, scan_cap: int, should_stop=lambda: False, round_cap: int | None = None):
    """Find clean agency domains until `scan_cap` companies exist for this run. Stops when the run is paused or cancelled.
    With `round_cap` it stops searching once that many companies exist (a round), and a later call goes on from there.
    Every search is used up to the end: its results are saved even when they pass the round cap."""
    target = min(scan_cap, round_cap) if round_cap else scan_cap
    db = get_db()
    f = campaign["filters"]
    c = f["company"]
    pid = campaign["profile_id"]  # a site or a search that another profile already used is still new for this one
    kind = kind_of(pid)
    ima = kind == IMA
    rows = [r for r in load_map(pid) if r["active"]]
    for r in rows:
        r["signals"] = [s for s in r["signals"] if s["active"]]

    have = db.table("companies").select("id", count="exact").eq("run_id", run_id).execute().count or 0
    if have >= target:
        return

    n_queries = max(1, scan_cap // 5)
    queries = build_queries(f, rows, kind)
    extra = 0
    if len(queries) < n_queries:
        extra = min(20, n_queries - len(queries))
    if extra:  # the AI's extra queries are only needed once every keyword query was searched (this is called again and again, a round at a time)
        done = {r["query_hash"] for r in db.table("search_queries").select("query_hash").eq("profile_id", pid)
                .in_("query_hash", [qhash(q) for q in queries]).execute().data}
        if any(qhash(q) not in done for q in queries):
            extra = 0
    if extra:
        out = await llm.complete_json(
            "queries", "fast", llm.load_prompt("queries_ima" if ima else "queries"),
            json.dumps({"N": extra, ("niches" if ima else "services"): [r["service"] for r in rows], "keywords": c["webKeywords"],
                        "already": queries[:20]}), QueriesOut, run_id)
        queries += out["queries"][:extra]
    queries = queries[:n_queries]

    dnc = {r["value"] for r in db.table("do_not_contact").select("value").execute().data}
    exclude = dnc | {d.lower() for d in c["excludeDomains"]}
    cutoff = (datetime.now(timezone.utc) - timedelta(days=c["cooldownDays"])).isoformat()
    limit = 20 if scan_cap >= 20 else 10

    for q in queries:
        if have >= target or should_stop():
            break
        h = qhash(q)
        if db.table("search_queries").select("id").eq("profile_id", pid).eq("query_hash", h).execute().data:
            continue  # already searched in any run of this profile
        res = await firecrawl.search(q, limit, run_id)
        db.table("search_queries").insert({
            "run_id": run_id, "profile_id": pid, "query": q, "query_hash": h, "results": res["results"],
            "result_count": len(res["results"]), "credits": res["credits"]}).execute()

        recent = {r["domain"] for r in db.table("companies").select("domain").eq("profile_id", pid).gte("first_seen", cutoff).execute().data}
        cands = clean_domains(res["results"], exclude | recent)
        if not cands:
            continue
        # pre-screen: no credits, LLM only
        keep = []
        for i in range(0, len(cands), 20):
            batch = cands[i:i + 20]
            payload = [{"i": j, "title": b["title"], "description": b["description"], "url": b["url"]} for j, b in enumerate(batch)]
            out = await llm.complete_json(
                "prescreen", "fast", llm.load_prompt("prescreen_ima" if ima else "prescreen"),
                json.dumps({("niches" if ima else "services"): [r["service"] for r in rows], "results": payload}), PrescreenOut, run_id)
            verdicts = {v["i"]: v["verdict"] for v in out["results"]}
            keep += [b for j, b in enumerate(batch) if verdicts.get(j, "unsure") != "no"]
        for k in keep:
            if have >= scan_cap or should_stop():
                break
            existing = db.table("companies").select("id").eq("profile_id", pid).eq("domain", k["domain"]).execute().data
            if existing:  # outside cooldown: reuse the row for this run
                db.table("companies").update({"status": "new", "run_id": run_id, "fail_reason": None}).eq("id", existing[0]["id"]).execute()
            else:
                db.table("companies").insert({
                    "domain": k["domain"], "name": k["title"], "source": "firecrawl_search",
                    "source_ref": q, "run_id": run_id, "profile_id": pid, "status": "new",
                    **({"source_url": k["url"]} if ima else {})}).execute()  # only IMA saves the page it found the brand on: it is a column of the lead sheet
            have += 1
        log_event(run_id, "info", "discovery", f"query done: {q}", {"kept": len(keep), "total_companies": have})
