from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel

from ..db import get_db
from ..pipeline import offer_map
from ..services import cv_parser, llm

router = APIRouter()
MAX_BYTES = 5 * 1024 * 1024


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


@router.post("/profiles")
async def upload_profile(file: UploadFile = File(...)):
    data = await file.read()
    if len(data) > MAX_BYTES:
        raise HTTPException(413, "File is larger than 5 MB")
    try:
        text = cv_parser.extract_text(file.filename or "", data)
    except cv_parser.CVError as e:
        raise HTTPException(400, str(e))
    db = get_db()
    path = f"{__import__('uuid').uuid4()}-{file.filename}"
    db.storage.from_("cvs").upload(path, data, {"content-type": file.content_type or "application/octet-stream"})
    parsed = await llm.complete_json("cv_parse", "fast", llm.load_prompt("cv_parse"), text[:20000], ParsedCV)
    db.table("profiles").update({"is_active": False}).eq("is_active", True).execute()
    row = db.table("profiles").insert({
        "file_name": file.filename, "storage_path": path, "raw_text": text, "parsed": parsed, "is_active": True,
    }).execute().data[0]
    return row


@router.get("/profiles/active")
def active_profile():
    r = get_db().table("profiles").select("id,file_name,parsed,created_at").eq("is_active", True).limit(1).execute().data
    return r[0] if r else None


@router.post("/profiles/{profile_id}/offer-map")
async def generate_offer_map(profile_id: str):
    await offer_map.generate(profile_id)
    return offer_map.load_map(profile_id)
