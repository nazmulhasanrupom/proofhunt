"""Runs stages in order. Resumable: each stage picks up items by status."""
from datetime import datetime, timezone

from ..db import get_db
from ..services.usage import BudgetExceeded, log_event
from . import assets, audit, contacts, discovery, extract, judge, sequences


def _run_row(run_id: str) -> dict:
    return get_db().table("runs").select("*").eq("id", run_id).single().execute().data


def make_should_stop(run_id: str):
    def should_stop() -> bool:
        return _run_row(run_id)["status"] in ("paused", "cancelled")
    return should_stop


def _set(run_id: str, **kw):
    get_db().table("runs").update(kw).eq("id", run_id).execute()


def _counters(run_id: str) -> dict:
    db = get_db()
    comps = db.table("companies").select("status").eq("run_id", run_id).execute().data
    by = {}
    for c in comps:
        by[c["status"]] = by.get(c["status"], 0) + 1
    qualified = by.get("qualified", 0)
    return {"found": len(comps), "failed": by.get("failed", 0), "filtered_out": by.get("filtered_out", 0),
            "no_contact": by.get("no_contact", 0), "qualified": qualified,
            "maybe": by.get("maybe", 0), "rejected": by.get("rejected", 0), "by_status": by}


async def run_campaign(run_id: str):
    db = get_db()
    run = _run_row(run_id)
    if run["status"] in ("cancelled", "done"):
        return
    campaign = db.table("campaigns").select("*").eq("id", run["campaign_id"]).single().execute().data
    f = campaign["filters"]
    should_stop = make_should_stop(run_id)
    _set(run_id, status="running", started_at=run["started_at"] or datetime.now(timezone.utc).isoformat())
    log_event(run_id, "info", "run", "run started")

    stages = [
        ("discovery", lambda: discovery.run(run_id, campaign, f["maxCompaniesToScan"])),
        ("audit", lambda: audit.run(run_id, should_stop)),
        ("extract", lambda: extract.run(run_id, campaign, should_stop)),
        ("contacts", lambda: contacts.run(run_id, campaign, should_stop)),
        ("judge", lambda: judge.run(run_id, campaign, should_stop)),
        ("assets", lambda: _assets_stage(run_id, campaign, should_stop)),
        ("sequences", lambda: _sequence_stage(run_id, campaign, should_stop)),
    ]
    try:
        for name, fn in stages:
            if should_stop():
                break
            _set(run_id, stage=name)
            await fn()
            counters = _counters(run_id)
            _set(run_id, counters=counters)
            if counters["qualified"] >= f["leadsWanted"]:
                log_event(run_id, "info", "run", "leadsWanted reached")
        if _run_row(run_id)["status"] == "running":
            _set(run_id, status="done", finished_at=datetime.now(timezone.utc).isoformat())
            log_event(run_id, "info", "run", "run done")
    except BudgetExceeded as e:
        _set(run_id, status="paused", error=str(e))
        log_event(run_id, "warn", "run", f"budget stop: {e}")
    except Exception as e:
        _set(run_id, status="failed", error=str(e)[:500], finished_at=datetime.now(timezone.utc).isoformat())
        log_event(run_id, "error", "run", f"run failed: {e}")


def _leads_for_run(run_id: str) -> list[dict]:
    db = get_db()
    ids = [c["id"] for c in db.table("companies").select("id").eq("run_id", run_id).eq("status", "qualified").execute().data]
    if not ids:
        return []
    return db.table("leads").select("*").in_("company_id", ids).execute().data


async def _assets_stage(run_id, campaign, should_stop):
    for lead in _leads_for_run(run_id):
        if should_stop():
            return
        try:
            await assets.build_assets(lead, campaign, run_id)
        except BudgetExceeded:
            raise
        except Exception as e:
            log_event(run_id, "error", "assets", str(e), lead_id=lead["id"])


async def _sequence_stage(run_id, campaign, should_stop):
    for lead in _leads_for_run(run_id):
        if should_stop():
            return
        if lead["stage"] != "new":
            continue
        try:
            await sequences.build_sequence(lead, run_id)
        except BudgetExceeded:
            raise
        except Exception as e:
            log_event(run_id, "error", "sequences", str(e), lead_id=lead["id"])
