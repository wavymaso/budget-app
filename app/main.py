"""FastAPI application: JSON API under /api, single-page UI at /."""
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import config
from .db import init_db
from .routers import budgets, categories, categorize, dashboard, email, expenses, io


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="Budget", lifespan=lifespan)

LOCAL_CLIENTS = {"127.0.0.1", "::1", "localhost"}
OPEN_TO_NETWORK = {"/api/expenses/quick"}   # token-protected


@app.middleware("http")
async def local_only(request: Request, call_next):
    """With `run.py --lan`, other devices may only use the quick-add endpoint."""
    host = request.client.host if request.client else ""
    if host not in LOCAL_CLIENTS and request.url.path not in OPEN_TO_NETWORK:
        return JSONResponse({"detail": "Only the quick-add API is available from other devices."}, status_code=403)
    return await call_next(request)

app.include_router(expenses.router)
app.include_router(categories.router)
app.include_router(categorize.router)
app.include_router(budgets.router)
app.include_router(dashboard.router)
app.include_router(io.router)
app.include_router(email.router)


@app.get("/api/status")
def status():
    return {
        "ai_enabled": config.anthropic_api_key() is not None,
        "quickadd_enabled": config.quickadd_token() is not None,
        "lan_enabled": config.lan_enabled(),
        "data_dir": str(config.DATA_DIR),
        "db_path": str(config.DB_PATH),
    }
app.mount("/static", StaticFiles(directory=config.STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(config.STATIC_DIR / "index.html", headers={"Cache-Control": "no-cache"})
