from arq import cron
from arq.connections import RedisSettings

from .config import settings
from .db import get_db
from .pipeline.orchestrator import run_campaign
from .sending import scheduler, tracker


async def ping(ctx):
    return "pong"


async def run_campaign_task(ctx, run_id: str):
    """One job per run at a time. A second job for the same run is skipped."""
    redis = ctx["redis"]
    key = f"lock:run:{run_id}"
    if not await redis.set(key, "1", nx=True, ex=6 * 3600):
        return "skipped: already running"
    try:
        await run_campaign(run_id)
    finally:
        await redis.delete(key)


async def _locked(ctx, name: str, fn, ttl: int):
    """Cron jobs never overlap with themselves: a slow tick makes the next one skip."""
    redis = ctx["redis"]
    if not await redis.set(f"lock:{name}", "1", nx=True, ex=ttl):
        return "skipped: still running"
    try:
        return await fn()
    finally:
        await redis.delete(f"lock:{name}")


async def send_tick(ctx):
    return await _locked(ctx, "send", scheduler.tick, 300)


async def reply_tick(ctx):
    return await _locked(ctx, "replies", tracker.check_replies, 600)


async def bounce_tick(ctx):
    return await _locked(ctx, "bounces", tracker.check_bounces, 600)


async def on_startup(ctx):
    """If the worker died mid-run, the run still says 'running' and its lock blocks Resume for hours.
    At start nothing can be running yet, so: clear the locks and pause those runs. The user presses Resume."""
    redis = ctx["redis"]
    async for k in redis.scan_iter("lock:*"):
        await redis.delete(k)
    if settings.supabase_url and settings.supabase_key:
        try:
            get_db().table("runs").update({"status": "paused", "error": "Worker restarted. Press Resume to continue."}).eq("status", "running").execute()
        except Exception as e:  # DB down at boot must not stop the worker
            print(f"startup cleanup failed: {type(e).__name__}")


class WorkerSettings:
    on_startup = on_startup
    functions = [ping, run_campaign_task]
    cron_jobs = [
        cron(send_tick, minute=set(range(0, 60, 2)), second=0, timeout=300),
        cron(reply_tick, minute={0, 10, 20, 30, 40, 50}, second=30, timeout=600),
        cron(bounce_tick, minute={5, 20, 35, 50}, second=30, timeout=600),
    ]
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    max_jobs = 2
    job_timeout = 6 * 3600
