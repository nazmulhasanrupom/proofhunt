"""Runs stages in order. Resumable: each stage picks up items by status."""
from datetime import datetime, timezone

from ..db import get_db
from ..schemas import CampaignFilters
from ..services.usage import BudgetExceeded, StageLimitReached, log_event
from . import assets, audit, contacts, discovery, extract, judge, sequences
from .scope import chunks, todo as scope_todo


def _run_row(run_id: str) -> dict:
    return get_db().table("runs").select("*").eq("id", run_id).single().execute().data


def make_should_stop(run_id: str):
    def should_stop() -> bool:
        return _run_row(run_id)["status"] in ("paused", "cancelled")
    return should_stop


def _set(run_id: str, **kw):
    get_db().table("runs").update(kw).eq("id", run_id).execute()


KEEP = ("stage_usage", "company_ids", "manual", "limits_hit")  # counter keys that are not recomputed


def counters_for(run: dict) -> dict:
    """Live numbers for a run: counts of its companies by status, plus the saved extras (stage usage, ...)."""
    db = get_db()
    saved = run.get("counters") or {}
    ids = saved.get("company_ids")
    if ids is None:
        comps = db.table("companies").select("status").eq("run_id", run["id"]).execute().data
    else:
        comps = []
        for part in chunks(ids):
            comps += db.table("companies").select("status").in_("id", part).execute().data
    by: dict[str, int] = {}
    for c in comps:
        by[c["status"]] = by.get(c["status"], 0) + 1
    out = {"found": len(comps), "failed": by.get("failed", 0), "filtered_out": by.get("filtered_out", 0),
           "no_contact": by.get("no_contact", 0), "qualified": by.get("qualified", 0),
           "maybe": by.get("maybe", 0), "rejected": by.get("rejected", 0), "by_status": by}
    out.update({k: saved[k] for k in KEEP if k in saved})
    if ids is not None:
        out.pop("company_ids", None)  # the list can be long. The API sends it only when asked
        out["manual"] = True
    return out


def _save_counters(run_id: str):
    """Write live numbers. Keeps the extras (company_ids, stage_usage, ...) in the stored value."""
    run = _run_row(run_id)
    stored = run.get("counters") or {}
    new = counters_for(run)
    for k in KEEP:
        if k in stored:
            new[k] = stored[k]
    _set(run_id, counters=new)
    return new


async def run_campaign(run_id: str):
    db = get_db()
    run = _run_row(run_id)
    if run["status"] in ("cancelled", "done"):
        return
    campaign = db.table("campaigns").select("*").eq("id", run["campaign_id"]).single().execute().data
    campaign["filters"] = CampaignFilters.model_validate(campaign["filters"]).model_dump()  # fills new fields for old campaigns
    f = campaign["filters"]
    ids = (run.get("counters") or {}).get("company_ids")  # set for a manual "Qualify" run
    should_stop = make_should_stop(run_id)
    _set(run_id, status="running", started_at=run["started_at"] or datetime.now(timezone.utc).isoformat())
    log_event(run_id, "info", "run", f"run started ({len(ids)} companies, manual)" if ids is not None else "run started")

    stages = [
        ("discovery", lambda: discovery.run(run_id, campaign, f["maxCompaniesToScan"])),
        ("audit", lambda: audit.run(run_id, should_stop, ids)),
        ("extract", lambda: extract.run(run_id, campaign, should_stop, ids)),
        ("contacts", lambda: contacts.run(run_id, campaign, should_stop, ids)),
        ("judge", lambda: judge.run(run_id, campaign, should_stop, ids)),
        ("assets", lambda: _assets_stage(run_id, campaign, should_stop, ids)),
        ("sequences", lambda: _sequence_stage(run_id, campaign, should_stop, ids)),
    ]
    if ids is not None:
        stages = stages[1:]  # a manual run never searches for new companies
    try:
        for name, fn in stages:
            if should_stop():
                break
            _set(run_id, stage=name)
            try:
                await fn()
            except StageLimitReached as e:
                # this stage used its own limit. Do not stop the run: go on with what exists.
                log_event(run_id, "warn", name, f"{e}. Moving on to the next stage.")
                stored = _run_row(run_id).get("counters") or {}
                hits = list(stored.get("limits_hit") or [])
                hits.append({"stage": name, "what": e.what, "used": e.used, "limit": e.limit})
                _set(run_id, counters={**stored, "limits_hit": hits})
            counters = _save_counters(run_id)
            log_event(run_id, "info", name, f"stage finished. companies: {counters['found']}, qualified: {counters['qualified']}")
            if counters["qualified"] >= f["leadsWanted"]:
                log_event(run_id, "info", "run", "leadsWanted reached")
        if _run_row(run_id)["status"] == "running":
            counters = _save_counters(run_id)
            left = {k: v for k, v in counters["by_status"].items() if k in ("new", "auditing", "audited", "extracted", "contacted")}
            if left:
                log_event(run_id, "warn", "run", f"some companies did not finish because a stage limit was reached: {left}. "
                                                 "Press Continue on this run, or use Qualify on the Companies page.")
            _set(run_id, status="done", finished_at=datetime.now(timezone.utc).isoformat())
            log_event(run_id, "info", "run", "run done")
    except BudgetExceeded as e:
        _save_counters(run_id)
        _set(run_id, status="paused", error=str(e))
        log_event(run_id, "warn", "run", f"budget stop: {e}")
    except Exception as e:
        _save_counters(run_id)
        _set(run_id, status="failed", error=str(e)[:500], finished_at=datetime.now(timezone.utc).isoformat())
        log_event(run_id, "error", "run", f"run failed: {e}")


def _leads_for_run(run_id: str, ids: list[str] | None = None) -> list[dict]:
    db = get_db()
    comps = scope_todo(run_id, ["qualified"], ids)
    cids = [c["id"] for c in comps]
    out = []
    for part in chunks(cids):
        out += db.table("leads").select("*").in_("company_id", part).execute().data
    return out


async def _assets_stage(run_id, campaign, should_stop, ids=None):
    for lead in _leads_for_run(run_id, ids):
        if should_stop():
            return
        try:
            await assets.build_assets(lead, campaign, run_id)
        except BudgetExceeded:
            raise
        except Exception as e:
            log_event(run_id, "error", "assets", str(e), lead_id=lead["id"])


async def _sequence_stage(run_id, campaign, should_stop, ids=None):
    for lead in _leads_for_run(run_id, ids):
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
