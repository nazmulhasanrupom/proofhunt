"""Dashboard numbers, usage, sidebar badges, do-not-contact list."""
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..config import settings as env
from ..db import get_db
from ..sending.scheduler import DRY_ID

router = APIRouter()
HOT = "interested"
NO_REPLY = {"out_of_office"}  # an auto-reply is not a real answer
SCORE_BANDS = [(80, "80+"), (70, "70-79"), (60, "60-69"), (0, "under 60")]


def _all(table: str, cols: str, build=None) -> list[dict]:
    """Read every row. Supabase returns at most 1000 rows per call."""
    out, start = [], 0
    while True:
        q = get_db().table(table).select(cols)
        if build:
            q = build(q)
        rows = q.range(start, start + 999).execute().data or []
        out += rows
        if len(rows) < 1000:
            return out
        start += 1000


def _count(table: str, build=None) -> int:
    q = get_db().table(table).select("id", count="exact")
    if build:
        q = build(q)
    return q.limit(1).execute().count or 0


def _band(score: int | None) -> str:
    s = score or 0
    return next(label for lo, label in SCORE_BANDS if s >= lo)


def _rates(buckets: dict[str, list[int]]) -> list[dict]:
    rows = [{"key": k, "sent": v[0], "replied": v[1], "rate": round(v[1] / v[0], 3) if v[0] else 0} for k, v in buckets.items()]
    return sorted(rows, key=lambda r: (-r["rate"], -r["sent"], r["key"]))


@router.get("/stats")
def stats():
    db = get_db()
    since = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()

    companies = _all("companies", "id,status,last_audited_at,country,size_bucket")
    people_ok = {p["company_id"] for p in _all("people", "company_id", lambda q: q.eq("selected", True).not_.is_("email", "null"))}
    leads = _all("leads", "id,company_id,person_id,stage,score,judgment_id")
    sent_msgs = _all("messages", "lead_id,sent_at,gmail_message_id", lambda q: q.eq("status", "sent"))
    replies = _all("replies", "lead_id,classification")

    sent_leads = {m["lead_id"] for m in sent_msgs}
    replied_leads = {r["lead_id"] for r in replies if r["classification"] not in NO_REPLY}
    funnel = [
        ("Found", len(companies)),
        ("Audited", sum(1 for c in companies if c["last_audited_at"])),
        ("Contact found", len(people_ok)),
        ("Qualified", len(leads)),
        ("Sent", len(sent_leads)),
        ("Replied", len(replied_leads)),
        ("Meeting", sum(1 for l in leads if l["stage"] in ("meeting", "won"))),
        ("Won", sum(1 for l in leads if l["stage"] == "won")),
    ]

    # reply rate by group. Only leads that got at least one email count.
    comp = {c["id"]: c for c in companies}
    people = {p["id"]: p for p in _all("people", "id,email_kind")}
    judg = {j["id"]: j for j in _all("judgments", "id,offer_row_id")}
    service = {o["id"]: o["service"] for o in _all("offer_rows", "id,service")}
    sig_name = {s["id"]: s["name"] for s in _all("signals", "id,name")}
    sig_by_company: dict[str, set[str]] = defaultdict(set)
    for e in _all("evidence", "company_id,signal_id", lambda q: q.eq("verified", True).not_.is_("signal_id", "null")):
        if e["signal_id"] in sig_name:
            sig_by_company[e["company_id"]].add(sig_name[e["signal_id"]])

    dims: dict[str, dict[str, list[int]]] = {k: defaultdict(lambda: [0, 0]) for k in
                                             ("offer_row", "signal", "country", "size", "email_kind", "score_band")}

    def add(dim: str, key: str | None, replied: bool):
        b = dims[dim][key or "unknown"]
        b[0] += 1
        b[1] += int(replied)

    for l in leads:
        if l["id"] not in sent_leads:
            continue
        r = l["id"] in replied_leads
        c = comp.get(l["company_id"], {})
        add("offer_row", service.get((judg.get(l["judgment_id"]) or {}).get("offer_row_id")), r)
        for s in sig_by_company.get(l["company_id"], ()):
            add("signal", s, r)
        add("country", c.get("country"), r)
        add("size", c.get("size_bucket"), r)
        add("email_kind", (people.get(l["person_id"]) or {}).get("email_kind"), r)
        add("score_band", _band(l["score"]), r)
    by = {k: _rates(v) for k, v in dims.items()}

    hot = (db.table("replies").select("id,from_email,received_at,snippet,leads(id, companies(domain,name))")
           .eq("classification", HOT).order("received_at", desc=True).limit(8).execute().data)
    real_week = [m for m in sent_msgs if m["sent_at"] and m["sent_at"] >= since and m["gmail_message_id"] != DRY_ID]
    dry_week = [m for m in sent_msgs if m["sent_at"] and m["sent_at"] >= since and m["gmail_message_id"] == DRY_ID]
    n_sent, n_replied = len(sent_leads), len(replied_leads)
    return {
        "cards": {
            "qualified": len(leads),
            "sent_week": len(real_week), "sent_week_dry": len(dry_week),
            "reply_rate": round(n_replied / n_sent, 3) if n_sent else None,
            "credits_left": credits_left(),
        },
        "funnel": [{"label": k, "count": v} for k, v in funnel],
        "reply_rates": by,
        "top_signals": [r for r in by["signal"] if r["sent"] >= 1][:3],
        "hot_replies": hot,
    }


def credits_left() -> int | None:
    """Starting balance minus all credits used. Falls back to the DEV limit. None if neither is set."""
    used = sum(r["firecrawl_credits"] or 0 for r in _all("usage_daily", "firecrawl_credits"))
    start = (get_db().table("settings").select("*").eq("id", 1).single().execute().data or {}).get("firecrawl_start_balance")
    start = start or env.dev_firecrawl_credit_limit
    return None if start is None else start - used


@router.get("/usage")
def usage(days: int = 30):
    days = max(1, min(days, 365))
    first = (datetime.now(timezone.utc).date() - timedelta(days=days - 1)).isoformat()
    rows = {r["day"]: r for r in _all("usage_daily", "*", lambda q: q.gte("day", first))}
    out = []
    for i in range(days):
        d = (datetime.now(timezone.utc).date() - timedelta(days=days - 1 - i)).isoformat()
        r = rows.get(d, {})
        out.append({
            "day": d, "credits": r.get("firecrawl_credits") or 0, "llm_calls": r.get("llm_calls") or 0,
            "tokens": (r.get("llm_input_tokens") or 0) + (r.get("llm_output_tokens") or 0),
            "emails": r.get("emails_sent") or 0,
        })
    total = {k: sum(d[k] for d in out) for k in ("credits", "llm_calls", "tokens", "emails")}
    runs = (get_db().table("runs").select("id,credits_used,llm_calls,llm_input_tokens,llm_output_tokens,counters,campaigns(name),started_at")
            .order("created_at", desc=True).limit(20).execute().data)
    per_run = [{
        "id": r["id"], "campaign": (r.get("campaigns") or {}).get("name"), "started_at": r["started_at"],
        "credits": r["credits_used"] or 0, "llm_calls": r["llm_calls"] or 0,
        "tokens": (r["llm_input_tokens"] or 0) + (r["llm_output_tokens"] or 0),
        "qualified": (r["counters"] or {}).get("qualified", 0),
    } for r in runs]
    return {"days": out, "total": total, "credits_left": credits_left(), "per_run": per_run}


@router.get("/counts")
def counts():
    """Sidebar badges. Unread replies are worked out in the browser (it keeps the last-seen time)."""
    return {
        "leads": _count("leads", lambda q: q.eq("stage", "new")),
        "review": _count("leads", lambda q: q.eq("stage", "ready")),
        "reply_times": [r["received_at"] for r in
                        get_db().table("replies").select("received_at").order("received_at", desc=True).limit(200).execute().data],
    }


class Dnc(BaseModel):
    value: str
    reason: str | None = None


@router.get("/do-not-contact")
def dnc_list():
    return get_db().table("do_not_contact").select("*").order("created_at", desc=True).execute().data


@router.post("/do-not-contact")
def dnc_add(body: Dnc):
    v = body.value.strip().lower()
    if not v or " " in v or "." not in v and "@" not in v:
        raise HTTPException(422, "Enter an email like a@b.com or a domain like b.com")
    kind = "email" if "@" in v else "domain"
    get_db().table("do_not_contact").upsert({"value": v, "kind": kind, "reason": body.reason or "added by hand"}, on_conflict="value").execute()
    return {"ok": True}


@router.delete("/do-not-contact/{did}")
def dnc_remove(did: str):
    get_db().table("do_not_contact").delete().eq("id", did).execute()
    return {"ok": True}
