"""Зависимости FastAPI: сессия БД, авторизация, CSRF."""

from __future__ import annotations

import secrets
from urllib.parse import quote

from fastapi import HTTPException, Request
from sqlalchemy.orm import Session, sessionmaker

SESSION_KEY_ADMIN = "admin_authenticated"
SESSION_KEY_CSRF = "csrf_token"

AUDIT_LOGIN_FAILED = "admin_login_failed"
AUDIT_DOCUMENT_SAVED = "document_saved"
AUDIT_DOCUMENT_PUBLISHED = "document_published"
AUDIT_DOCUMENT_INDEXED = "document_indexed"
AUDIT_DOCUMENT_INDEX_FAILED = "document_index_failed"
AUDIT_REINDEX_ALL = "reindex_all_completed"
AUDIT_REINDEX_ALL_FAILED = "reindex_all_failed"


def get_session_factory(request: Request) -> sessionmaker[Session]:
    sf = getattr(request.app.state, "session_factory", None)
    if sf is None:
        raise RuntimeError("session_factory not configured")
    return sf


def ensure_csrf_token(request: Request) -> str:
    token = request.session.get(SESSION_KEY_CSRF)
    if not token:
        token = secrets.token_urlsafe(32)
        request.session[SESSION_KEY_CSRF] = token
    return str(token)


def require_csrf(request: Request, csrf_token: str) -> None:
    expected = request.session.get(SESSION_KEY_CSRF)
    if not expected or not csrf_token or not secrets.compare_digest(str(expected), str(csrf_token)):
        raise HTTPException(status_code=403, detail="Invalid CSRF token")


def admin_required(request: Request) -> None:
    if request.session.get(SESSION_KEY_ADMIN):
        return
    nxt = quote(str(request.url.path), safe="/")
    raise HTTPException(status_code=303, headers={"Location": f"/login?next={nxt}"})
