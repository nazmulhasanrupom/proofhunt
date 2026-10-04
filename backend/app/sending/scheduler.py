"""Sending engine. One cron tick sends at most ONE email.

Pure helpers (cap, gap, window, business days) come first so tests can call them without a DB.
"""
import asyncio
import random
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from ..config import settings as env
from ..db import get_db
from ..services import gmail
from ..services.usage import add_usage, log_event

DRY_ID = "dry-run"
DEFAULT_TZ = "America/New_York"
BOUNCE_LIMIT = 3  # more than this many bounces in 24 h pauses sending
STUCK_AFTER = timedelta(minutes=10)
RETRY_AFTER = timedelta(minutes=30)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def parse_dt(v: str | None) -> datetime | None:
    return datetime.fromisoformat(v.replace("Z", "+00:00")) if v else None


def parse_t(v: str | time) -> time:
    return v if isinstance(v, time) else time.fromisoformat(v)


# ---- pure helpers --------------------------------------------------------

def tz_of(name: str | None) -> ZoneInfo:
    try:
        return ZoneInfo(name or DEFAULT_TZ)
    except Exception:
        return ZoneInfo(DEFAULT_TZ)


def warmup_cap(daily_cap: int, warmup: bool, first_real_send: datetime | None, now: datetime) -> int:
    """With warm-up: min(cap, 10 + 5 x full weeks since the first real send). Before any real send: 10."""
    cap = max(1, min(50, daily_cap or 20))
    if not warmup:
        return cap
    weeks = 0 if first_real_send is None else max(0, (now - first_real_send).days // 7)
    return min(cap, 10 + 5 * weeks)


def gap_seconds(last_sent: datetime, min_s: int, max_s: int) -> float:
    """Random gap in [min, max]. Seeded by the last send time, so every tick agrees on the same value."""
    return random.Random(last_sent.isoformat()).uniform(min_s, max(min_s, max_s))


def is_business_day(d: date) -> bool:
    return d.weekday() < 5


def add_business_days(d: date, n: int) -> date:
    while n > 0:
        d += timedelta(days=1)
        if is_business_day(d):
            n -= 1
    return d


def in_window(at: datetime, tz_name: str | None, start: time, end: time) -> bool:
    local = at.astimezone(tz_of(tz_name))
    return is_business_day(local.date()) and start <= local.time() < end


def next_slot(after: datetime, tz_name: str | None, start: time, end: time, rng: random.Random) -> datetime:
    """Next window start (Mon-Fri) after `after`, plus 0-60 random minutes (kept inside the window)."""
    tz = tz_of(tz_name)
    local = after.astimezone(tz)
    day = local.date()
    if not (is_business_day(day) and local.time() < start):
        day = add_business_days(day, 1)
    span = (end.hour * 60 + end.minute) - (start.hour * 60 + start.minute)
    offset = rng.randint(0, max(0, min(60, span - 1)))
    at = datetime.combine(day, start, tzinfo=tz) + timedelta(minutes=offset)
    return at.astimezone(timezone.utc)


def place_in_window(at: datetime, tz_name: str | None, start: time, end: time, rng: random.Random) -> datetime:
    return at if in_window(at, tz_name, start, end) else next_slot(at, tz_name, start, end, rng)


def followup_time(sent_at: datetime, business_days: int, tz_name: str | None, start: time, end: time,
                  rng: random.Random) -> datetime:
    """sent_at + N business days (same local clock time), moved into the send window."""
    tz = tz_of(tz_name)
    local = sent_at.astimezone(tz)
    day = add_business_days(local.date(), business_days)
    at = datetime.combine(day, local.time(), tzinfo=tz).astimezone(timezone.utc)
    return place_in_window(at, tz_name, start, end, rng)


def bounce_pause_until(bounced_at: list[datetime], now: datetime) -> datetime | None:
    """More than BOUNCE_LIMIT bounces in 24 h: pause until the oldest one that counts is 24 h old."""
    recent = sorted((t for t in bounced_at if now - t < timedelta(hours=24)), reverse=True)
    if len(recent) > BOUNCE_LIMIT:
        return recent[BOUNCE_LIMIT] + timedelta(hours=24)
    return None


# ---- DB helpers ----------------------------------------------------------

def _settings() -> dict:
    return (get_db().table("settings").select("*").eq("id", 1).execute().data or [{}])[0]


def _mode_filter(q):
    """Dry-run sends and real sends are counted apart, so a test never eats the real cap."""
    return q.eq("gmail_message_id", DRY_ID) if env.dry_run else q.neq("gmail_message_id", DRY_ID)


def sent_since(since: datetime) -> int:
    q = get_db().table("messages").select("id", count="exact").eq("status", "sent").gte("sent_at", iso(since))
    return _mode_filter(q).execute().count or 0


def last_sent_at() -> datetime | None:
    q = get_db().table("messages").select("sent_at").eq("status", "sent")
    r = _mode_filter(q).order("sent_at", desc=True).limit(1).execute().data
    return parse_dt(r[0]["sent_at"]) if r else None


def first_real_send() -> datetime | None:
    r = (get_db().table("messages").select("sent_at").eq("status", "sent").neq("gmail_message_id", DRY_ID)
         .order("sent_at").limit(1).execute().data)
    return parse_dt(r[0]["sent_at"]) if r else None


def bounce_pause(now: datetime) -> datetime | None:
    since = iso(now - timedelta(hours=24))
    rows = get_db().table("leads").select("updated_at").eq("stage", "bounced").gte("updated_at", since).execute().data
    return bounce_pause_until([parse_dt(r["updated_at"]) for r in rows], now)


def sender_name(st: dict, profile_id: str | None = None) -> str:
    """Settings first. Else the name in the CV of this profile (no profile given: the first CV that has a name)."""
    if st.get("sender_name"):
        return st["sender_name"]
    q = get_db().table("profiles").select("parsed")
    if profile_id:
        q = q.eq("id", profile_id)
    for p in q.order("created_at").execute().data:
        if (p["parsed"] or {}).get("name"):
            return p["parsed"]["name"]
    return ""


def blockers(st: dict, now: datetime | None = None) -> list[str]:
    """Reasons the engine will not send right now (for the UI banner and the tick)."""
    now = now or utcnow()
    out = []
    if not env.dry_run:
        if not st.get("gmail_refresh_token_enc"):
            out.append("Reconnect Gmail" if st.get("gmail_address") else "Gmail is not connected")
        if not (st.get("postal_address") or "").strip() or not sender_name(st):
            out.append("Set sender name and postal address in Settings")
    until = bounce_pause(now)
    if until:
        out.append(f"Paused until {until:%Y-%m-%d %H:%M} UTC: more than {BOUNCE_LIMIT} bounces in 24 hours")
    return out


def status() -> dict:
    st = _settings()
    now = utcnow()
    cap = warmup_cap(st.get("daily_send_cap"), st.get("warmup_enabled", True), first_real_send(), now)
    return {
        "dry_run": env.dry_run, "gmail_connected": bool(st.get("gmail_refresh_token_enc")),
        "gmail_address": st.get("gmail_address"), "sender_name": sender_name(st),
        "blockers": blockers(st, now), "cap": cap, "sent_24h": sent_since(now - timedelta(hours=24)),
    }


# ---- scheduling ----------------------------------------------------------

def _window(st: dict) -> tuple[time, time]:
    return parse_t(st.get("send_window_start") or "09:00"), parse_t(st.get("send_window_end") or "16:30")


def schedule_next(db, lead_id: str, prev: dict, tz_name: str | None, st: dict):
    """Set scheduled_at of the step after `prev` (which must be sent)."""
    nxt = db.table("messages").select("id,status").eq("lead_id", lead_id).eq("step", prev["step"] + 1).execute().data
    if not nxt or nxt[0]["status"] not in ("approved", "scheduled"):
        return
    days = st.get("followup_days") or [3, 4, 7]
    n = days[min(prev["step"], len(days) - 1)]
    start, end = _window(st)
    at = followup_time(parse_dt(prev["sent_at"]), n, tz_name, start, end, random.Random())
    db.table("messages").update({"status": "scheduled", "scheduled_at": iso(at)}).eq("id", nxt[0]["id"]).execute()


def _dnc_values() -> set[str]:
    return {r["value"].lower() for r in get_db().table("do_not_contact").select("value").execute().data}


def is_blocked(email: str, dnc: set[str]) -> bool:
    e = email.lower()
    return e in dnc or e.split("@")[-1] in dnc


def _fail_stuck(db, now: datetime):
    rows = db.table("messages").select("id,sent_at,lead_id").eq("status", "sending").execute().data
    for r in rows:
        at = parse_dt(r["sent_at"])
        if at is None or now - at > STUCK_AFTER:
            db.table("messages").update({
                "status": "failed", "sent_at": None,
                "error": "stuck while sending. Check the Gmail Sent folder before you retry.",
            }).eq("id", r["id"]).execute()
            log_event(None, "error", "send", "message stuck in 'sending', marked failed", lead_id=r["lead_id"])


# ---- the tick ------------------------------------------------------------

async def tick() -> str:
    """Send at most one due message. Returns a short note for the worker log."""
    db = get_db()
    now = utcnow()
    st = _settings()
    await asyncio.to_thread(_fail_stuck, db, now)

    why = blockers(st, now)
    if why:
        return "idle: " + why[0]

    cap = warmup_cap(st.get("daily_send_cap"), st.get("warmup_enabled", True), first_real_send(), now)
    if sent_since(now - timedelta(hours=24)) >= cap:
        return f"idle: daily cap {cap} reached"
    last = last_sent_at()
    if last and (now - last).total_seconds() < gap_seconds(last, st.get("min_gap_seconds") or 180, st.get("max_gap_seconds") or 540):
        return "idle: waiting for the gap"

    cands = db.table("messages").select("*").in_("status", ["approved", "scheduled"]).limit(1000).execute().data
    cands = [m for m in cands if not m["scheduled_at"] or parse_dt(m["scheduled_at"]) <= now]
    cands.sort(key=lambda m: (parse_dt(m["scheduled_at"]) or now, m["step"]))
    if not cands:
        return "idle: nothing due"

    start, end = _window(st)
    dnc = _dnc_values()
    leads: dict[str, dict] = {}
    for m in cands:
        lid = m["lead_id"]
        if lid not in leads:
            ld = db.table("leads").select("*, people(email)").eq("id", lid).execute().data
            leads[lid] = ld[0] if ld else {}
        lead = leads[lid]
        if lead.get("stage") != "in_sequence":
            continue
        tz_name = lead.get("timezone")
        rng = random.Random()

        siblings = db.table("messages").select("*").eq("lead_id", lid).execute().data
        by_step = {s["step"]: s for s in siblings}
        if m["step"] > 0:
            prev = by_step.get(m["step"] - 1)
            if not prev or prev["status"] != "sent":
                continue
            if not m["scheduled_at"]:  # step was never scheduled (self-heal), do not send at once
                schedule_next(db, lid, prev, tz_name, st)
                continue

        if not in_window(now, tz_name, start, end):
            at = next_slot(now, tz_name, start, end, rng)
            db.table("messages").update({"status": "scheduled", "scheduled_at": iso(at)}).eq("id", m["id"]).execute()
            continue

        email = ((lead.get("people") or {}).get("email") or "").strip()
        if not email:
            db.table("messages").update({"status": "failed", "error": "lead has no email"}).eq("id", m["id"]).execute()
            continue
        if is_blocked(email, dnc):
            db.table("messages").update({"status": "cancelled"}).eq("lead_id", lid).in_(
                "status", ["draft", "approved", "scheduled"]).execute()
            db.table("leads").update({"stage": "lost", "notes": "on the do-not-contact list", "updated_at": "now"}).eq("id", lid).execute()
            log_event(None, "warn", "send", f"{email} is on the do-not-contact list, sequence cancelled", lead_id=lid)
            continue

        return await _send_one(db, st, m, lead, email, by_step, now)
    return "idle: nothing sendable now"


async def _send_one(db, st: dict, m: dict, lead: dict, email: str, by_step: dict, now: datetime) -> str:
    # claim the row first, so two ticks can never send the same message
    claimed = db.table("messages").update({"status": "sending", "sent_at": iso(now)}).eq("id", m["id"]).in_(
        "status", ["approved", "scheduled"]).execute().data
    if not claimed:
        return "idle: message already taken"
    lid, step = lead["id"], m["step"]
    root = by_step.get(0) or {}

    def revert(status: str, error: str | None = None, at: datetime | None = None):
        db.table("messages").update({
            "status": status, "sent_at": None, "error": error, **({"scheduled_at": iso(at)} if at else {}),
        }).eq("id", m["id"]).execute()

    try:
        if env.dry_run:
            ids = {"gmail_message_id": DRY_ID, "gmail_thread_id": None, "rfc_message_id": f"<dry-run-{m['id']}@localhost>"}
            gmail.build_message(sender_name(st, lead.get("profile_id")), st.get("gmail_address") or "dry-run@localhost", email,
                                m["subject"], m["body"])  # build it anyway: catches bad headers
        else:
            if step > 0 and (not root.get("gmail_thread_id") or root.get("gmail_message_id") == DRY_ID):
                revert("failed", "step 0 was not sent through Gmail, so there is no thread to reply in")
                return "failed: no thread"
            msg = gmail.build_message(sender_name(st, lead.get("profile_id")), st["gmail_address"], email, m["subject"], m["body"],
                                      root.get("rfc_message_id") if step > 0 else None)
            ids = await asyncio.to_thread(gmail.send, msg, root.get("gmail_thread_id") if step > 0 else None)
    except gmail.GmailAuthError as e:
        revert("approved")
        log_event(None, "error", "send", f"Gmail login failed: {e}", lead_id=lid)
        return "idle: Gmail needs reconnecting"
    except gmail.GmailTransient as e:
        revert("scheduled", None, now + RETRY_AFTER)
        log_event(None, "warn", "send", f"Gmail busy, retry in 30 min: {e}", lead_id=lid)
        return "idle: Gmail busy"
    except Exception as e:
        revert("failed", str(e)[:300])
        log_event(None, "error", "send", f"send failed: {e}", lead_id=lid)
        return f"failed: {type(e).__name__}"

    sent_at = utcnow()
    done = {**ids, "status": "sent", "sent_at": iso(sent_at), "error": None}
    db.table("messages").update(done).eq("id", m["id"]).execute()
    if not env.dry_run:
        await asyncio.to_thread(add_usage, 0, 0, 0, 0, 1)
    schedule_next(db, lid, {**m, **done}, lead.get("timezone"), st)
    tag = " (dry run)" if env.dry_run else ""
    log_event(None, "info", "send", f"step {step} sent to {email}{tag}", lead_id=lid)
    return f"sent step {step} to {email}{tag}"
