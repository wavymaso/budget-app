"""FastAPI application: JSON API under /api, single-page UI at /."""
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from . import auth, config, server
from .db import connect, init_db
from .routers import auth as auth_routes
from .routers import budgets, categories, categorize, dashboard, email, expenses, io, preferences


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="Budget", lifespan=lifespan)

# Requests from other devices (phone access): what they may reach.
OPEN_TO_NETWORK = {"/api/expenses/quick", "/login", "/api/auth/login", "/api/auth/me", "/favicon.ico"}
MAC_ONLY_PREFIXES = ("/api/phone", "/api/email/settings", "/api/email/test")


@app.middleware("http")
async def access_control(request: Request, call_next):
    """The Mac's own window gets everything. Other devices must sign in with the
    phone password, and can never change phone access or Gmail settings."""
    host = request.client.host if request.client else ""
    if auth.is_local(host):
        return await call_next(request)
    path = request.url.path
    if path in OPEN_TO_NETWORK or path.startswith("/static/"):
        return await call_next(request)   # quick-add checks its own token
    if path.startswith(MAC_ONLY_PREFIXES):
        return JSONResponse({"detail": "This setting can only be changed on the Mac."}, status_code=403)
    conn = connect()
    try:
        signed_in = auth.valid_session(conn, request.cookies.get(auth.COOKIE))
    finally:
        conn.close()
    if not signed_in:
        if path.startswith("/api/"):
            return JSONResponse({"detail": "Please sign in"}, status_code=401)
        return RedirectResponse("/login", status_code=303)
    return await call_next(request)


app.include_router(expenses.router)
app.include_router(categories.router)
app.include_router(categorize.router)
app.include_router(budgets.router)
app.include_router(dashboard.router)
app.include_router(io.router)
app.include_router(email.router)
app.include_router(auth_routes.router)
app.include_router(preferences.router)


@app.get("/api/status")
def status():
    pa = server.phone_access
    return {
        "ai_enabled": config.anthropic_api_key() is not None,
        "quickadd_enabled": config.quickadd_token() is not None,
        "lan_enabled": bool(pa and pa.running),
        "data_dir": str(config.DATA_DIR),
        "db_path": str(config.DB_PATH),
    }


app.mount("/static", StaticFiles(directory=config.STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(config.STATIC_DIR / "index.html", headers={"Cache-Control": "no-cache"})
