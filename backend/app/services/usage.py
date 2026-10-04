"""Credit + token accounting and budget guards."""
import threading

from ..config import settings
from ..db import get_db


_bump_lock = threading.Lock()


class BudgetExceeded(Exception):
    """A hard stop. The run pauses."""


class RunStopped(BudgetExceeded):
    """You paused or cancelled the run. Raised before any Firecrawl or AI call, so nothing is spent after a stop,
    whatever stage the run is in. It is a BudgetExceeded on purpose: every stage already knows to leave its company
    for the next time and to pass this up. Only the run itself tells the two apart (it keeps the status you set)."""


STOPPED = ("paused", "cancelled")


class StageLimitReached(BudgetExceeded):
    """One stage used up its own limit. The run does NOT pause: it moves on to the next stage."""

    def __init__(self, stage: str, what: str, used: int, limit: int):
        self.stage, self.what, self.used, self.limit = stage, what, used, limit
        super().__init__(f"{stage}: {what} limit reached ({used} of {limit})")


STAGE_DEFAULTS = {"credits": 500, "llm_calls": 300}


def _stage_state(run_id: str) -> tuple[str | None, dict, dict]:
    """(stage, usage of that stage so far, campaign filters)"""
    run = get_db().table("runs").select("stage,counters,campaign_id,status").eq("id", run_id).single().execute().data
    if run.get("status") in STOPPED:
        raise RunStopped(f"the run is {run['status']}")
    camp = get_db().table("campaigns").select("filters").eq("id", run["campaign_id"]).single().execute().data
    stage = run.get("stage")
    used = ((run.get("counters") or {}).get("stage_usage") or {}).get(stage) or {}
    return stage, used, camp["filters"] or {}


def check_stage_limit(run_id: str | None, what: str, cost: int):
    """what: 'credits' or 'llm_calls'. Raises StageLimitReached when this stage would pass its own limit."""
    if not run_id:
        return
    stage, used, f = _stage_state(run_id)
    if not stage:
        return
    key = "maxCreditsPerStage" if what == "credits" else "maxLlmCallsPerStage"
    limit = f.get(key) or STAGE_DEFAULTS[what]
    now = used.get(what, 0)
    if now + cost > limit:
        raise StageLimitReached(stage, "Firecrawl credit" if what == "credits" else "AI call", now, limit)


def check_run_active(run_id: str | None):
    """Raises RunStopped when the run was paused or cancelled. For waits and retries that do not pass the checks above."""
    if not run_id:
        return
    row = get_db().table("runs").select("status").eq("id", run_id).execute().data
    if row and row[0]["status"] in STOPPED:
        raise RunStopped(f"the run is {row[0]['status']}")


def add_usage(credits=0, calls=0, in_tokens=0, out_tokens=0, emails=0):
    get_db().rpc("add_usage", {
        "p_credits": credits, "p_calls": calls,
        "p_in": in_tokens, "p_out": out_tokens, "p_emails": emails,
    }).execute()


def total_usage() -> dict:
    """Sum over all days. The DEV limits cover the whole build, not one day."""
    rows = get_db().table("usage_daily").select("firecrawl_credits,llm_calls").execute().data or []
    return {
        "credits": sum(r["firecrawl_credits"] or 0 for r in rows),
        "calls": sum(r["llm_calls"] or 0 for r in rows),
    }


def check_credit_budget(cost: int, run_id: str | None = None):
    limit = settings.dev_firecrawl_credit_limit
    if limit and total_usage()["credits"] + cost > limit:
        raise BudgetExceeded(f"DEV_FIRECRAWL_CREDIT_LIMIT ({limit}) would be exceeded")
    if run_id:
        check_stage_limit(run_id, "credits", cost)
        run = get_db().table("runs").select("credits_used,campaign_id").eq("id", run_id).single().execute().data
        camp = get_db().table("campaigns").select("filters").eq("id", run["campaign_id"]).single().execute().data
        max_run = camp["filters"].get("maxCreditsPerRun")
        if max_run and (run["credits_used"] or 0) + cost > max_run:
            raise BudgetExceeded(f"maxCreditsPerRun ({max_run}) reached")


def check_llm_budget(run_id: str | None = None):
    limit = settings.dev_llm_call_limit
    if limit and total_usage()["calls"] >= limit:
        raise BudgetExceeded(f"DEV_LLM_CALL_LIMIT ({limit}) reached")
    check_stage_limit(run_id, "llm_calls", 1)


def bump_run(run_id: str | None, credits=0, calls=0, in_tokens=0, out_tokens=0):
    if not run_id:
        return
    with _bump_lock:
        _bump_run(run_id, credits, calls, in_tokens, out_tokens)


def _bump_run(run_id, credits, calls, in_tokens, out_tokens):
    db = get_db()
    r = db.table("runs").select("credits_used,llm_calls,llm_input_tokens,llm_output_tokens,stage,counters").eq("id", run_id).single().execute().data
    counters = dict(r.get("counters") or {})
    stage = r.get("stage")
    if stage:  # what each stage has used, so each stage can have its own limit
        su = dict(counters.get("stage_usage") or {})
        cur = dict(su.get(stage) or {})
        cur["credits"] = cur.get("credits", 0) + credits
        cur["llm_calls"] = cur.get("llm_calls", 0) + calls
        su[stage] = cur
        counters["stage_usage"] = su
    db.table("runs").update({
        "credits_used": (r["credits_used"] or 0) + credits,
        "llm_calls": (r["llm_calls"] or 0) + calls,
        "llm_input_tokens": (r["llm_input_tokens"] or 0) + in_tokens,
        "llm_output_tokens": (r["llm_output_tokens"] or 0) + out_tokens,
        "counters": counters,
    }).eq("id", run_id).execute()


_profile_of: dict[str, str] = {}  # run or lead id -> profile id. Neither ever changes profile, so this never goes stale


def _profile_for(run_id: str | None, lead_id: str | None) -> str | None:
    for table, key in (("runs", run_id), ("leads", lead_id)):
        if not key:
            continue
        if key in _profile_of:
            return _profile_of[key]
        rows = get_db().table(table).select("profile_id").eq("id", key).execute().data
        if rows and rows[0].get("profile_id"):
            if len(_profile_of) > 5000:
                _profile_of.clear()
            _profile_of[key] = rows[0]["profile_id"]
            return rows[0]["profile_id"]
    return None


def log_event(run_id, level, stage, message, data=None, lead_id=None, profile_id=None):
    """profile_id is found from the run or the lead when not given. No profile at all = a message for the whole app."""
    try:
        get_db().table("events").insert({
            "run_id": run_id, "lead_id": lead_id, "level": level, "profile_id": profile_id or _profile_for(run_id, lead_id),
            "stage": stage, "message": message, "data": data,
        }).execute()
    except Exception:
        pass
