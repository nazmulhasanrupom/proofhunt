"""Runs stages in order. Resumable: each stage picks up items by status."""
from datetime import datetime, timezone

from ..db import get_db
from ..schemas import CampaignFilters
from ..services.usage import STOPPED, BudgetExceeded, RunStopped, StageLimitReached, log_event
from . import assets, audit, brand_leads, contacts, discovery, extract, judge, sequences
from .kinds import IMA, kind_of
from .scope import chunks, todo as scope_todo


def _run_row(run_id: str) -> dict:
    return get_db().table("runs").select("*").eq("id", run_id).single().execute().data


def make_should_stop(run_id: str):
    def should_stop() -> bool:
        return _run_row(run_id)["status"] in ("paused", "cancelled")
    return should_stop


def _set(run_id: str, **kw):
    get_db().table("runs").update(kw).eq("id", run_id).execute()


def _claim(run: dict) -> bool:
    """Start the run. False when it was paused or cancelled after it was queued (or when the worker restarted):
    such a run must stay as it is, not jump back to 'running'."""
    now = datetime.now(timezone.utc).isoformat()
    row = get_db().table("runs").update({"status": "running", "started_at": run["started_at"] or now}).eq("id", run["id"]).in_(
        "status", ["queued", "running"]).execute().data
    return bool(row)


def _finish(run_id: str, **kw) -> bool:
    """Set how the run ended, but only while it is still running. A pause or cancel you pressed meanwhile is kept."""
    return bool(get_db().table("runs").update(kw).eq("id", run_id).eq("status", "running").execute().data)


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
    if run["status"] not in ("queued", "running"):  # cancelled, done, paused (Resume makes it 'queued' first), failed
        return
    campaign = db.table("campaigns").select("*").eq("id", run["campaign_id"]).single().execute().data
    campaign["filters"] = CampaignFilters.model_validate(campaign["filters"]).model_dump()  # fills new fields for old campaigns
    ids = (run.get("counters") or {}).get("company_ids")  # set for a manual "Qualify" run
    should_stop = make_should_stop(run_id)
    if not _claim(run):
        return
    log_event(run_id, "info", "run", f"run started ({len(ids)} companies, manual)" if ids is not None else "run started")

    try:
        reached = False
        if ids is None:
            reached = await _hunt(run_id, campaign, should_stop)  # searches too, and stops at the leads wanted. Every batch goes all the way to the emails
            stages = {}
        else:
            # a manual Qualify run: exactly the companies you picked, all stages, no search. The leads wanted do not apply
            stages = {**_work_stages(run_id, campaign, should_stop, ids), **_lead_stages(run_id, campaign, should_stop, ids)}
        for name, fn in stages.items():
            if should_stop():
                break
            await _stage(run_id, name, fn)
            counters = _save_counters(run_id)
            log_event(run_id, "info", name, f"stage finished. companies: {counters['found']}, qualified: {counters['qualified']}")
        status = _run_row(run_id)["status"]
        if status == "running":
            counters = _save_counters(run_id)
            left = {k: v for k, v in counters["by_status"].items() if k in WORK}
            if left and reached:
                log_event(run_id, "info", "run", f"stopped at the leads wanted. {sum(left.values())} companies were found but not finished: {left}. "
                                                 "To go on, raise 'Leads wanted' in the campaign and press Continue on this run.")
            elif left:
                log_event(run_id, "warn", "run", f"some companies did not finish because a stage limit was reached: {left}. "
                                                 "Press Continue on this run, or use Qualify on the Companies page.")
            if _finish(run_id, status="done", finished_at=datetime.now(timezone.utc).isoformat()):
                log_event(run_id, "info", "run", "run done")
        elif status in STOPPED:
            _save_counters(run_id)
            log_event(run_id, "info", "run", f"worker stopped: the run is {status}")
    except RunStopped as e:  # raised before a Firecrawl or AI call. The status is the one you set: leave it
        _save_counters(run_id)
        log_event(run_id, "info", "run", f"worker stopped: {e}")
    except BudgetExceeded as e:
        _save_counters(run_id)
        if _finish(run_id, status="paused", error=str(e)):
            log_event(run_id, "warn", "run", f"budget stop: {e}")
    except Exception as e:
        _save_counters(run_id)
        if _finish(run_id, status="failed", error=str(e)[:500], finished_at=datetime.now(timezone.utc).isoformat()):
            log_event(run_id, "error", "run", f"run failed: {e}")


BATCH = 5  # companies that go through every stage together, up to their emails. Only then the next 5 start. "Leads wanted" is checked after every batch
WORK = ("new", "auditing", "audited", "extracted", "contacted")  # a company in one of these still has stages to go


def _count(run_id: str, *statuses: str) -> int:
    q = get_db().table("companies").select("id", count="exact").eq("run_id", run_id)
    if statuses:
        q = q.in_("status", list(statuses))
    return q.limit(1).execute().count or 0


def _next_batch(run_id: str, seen: set[str]) -> list[str]:
    """The oldest companies of this run that still have stages to go and were not tried in this execution."""
    out, start = [], 0
    while len(out) < BATCH:
        rows = (get_db().table("companies").select("id").eq("run_id", run_id).in_("status", list(WORK))
                .order("first_seen").order("id").range(start, start + 999).execute().data)
        out += [r["id"] for r in rows if r["id"] not in seen]
        if len(rows) < 1000:
            break
        start += 1000
    return out[:BATCH]


async def _stage(run_id: str, name: str, fn) -> bool:
    """Run one stage. False when the stage used up its own limit: the run goes on without that stage."""
    _set(run_id, stage=name)
    try:
        await fn()
    except StageLimitReached as e:
        log_event(run_id, "warn", name, f"{e}. Moving on.")
        stored = _run_row(run_id).get("counters") or {}
        hits = list(stored.get("limits_hit") or [])
        hits.append({"stage": name, "what": e.what, "used": e.used, "limit": e.limit})
        _set(run_id, counters={**stored, "limits_hit": hits})
        return False
    return True


def _work_stages(run_id, campaign, should_stop, ids, stop_when=None) -> dict:
    stages = {
        "audit": lambda: audit.run(run_id, should_stop, ids),
        "extract": lambda: extract.run(run_id, campaign, should_stop, ids),
        "contacts": lambda: contacts.run(run_id, campaign, should_stop, ids),
    }
    if kind_of(campaign["profile_id"]) == IMA:  # no judge: a brand that got this far is qualified, and goes in the lead sheet
        stages["brand_leads"] = lambda: brand_leads.run(run_id, campaign, should_stop, ids, stop_when)
    else:
        stages["judge"] = lambda: judge.run(run_id, campaign, should_stop, ids, stop_when)
    return stages


def _lead_stages(run_id, campaign, should_stop, ids) -> dict:
    """The stages after the judge: report and demo, then the email drafts. Only for leads (qualified companies). IMA has none: it stops at qualified."""
    if kind_of(campaign["profile_id"]) == IMA:
        return {}
    return {
        "assets": lambda: _assets_stage(run_id, campaign, should_stop, ids),
        "sequences": lambda: _sequence_stage(run_id, campaign, should_stop, ids),
    }


async def _hunt(run_id: str, campaign: dict, should_stop) -> bool:
    """Work in batches of BATCH companies. Each batch goes through every stage, up to the email drafts, before the
    next batch starts. When nothing is left to work on, search for more. One search can find more than BATCH
    companies: they are taken BATCH at a time, in the order they were found, and no new search starts until they are done.
    Stops as soon as the leads wanted exist, so no more Firecrawl credits or AI calls go to companies you do not need.
    True when it stopped for that reason."""
    f = campaign["filters"]
    wanted, cap = f["leadsWanted"], f["maxCompaniesToScan"]
    enough = lambda: _count(run_id, "qualified") >= wanted  # noqa: E731
    seen: set[str] = set()   # each company is tried once per execution: a stage limit or a rate limit cannot make us loop
    skip: set[str] = set()   # stages that used their own limit
    n = 0
    for name, fn in _lead_stages(run_id, campaign, should_stop, None).items():  # leads of an earlier, stopped execution: finish them first
        if should_stop():
            return False
        if not await _stage(run_id, name, fn):
            skip.add(name)
    while not should_stop():
        if enough():
            log_event(run_id, "info", "run", f"leads wanted reached ({wanted}). No more companies are searched or read")
            return True
        batch = _next_batch(run_id, seen)
        if not batch:  # everything found is handled: search for more
            found = _count(run_id)
            if "discovery" in skip or found >= cap:
                return False
            if not await _stage(run_id, "discovery", lambda: discovery.run(run_id, campaign, cap, should_stop, found + BATCH)):
                skip.add("discovery")
            if _count(run_id) == found:  # no new companies: the searches are used up
                return False
            continue
        seen.update(batch)
        n += 1
        stages = {**_work_stages(run_id, campaign, should_stop, batch, enough), **_lead_stages(run_id, campaign, should_stop, batch)}
        for name, fn in stages.items():
            if should_stop():
                return False
            if name not in skip and not await _stage(run_id, name, fn):
                skip.add(name)
        c = _save_counters(run_id)
        log_event(run_id, "info", "run", f"batch {n} done ({len(batch)} companies, up to the emails). Found {c['found']}, qualified {c['qualified']} of {wanted} wanted")
    return False


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
