import json
import re

from pydantic import BaseModel

from ..config import settings
from ..db import get_db
from ..services import llm
from .assets import lead_context

LIMITS = {0: 120, 1: 80, 2: 80, 3: 50}
OPTOUT = 'If this isn\'t relevant, reply "no" and I won\'t email again.'
BANNED = ["i hope this email finds you well", "i came across your website", "synergy", "revolutionize",
          "game-changer", "game changer", "guaranteed", "100%", "free!!!"]


class _Email(BaseModel):
    step: int
    subject: str = ""
    body: str = ""
    evidence_ids: list[str] = []


class SeqOut(BaseModel):
    emails: list[_Email]


def check_email(e: dict, company_name: str, sent_ids: set[str]) -> list[str]:
    """Code checks after the LLM call. Returns a list of error texts (empty = ok)."""
    errs = []
    step, body = e["step"], e["body"]
    text = body.strip()
    core = text[: text.rfind(OPTOUT)] if text.endswith(OPTOUT) else text
    if not text.endswith(OPTOUT):
        errs.append(f"step {step}: last line must be the opt-out line")
    words = len(core.split())
    if words > LIMITS.get(step, 120):
        errs.append(f"step {step}: {words} words, max {LIMITS.get(step)}")
    if len(re.findall(r"https?://", body)) > 1:
        errs.append(f"step {step}: more than 1 link")
    low = body.lower() + " " + e["subject"].lower()
    for b in BANNED:
        if b in low:
            errs.append(f"step {step}: banned phrase '{b}'")
    if re.search(r"[{}]|\[[A-Za-z ]+\]", body + e["subject"]):
        errs.append(f"step {step}: leftover placeholder")
    if step == 0 and company_name and company_name.lower() not in body.lower():
        errs.append("step 0: company name missing")
    if any(i not in sent_ids for i in e["evidence_ids"]):
        errs.append(f"step {step}: unknown evidence id")
    if re.search(r"\b[A-Z]{4,}\b", e["subject"]):
        errs.append(f"step {step}: ALL CAPS in subject")
    return errs


def signature(s: dict, fallback_name: str) -> str:
    parts = [s.get("signature") or "\n".join(x for x in [s.get("sender_name") or fallback_name, s.get("sender_title")] if x)]
    if s.get("postal_address"):
        parts.append(s["postal_address"])
    return "\n".join(p for p in parts if p)


async def build_sequence(lead: dict, run_id: str | None):
    db = get_db()
    if db.table("messages").select("id").eq("lead_id", lead["id"]).execute().data:
        return
    ctx = lead_context(lead)
    st = (db.table("settings").select("*").eq("id", 1).execute().data or [{}])[0]
    j, p, c = ctx["judgment"], ctx["person"], ctx["company"]
    cv_name = (ctx["cv"] or {}).get("name", "")
    report = db.table("assets").select("kind,public_token,demo_url").eq("lead_id", lead["id"]).execute().data
    rep = next((a for a in report if a["kind"] == "report"), None)
    demo = next((a["demo_url"] for a in report if a["kind"] == "demo_spec" and a.get("demo_url")), None)
    ev = [e for e in ctx["evidence"] if e["kind"] != "tech"]
    sent_ids = {e["id"] for e in ctx["evidence"]}
    payload = {
        "sender_name": st.get("sender_name") or cv_name, "sender_title": st.get("sender_title"),
        "cv_proof_points": (ctx["cv"] or {}).get("proof_points", []),
        "person_first_name": (p["name"] or "").split(" ")[0], "company_name": c["name"],
        "evidence": ev, "problem": j["problem"], "fix": j["fix"], "value_estimate": j["value_estimate"],
        "report_link": f"{settings.public_base_url}/r/{rep['public_token']}" if settings.public_base_url and rep else None,
        "demo_url": demo,
    }
    base_user = json.dumps(payload)
    errs: list[str] = []
    emails = None
    for attempt in range(2):
        user = base_user + (f"\n\nFix these problems from the last try: {errs}" if errs else "")
        out = await llm.complete_json("sequence", "smart", llm.load_prompt("sequence"), user, SeqOut, run_id, 0.7)
        emails = sorted(out["emails"], key=lambda e: e["step"])
        errs = []
        if [e["step"] for e in emails] != [0, 1, 2, 3]:
            errs.append("need exactly steps 0,1,2,3")
        else:
            for e in emails:
                errs += check_email(e, c["name"], sent_ids)
        if not errs:
            break

    sig = signature(st, cv_name)
    main_subject = emails[0]["subject"]
    rows = []
    for e in emails:
        rows.append({
            "lead_id": lead["id"], "step": e["step"],
            "subject": main_subject if e["step"] == 0 else f"Re: {main_subject}",
            "body": e["body"].rstrip() + ("\n\n" + sig if sig else ""),
            "evidence_ids": [i for i in e["evidence_ids"] if i in sent_ids],
            "status": "draft", "error": ("needs manual edit: " + "; ".join(errs))[:500] if errs else None,
        })
    db.table("messages").insert(rows).execute()
    db.table("leads").update({"stage": "ready"}).eq("id", lead["id"]).execute()
    if st.get("auto_send") and not errs:
        approve_lead(lead["id"])


def approve_lead(lead_id: str):
    db = get_db()
    db.table("messages").update({"status": "approved"}).eq("lead_id", lead_id).eq("status", "draft").execute()
    db.table("leads").update({"stage": "in_sequence"}).eq("id", lead_id).execute()
