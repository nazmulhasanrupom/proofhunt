"""Credit + token accounting and budget guards."""
import threading

from ..config import settings
from ..db import get_db


_bump_lock = threading.Lock()


class BudgetExceeded(Exception):
    pass


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
        run = get_db().table("runs").select("credits_used,campaign_id").eq("id", run_id).single().execute().data
        camp = get_db().table("campaigns").select("filters").eq("id", run["campaign_id"]).single().execute().data
        max_run = camp["filters"].get("maxCreditsPerRun")
        if max_run and (run["credits_used"] or 0) + cost > max_run:
            raise BudgetExceeded(f"maxCreditsPerRun ({max_run}) reached")


def check_llm_budget():
    limit = settings.dev_llm_call_limit
    if limit and total_usage()["calls"] >= limit:
        raise BudgetExceeded(f"DEV_LLM_CALL_LIMIT ({limit}) reached")


def bump_run(run_id: str | None, credits=0, calls=0, in_tokens=0, out_tokens=0):
    if not run_id:
        return
    with _bump_lock:
        _bump_run(run_id, credits, calls, in_tokens, out_tokens)


def _bump_run(run_id, credits, calls, in_tokens, out_tokens):
    db = get_db()
    r = db.table("runs").select("credits_used,llm_calls,llm_input_tokens,llm_output_tokens").eq("id", run_id).single().execute().data
    db.table("runs").update({
        "credits_used": (r["credits_used"] or 0) + credits,
        "llm_calls": (r["llm_calls"] or 0) + calls,
        "llm_input_tokens": (r["llm_input_tokens"] or 0) + in_tokens,
        "llm_output_tokens": (r["llm_output_tokens"] or 0) + out_tokens,
    }).eq("id", run_id).execute()


def log_event(run_id, level, stage, message, data=None, lead_id=None):
    try:
        get_db().table("events").insert({
            "run_id": run_id, "lead_id": lead_id, "level": level,
            "stage": stage, "message": message, "data": data,
        }).execute()
    except Exception:
        pass
