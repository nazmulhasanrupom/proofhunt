import re
import uuid

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from postgrest.exceptions import APIError
from pydantic import BaseModel

from ..db import get_db
from ..deps import as_uuid
from ..pipeline import ima_brief, offer_map
from ..pipeline.kinds import FREELANCER, IMA, KINDS, kind_of
from ..services import cv_parser, llm
from ..services.usage import BudgetExceeded, log_event

router = APIRouter()
MAX_BYTES = 5 * 1024 * 1024
MAX_NAME = 60
MIGRATION_HINT = "The database is not updated yet. Run backend/migrations/003_profiles.sql in Supabase Studio, then reload this page."


class _Role(BaseModel):
    title: str = ""
    company: str = ""
    summary: str = ""


class _Project(BaseModel):
    name: str = ""
    what: str = ""
    result: str = ""


class ParsedCV(BaseModel):
    name: str = ""
    headline: str = ""
    years_experience: int = 0
    skills: list[str] = []
    tools: list[str] = []
    roles: list[_Role] = []
    projects: list[_Project] = []
    proof_points: list[str] = []


def clean_name(raw: str) -> str:
    name = " ".join((raw or "").split())
    if not name:
        raise HTTPException(422, "Give the profile a name")
    if len(name) > MAX_NAME:
        raise HTTPException(422, f"The name can have at most {MAX_NAME} characters")
    return name


def _name_taken(name: str, except_id: str | None = None) -> bool:
    rows = get_db().table("profiles").select("id,name").execute().data
    return any(r["name"].casefold() == name.casefold() and r["id"] != except_id for r in rows)


def _check_name_free(name: str, except_id: str | None = None):
    if _name_taken(name, except_id):
        raise HTTPException(409, f"A profile named '{name}' already exists")


def _row(profile_id: str) -> dict:
    pid = as_uuid(profile_id)
    r = get_db().table("profiles").select("id,name,file_name,storage_path,parsed,created_at").eq("id", pid).execute().data if pid else []
    if not r:
        raise HTTPException(404, "Profile not found")
    return r[0]


def _public(r: dict) -> dict:
    return {k: v for k, v in r.items() if k != "storage_path"}


async def _read_cv(file: UploadFile, kind: str = FREELANCER) -> tuple[bytes, str, dict]:
    """Read the upload, get its text, let the AI parse it. Nothing is saved yet. For an IMA profile the file is an agency brief."""
    data = await file.read()
    if len(data) > MAX_BYTES:
        raise HTTPException(413, "File is larger than 5 MB")
    try:
        text = cv_parser.extract_text(file.filename or "", data)
    except cv_parser.CVError as e:
        raise HTTPException(400, str(e))
    what = "agency brief" if kind == IMA else "CV"
    try:
        if kind == IMA:
            ai = await llm.complete_json("ima_parse", "fast", llm.load_prompt("ima_parse"), text[:20000], ima_brief.ParsedBrief)
            parsed = ima_brief.normalize(ai, text[:20000])  # every number and name is checked against the brief
        else:
            parsed = await llm.complete_json("cv_parse", "fast", llm.load_prompt("cv_parse"), text[:20000], ParsedCV)
    except BudgetExceeded as e:
        raise HTTPException(429, str(e))
    except Exception as e:
        raise HTTPException(502, f"The AI could not read this {what}: {str(e)[:200]}")
    return data, text, parsed


def _store_cv(file: UploadFile, data: bytes) -> str:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", file.filename or "cv")[:80]
    path = f"{uuid.uuid4()}-{safe}"
    get_db().storage.from_("cvs").upload(path, data, {"content-type": file.content_type or "application/octet-stream"})
    return path


def _remove_cv(path: str | None):
    if not path:
        return
    try:
        get_db().storage.from_("cvs").remove([path])
    except Exception as e:  # a file that stays behind is not worth failing the request
        print(f"cv file cleanup failed: {type(e).__name__}")


@router.get("/profiles")
def list_profiles():
    rows = None
    for cols in ("id,name,file_name,created_at,parsed,kind", "id,name,file_name,created_at,parsed"):  # the 2nd: migration 005 is not run yet
        try:
            rows = get_db().table("profiles").select(cols).order("created_at").execute().data
            break
        except APIError as e:
            if e.code != "42703":  # undefined column
                raise
    if rows is None:  # not even migration 003 has been run
        raise HTTPException(503, MIGRATION_HINT)
    return [{"id": r["id"], "name": r["name"], "file_name": r["file_name"], "created_at": r["created_at"], "kind": r.get("kind") or FREELANCER,
             "headline": (r["parsed"] or {}).get("headline") or None} for r in rows]


@router.post("/profiles")
async def create_profile(name: str = Form(...), file: UploadFile = File(...), kind: str = Form(FREELANCER)):
    name = clean_name(name)
    if kind not in KINDS:
        raise HTTPException(422, "Unknown profile type")
    _check_name_free(name)  # before the AI call, so a taken name costs nothing
    data, text, parsed = await _read_cv(file, kind)
    path = _store_cv(file, data)
    new = {"name": name, "file_name": file.filename, "storage_path": path, "raw_text": text, "parsed": parsed}
    if kind != FREELANCER:  # a freelancer profile does not send the column, so it still works before migration 005
        new["kind"] = kind
    try:
        row = get_db().table("profiles").insert(new).execute().data[0]
    except APIError as e:
        _remove_cv(path)
        if e.code == "23505":  # two creates with the same name at the same moment
            raise HTTPException(409, f"A profile named '{name}' already exists")
        if kind != FREELANCER and e.code in ("42703", "PGRST204"):  # no `kind` column: migration 005 has not been run
            raise HTTPException(503, "The database is not updated yet. Run backend/migrations/005_ima.sql in Supabase Studio, then try again.")
        raise
    log_event(None, "info", "profile", f"profile '{name}' created", profile_id=row["id"])
    return {**{k: row[k] for k in ("id", "name", "file_name", "parsed", "created_at")}, "kind": kind}


@router.get("/profiles/{profile_id}")
def get_profile(profile_id: str):
    r = _row(profile_id)
    db = get_db()

    def count(table: str, **eq) -> int:
        q = db.table(table).select("id", count="exact").eq("profile_id", r["id"])
        for k, v in eq.items():
            q = q.eq(k, v)
        return q.limit(1).execute().count or 0

    return {**_public(r), "kind": kind_of(r["id"]), "counts": {
        "campaigns": count("campaigns"), "companies": count("companies"), "leads": count("leads"),
        "emails_sent": count("messages", status="sent"),
    }}


class Rename(BaseModel):
    name: str


@router.patch("/profiles/{profile_id}")
def rename_profile(profile_id: str, body: Rename):
    r = _row(profile_id)
    name = clean_name(body.name)
    _check_name_free(name, r["id"])
    try:
        get_db().table("profiles").update({"name": name}).eq("id", r["id"]).execute()
    except APIError as e:
        if e.code == "23505":
            raise HTTPException(409, f"A profile named '{name}' already exists")
        raise
    log_event(None, "info", "profile", f"profile '{r['name']}' renamed to '{name}'", profile_id=r["id"])
    return {"ok": True}


@router.put("/profiles/{profile_id}/cv")
async def replace_cv(profile_id: str, file: UploadFile = File(...)):
    """A better CV (or agency brief) for the same profile. Campaigns, leads and the offer map stay. Generate the offer map again to use the new file."""
    old = _row(profile_id)
    data, text, parsed = await _read_cv(file, kind_of(old["id"]))
    path = _store_cv(file, data)
    get_db().table("profiles").update({"file_name": file.filename, "storage_path": path, "raw_text": text, "parsed": parsed}).eq("id", old["id"]).execute()
    _remove_cv(old["storage_path"])
    log_event(None, "info", "profile", f"profile '{old['name']}': CV replaced with {file.filename}", profile_id=old["id"])
    return _public({**old, "file_name": file.filename, "parsed": parsed, "storage_path": path})


@router.delete("/profiles/{profile_id}")
def delete_profile(profile_id: str):
    """Delete the profile and everything in it: campaigns, runs, companies, leads, emails, replies."""
    r = _row(profile_id)
    db = get_db()
    if db.table("runs").select("id").eq("profile_id", r["id"]).in_("status", ["queued", "running"]).limit(1).execute().data:
        raise HTTPException(409, "A run of this profile is active. Cancel it in Activity first.")
    if db.table("messages").select("id").eq("profile_id", r["id"]).eq("status", "sending").limit(1).execute().data:
        raise HTTPException(409, "An email of this profile is being sent right now. Try again in a minute.")
    db.rpc("delete_profile", {"p_id": r["id"]}).execute()
    _remove_cv(r["storage_path"])
    log_event(None, "info", "profile", f"profile '{r['name']}' deleted with all its data")
    return {"ok": True}


@router.post("/profiles/{profile_id}/offer-map")
async def generate_offer_map(profile_id: str):
    r = _row(profile_id)
    try:
        await offer_map.generate(r["id"])
    except BudgetExceeded as e:
        raise HTTPException(429, str(e))
    return offer_map.load_map(r["id"])
