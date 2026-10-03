"""Reply and bounce tracking. Reads Gmail only. Works with DRY_RUN on or off.

Pure parsing helpers come first so tests can run them on recorded data.
"""
import asyncio
import base64
import random
import re
from datetime import datetime, timedelta, timezone
from email.utils import parseaddr

from pydantic import BaseModel

from ..db import get_db
from ..services import gmail, llm
from ..services.usage import BudgetExceeded, log_event
from . import scheduler as sch

CLASSES = {"interested", "not_now", "not_interested", "unsubscribe", "out_of_office", "other"}
DAEMONS = {"mailer-daemon", "postmaster"}
OPTOUT_FIRST = {"no", "stop", "unsubscribe", "remove"}
NOT_OPTOUT = re.compile(r"\bno\s+(problem|worries|worry)\b", re.I)
ATTRIBUTION = re.compile(r"^[ \t]*On\s.{5,250}?wrote:", re.I | re.M | re.S)
OPTOUT_PHRASE = re.compile(r"\b(unsubscribe|remove me|take me off|stop (emailing|sending|contacting))\b", re.I)
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")


# ---- pure helpers --------------------------------------------------------

def addr_of(from_header: str | None) -> str:
    return parseaddr(from_header or "")[1].lower()


def is_daemon(addr: str) -> bool:
    return addr.split("@")[0] in DAEMONS


def find_new_replies(thread: dict, my_email: str, known_ids: set[str]) -> list[dict]:
    """Messages in the thread that someone else wrote and that we have not saved yet."""
    out = []
    for m in thread.get("messages", []):
        if m["id"] in known_ids:
            continue
        labels = set(m.get("labelIds", []))
        if "SENT" in labels or "DRAFT" in labels:
            continue
        frm = addr_of(gmail.header(m, "From"))
        if not frm or frm == my_email.lower() or is_daemon(frm):
            continue
        out.append(m)
    return out


def _b64(data: str) -> str:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4)).decode("utf-8", "replace")


def extract_text(msg: dict) -> str:
    """Plain text of a full Gmail message. Falls back to HTML with the tags removed."""
    plain, html = [], []

    def walk(part: dict):
        mime, data = part.get("mimeType", ""), (part.get("body") or {}).get("data")
        if data and mime == "text/plain":
            plain.append(_b64(data))
        elif data and mime == "text/html":
            html.append(_b64(data))
        for p in part.get("parts", []) or []:
            walk(p)

    walk(msg.get("payload") or {})
    if plain:
        return "\n".join(plain).strip()
    text = re.sub(r"<(script|style).*?</\1>", " ", "\n".join(html), flags=re.S | re.I)
    text = re.sub(r"<br\s*/?>|</p>|</div>", "\n", text, flags=re.I)
    return re.sub(r"[ \t]+", " ", re.sub(r"<[^>]+>", " ", text)).strip()


def clean_reply(text: str) -> str:
    """The new words of a reply: no quoted history."""
    m = ATTRIBUTION.search(text)  # "On Mon, ... wrote:" can wrap over two lines
    if m:
        text = text[: m.start()]
    lines = []
    for ln in text.splitlines():
        s = ln.strip()
        if re.match(r"^(-+\s*original message\s*-+|from:\s.+)$", s, re.I):
            break
        if s.startswith(">") or re.match(r"^sent from my ", s, re.I):
            continue
        lines.append(ln)
    return "\n".join(lines).strip()


def looks_like_optout(clean: str) -> bool:
    """A clear opt-out phrase, or a very short reply that starts with no / stop / unsubscribe / remove."""
    if OPTOUT_PHRASE.search(clean):
        return True
    if NOT_OPTOUT.search(clean):
        return False
    words = [w for w in re.findall(r"[a-z']+", clean.lower()) if w not in ("please", "pls")]
    return 0 < len(words) <= 4 and words[0] in OPTOUT_FIRST


def is_autoreply(msg: dict) -> bool:
    v = (gmail.header(msg, "Auto-Submitted") or "").lower()
    return bool(v) and v != "no"


def parse_bounce(subject: str, text: str, known: set[str]) -> tuple[str | None, bool]:
    """(failed address, is_hard_bounce). Only an address we really mailed can match."""
    if "delay" in subject.lower():
        return None, False
    has5, has4 = re.search(r"Status:\s*5\.\d", text), re.search(r"Status:\s*4\.\d", text)
    hard = bool(has5) or not has4
    found = [e.lower() for e in EMAIL_RE.findall(text)]
    for e in found:
        if e in known:
            return e, hard
    return None, hard


# ---- LLM classification --------------------------------------------------

class _Cls(BaseModel):
    classification: str = "other"


async def classify(clean: str, msg: dict) -> str | None:
    """Rules first (free). The LLM only sees what the rules cannot decide."""
    if is_autoreply(msg):
        return "out_of_office"
    if looks_like_optout(clean):
        return "unsubscribe"
    try:
        out = await llm.complete_json("reply_classify", "fast", llm.load_prompt("reply_classify"),
                                      clean[:1500], _Cls, None, 0.1)
    except BudgetExceeded:
        raise
    except Exception:
        return None
    c = (out["classification"] or "").strip().lower()
    return c if c in CLASSES else "other"


# ---- replies -------------------------------------------------------------

def _cancel_pending(db, lead_id: str) -> list[dict]:
    rows = db.table("messages").select("id,step,status").eq("lead_id", lead_id).in_(
        "status", ["draft", "approved", "scheduled"]).execute().data
    if rows:
        db.table("messages").update({"status": "cancelled"}).in_("id", [r["id"] for r in rows]).execute()
    return rows


def _add_dnc(db, email: str, reason: str):
    if email:
        db.table("do_not_contact").upsert({"value": email.lower(), "kind": "email", "reason": reason},
                                          on_conflict="value", ignore_duplicates=True).execute()


def _set_stage(db, lead_id: str, stage: str):
    db.table("leads").update({"stage": stage, "updated_at": "now"}).eq("id", lead_id).execute()


def _restore_after_ooo(db, lead: dict, cancelled: list[dict], st: dict, now: datetime):
    """Out of office: undo the cancel and push the next step back by 7 days."""
    if not cancelled:
        return
    for r in cancelled:
        db.table("messages").update({"status": r["status"]}).eq("id", r["id"]).execute()
    nxt = min(cancelled, key=lambda r: r["step"])
    start, end = sch._window(st)
    at = sch.place_in_window(now + timedelta(days=7), lead.get("timezone"), start, end, random.Random())
    db.table("messages").update({"status": "scheduled", "scheduled_at": sch.iso(at)}).eq("id", nxt["id"]).execute()
    _set_stage(db, lead["id"], "in_sequence")


async def _handle_reply(db, lead: dict, person_email: str, st: dict, m: dict):
    full = await asyncio.to_thread(gmail.get_message, m["id"])
    text = extract_text(full)
    clean = clean_reply(text) or text
    frm = addr_of(gmail.header(full, "From"))
    received = datetime.fromtimestamp(int(full.get("internalDate", 0)) / 1000, tz=timezone.utc)
    row = db.table("replies").upsert({
        "lead_id": lead["id"], "gmail_message_id": m["id"], "from_email": frm,
        "received_at": sch.iso(received), "snippet": (full.get("snippet") or clean)[:200], "body": text[:20000],
    }, on_conflict="gmail_message_id", ignore_duplicates=True).execute().data
    if not row:
        return  # already saved by another run

    # stop first, decide after: if the LLM fails the sequence stays stopped
    cancelled = _cancel_pending(db, lead["id"])
    _set_stage(db, lead["id"], "replied")

    try:
        cls = await classify(clean, full)
    except BudgetExceeded as e:
        cls = None
        log_event(None, "warn", "reply", f"reply not classified: {e}", lead_id=lead["id"])
    if cls:
        db.table("replies").update({"classification": cls}).eq("id", row[0]["id"]).execute()

    if cls in ("unsubscribe", "not_interested"):
        _set_stage(db, lead["id"], "unsubscribed")
        _add_dnc(db, frm, f"reply: {cls}")
        _add_dnc(db, person_email, f"reply: {cls}")
    elif cls == "out_of_office":
        _restore_after_ooo(db, lead, cancelled, st, sch.utcnow())
    log_event(None, "info", "reply", f"reply from {frm}: {cls or 'not classified'}", lead_id=lead["id"])


async def check_replies() -> str:
    db = get_db()
    st = sch._settings()
    if not st.get("gmail_refresh_token_enc") or not st.get("gmail_address"):
        return "idle: Gmail not connected"
    since = sch.iso(sch.utcnow() - timedelta(days=30))
    sent = db.table("messages").select("lead_id,gmail_thread_id").eq("status", "sent").neq(
        "gmail_message_id", sch.DRY_ID).not_.is_("gmail_thread_id", "null").gte("sent_at", since).execute().data
    threads = {}
    for r in sent:
        threads.setdefault(r["lead_id"], r["gmail_thread_id"])  # all steps share the thread of step 0
    if not threads:
        return "idle: no sent threads"

    leads = db.table("leads").select("*, people(email)").in_("id", list(threads)).eq("stage", "in_sequence").execute().data
    found = 0
    for lead in leads:
        try:
            thread = await asyncio.to_thread(gmail.get_thread, threads[lead["id"]])
            known = {r["gmail_message_id"] for r in db.table("replies").select("gmail_message_id").eq("lead_id", lead["id"]).execute().data}
            new = find_new_replies(thread, st["gmail_address"], known)
            if new:
                await _handle_reply(db, lead, (lead.get("people") or {}).get("email") or "", st, new[0])
                found += 1
        except gmail.GmailAuthError:
            log_event(None, "error", "reply", "Gmail login failed while checking replies")
            return "stopped: Gmail needs reconnecting"
        except gmail.GmailTransient as e:
            log_event(None, "warn", "reply", f"Gmail busy while checking replies: {e}")
            return "stopped: Gmail busy"
        except Exception as e:
            log_event(None, "error", "reply", f"reply check failed: {e}", lead_id=lead["id"])
    return f"checked {len(leads)} leads, {found} new replies"


# ---- bounces -------------------------------------------------------------

async def check_bounces() -> str:
    db = get_db()
    st = sch._settings()
    if not st.get("gmail_refresh_token_enc"):
        return "idle: Gmail not connected"
    leads = db.table("leads").select("*, people(email)").eq("stage", "in_sequence").execute().data
    by_email = {((l.get("people") or {}).get("email") or "").lower(): l for l in leads}
    by_email.pop("", None)
    if not by_email:
        return "idle: no active leads"
    handled = 0
    try:
        ids = await asyncio.to_thread(gmail.search_ids, "from:mailer-daemon newer_than:3d")
        for mid in ids:
            full = await asyncio.to_thread(gmail.get_message, mid)
            subject = gmail.header(full, "Subject") or ""
            text = extract_text(full)
            failed = gmail.header(full, "X-Failed-Recipients")
            known = set(by_email)
            email, hard = parse_bounce(subject, (failed or "") + "\n" + text, known)
            if not email or not hard or email not in by_email:
                continue
            lead = by_email.pop(email)  # one action per lead
            _cancel_pending(db, lead["id"])
            _set_stage(db, lead["id"], "bounced")
            _add_dnc(db, email, "bounce")
            log_event(None, "warn", "bounce", f"bounce from {email}", lead_id=lead["id"])
            handled += 1
    except gmail.GmailAuthError:
        log_event(None, "error", "bounce", "Gmail login failed while checking bounces")
        return "stopped: Gmail needs reconnecting"
    except gmail.GmailTransient as e:
        log_event(None, "warn", "bounce", f"Gmail busy while checking bounces: {e}")
        return "stopped: Gmail busy"
    until = sch.bounce_pause(sch.utcnow())
    if until:
        log_event(None, "warn", "bounce", f"more than {sch.BOUNCE_LIMIT} bounces in 24 h: sending paused until {until:%Y-%m-%d %H:%M} UTC")
    return f"{handled} new bounces"
