import html

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse

from ..db import get_db

router = APIRouter()


@router.get("/r/{token}", response_class=HTMLResponse)
def report_page(token: str):
    r = get_db().table("assets").select("content_md").eq("public_token", token).execute().data
    if not r:
        raise HTTPException(404)
    body = html.escape(r[0]["content_md"])
    return f"<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'><meta name=robots content=noindex><title>Report</title><body style='font-family:system-ui;max-width:640px;margin:2rem auto;padding:0 1rem;white-space:pre-wrap;line-height:1.5'>{body}</body>"
