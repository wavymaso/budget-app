"""Signing in from a phone on the Wi-Fi, and the Mac-only phone access settings."""
import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from .. import auth, config, server
from ..db import get_db

router = APIRouter(tags=["phone access"])


class LoginIn(BaseModel):
    password: str = Field(max_length=200)


@router.get("/login", include_in_schema=False)
def login_page():
    return FileResponse(config.STATIC_DIR / "login.html", headers={"Cache-Control": "no-cache"})


@router.post("/api/auth/login")
def login(body: LoginIn, request: Request, response: Response, db: sqlite3.Connection = Depends(get_db)):
    ip = request.client.host if request.client else "?"
    if not auth.has_password(db):
        raise HTTPException(403, "Phone access has no password yet. Set one on your Mac: Settings → Phone access.")
    wait = auth.seconds_locked_out(ip)
    if wait:
        raise HTTPException(429, f"Too many wrong passwords. Try again in {max(1, wait // 60)} minute(s).")
    if not auth.check_password(db, body.password):
        auth.record_failure(ip)
        raise HTTPException(401, "Wrong password")
    auth.clear_failures(ip)
    token = auth.create_session(db, request.headers.get("user-agent", ""), ip)
    response.set_cookie(auth.COOKIE, token, max_age=auth.SESSION_DAYS * 86400,
                        httponly=True, samesite="lax", path="/")
    return {"ok": True}


@router.post("/api/auth/logout")
def logout(request: Request, response: Response, db: sqlite3.Connection = Depends(get_db)):
    auth.end_session(db, request.cookies.get(auth.COOKIE))
    response.delete_cookie(auth.COOKIE, path="/")
    return {"ok": True}


@router.get("/api/auth/me")
def me(request: Request):
    host = request.client.host if request.client else None
    return {"local": auth.is_local(host)}


# --- settings: only reachable from the Mac itself (see main.local_only) ------------

class PhoneIn(BaseModel):
    enabled: bool
    port: int = Field(8000, ge=1024, le=65535)
    password: str | None = Field(None, max_length=200)


def _phone_status(db: sqlite3.Connection) -> dict:
    cfg = auth.phone_settings(db)
    pa = server.phone_access
    return {
        **cfg,
        "has_password": auth.has_password(db),
        "available": pa is not None,          # False when running with run.py --browser
        "running": bool(pa and pa.running),
        "error": pa.error if pa else None,
        "urls": pa.urls() if pa else [],
        "sessions": auth.list_sessions(db),
        "min_password_length": auth.MIN_PASSWORD_LENGTH,
    }


@router.get("/api/phone")
def phone_status(db: sqlite3.Connection = Depends(get_db)):
    return _phone_status(db)


@router.put("/api/phone")
def phone_update(body: PhoneIn, db: sqlite3.Connection = Depends(get_db)):
    if body.password:
        try:
            auth.set_password(db, body.password)
        except ValueError as exc:
            raise HTTPException(422, str(exc))
    if body.enabled and not auth.has_password(db):
        raise HTTPException(422, "Set a password before turning on phone access")
    auth.save_phone_settings(db, enabled=body.enabled, port=body.port)
    if server.phone_access is not None:
        server.phone_access.apply(body.enabled, body.port)
    return _phone_status(db)


@router.post("/api/phone/sign-out-all")
def phone_sign_out_all(db: sqlite3.Connection = Depends(get_db)):
    auth.sign_out_everyone(db)
    db.commit()
    return _phone_status(db)
