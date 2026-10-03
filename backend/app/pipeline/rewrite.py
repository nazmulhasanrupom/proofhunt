"""Rewrite one email with the AI. The opt-out line and the signature are kept by code, never by the model."""
import json

from pydantic import BaseModel

from ..db import get_db
from ..services import llm
from .sequences import LIMITS, OPTOUT, check_email


class RewriteOut(BaseModel):
    subject: str = ""
    body: str = ""


def split_body(body: str) -> tuple[str, str]:
    """(text the AI may change, tail kept as is). The tail is the opt-out line plus the signature."""
    i = body.rfind(OPTOUT)
    if i < 0:
        return body.strip(), ""
    return body[:i].rstrip(), body[i:].strip()


def join_body(core: str, tail: str, signature_hint: str = "") -> str:
    return core.strip() + "\n\n" + (tail or OPTOUT)


def warnings_for(step: int, subject: str, body: str, company_name: str, evidence_ids: list[str]) -> list[str]:
    core, _ = split_body(body)
    return check_email({"step": step, "subject": subject, "body": core + "\n\n" + OPTOUT, "evidence_ids": evidence_ids},
                       company_name, set(evidence_ids))


async def rewrite_message(m: dict, instruction: str) -> dict:
    db = get_db()
    lead = db.table("leads").select("company_id,person_id").eq("id", m["lead_id"]).single().execute().data
    company = db.table("companies").select("name,domain").eq("id", lead["company_id"]).single().execute().data
    person = db.table("people").select("name").eq("id", lead["person_id"]).single().execute().data if lead.get("person_id") else {}
    ev_ids = m.get("evidence_ids") or []
    quotes = db.table("evidence").select("quote,url").in_("id", ev_ids).execute().data if ev_ids else []
    core, tail = split_body(m["body"] or "")
    step = m["step"]
    payload = {
        "step": step, "instruction": instruction.strip() or None, "max_words": LIMITS.get(step, 120),
        "company_name": company["name"] or company["domain"], "person_first_name": ((person or {}).get("name") or "").split(" ")[0],
        "current_subject": m["subject"], "current_body": core, "quotes": quotes,
    }
    out = await llm.complete_json("rewrite", "fast", llm.load_prompt("rewrite"), json.dumps(payload), RewriteOut, None, 0.7)
    subject = out["subject"].strip() if step == 0 and out["subject"].strip() else m["subject"]
    body = join_body(out["body"], tail)
    return {"subject": subject, "body": body,
            "warnings": warnings_for(step, subject, body, company["name"] or "", ev_ids)}
