import hmac
from contextlib import asynccontextmanager

from arq import create_pool
from arq.connections import RedisSettings
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from redis.asyncio import from_url

from .config import settings
from .db import get_db
from .routers import auth_google, campaigns, companies, leads, messages, offer_map, outbox, profiles, public, runs, stats
from .routers import settings as settings_router


def ensure_bucket():
    """Create the private `cvs` bucket on first start, so the user has one setup step less."""
    if not settings.supabase_url or not settings.supabase_key:
        return
    try:
        storage = get_db().storage
        if not any(b.name == "cvs" for b in storage.list_buckets()):
            storage.create_bucket("cvs", options={"public": False})
    except Exception as e:  # DB down at boot must not stop the API
        print(f"bucket check failed: {type(e).__name__}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.arq = await create_pool(RedisSettings.from_dsn(settings.redis_url))
    ensure_bucket()
    yield
    await app.state.arq.aclose()


app = FastAPI(title="Proofhunt", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

OPEN_PATHS = ("/health", "/auth/google/callback")  # Google calls the callback itself; /r/{token} is the public report
MAX_BAD_LOGINS = 20  # per 15 minutes


def password_ok(header: str) -> bool:
    given = header[7:] if header.lower().startswith("bearer ") else ""
    return hmac.compare_digest(given.encode(), settings.access_password.encode())


@app.middleware("http")
async def require_password(request: Request, call_next):
    """Hosting guard. With ACCESS_PASSWORD empty (local use) nothing changes."""
    path = request.url.path
    if not settings.access_password or request.method == "OPTIONS" or path in OPEN_PATHS or path.startswith("/r/"):
        return await call_next(request)
    redis = request.app.state.arq
    ip = request.client.host if request.client else "?"
    key = f"auth:bad:{ip}"
    if int(await redis.get(key) or 0) >= MAX_BAD_LOGINS:
        return JSONResponse({"detail": "Too many wrong passwords. Wait 15 minutes."}, status_code=429)
    if not password_ok(request.headers.get("authorization", "")):
        if request.headers.get("authorization"):  # a wrong password counts, a missing one does not
            await redis.incr(key)
            await redis.expire(key, 900)
        return JSONResponse({"detail": "Password needed"}, status_code=401)
    return await call_next(request)


@app.get("/auth/check")
async def auth_check():
    return {"ok": True}


app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_url],
    allow_methods=["*"],
    allow_headers=["*"],
)
for r in (profiles, offer_map, campaigns, runs, companies, leads, messages, settings_router, public, auth_google, outbox, stats):
    app.include_router(r.router)


@app.get("/health")
async def health():
    redis_state = "ok"
    try:
        r = from_url(settings.redis_url)
        await r.ping()
        await r.aclose()
    except Exception as e:
        redis_state = f"error: {type(e).__name__}"

    if not settings.supabase_url or not settings.supabase_key:
        db_state = "not_configured"
    else:
        try:
            get_db().table("settings").select("id").limit(1).execute()
            db_state = "ok"
        except Exception as e:
            db_state = f"error: {type(e).__name__}"

    ok = redis_state == "ok" and db_state in ("ok", "not_configured")
    return {"status": "ok" if ok else "error", "redis": redis_state, "db": db_state, "dry_run": settings.dry_run}
