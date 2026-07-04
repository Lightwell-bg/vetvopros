"""HTML-маршруты админ-панели: логин, CRUD документов, статус, audit."""

from __future__ import annotations

import json
import re
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import markdown
from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from vetvopros.admin.auth import verify_admin_credentials
from vetvopros.admin.deps import (
    AUDIT_DOCUMENT_INDEX_FAILED,
    AUDIT_DOCUMENT_INDEXED,
    AUDIT_DOCUMENT_PUBLISHED,
    AUDIT_DOCUMENT_SAVED,
    AUDIT_LOGIN_FAILED,
    AUDIT_REINDEX_ALL,
    AUDIT_REINDEX_ALL_FAILED,
    SESSION_KEY_ADMIN,
    admin_required,
    ensure_csrf_token,
    get_session_factory,
    require_csrf,
)
from vetvopros.config.settings import Settings
from vetvopros.db.constants import (
    DOCUMENT_STATUSES,
    DOCUMENT_STATUS_DRAFT,
    DOCUMENT_STATUS_PUBLISHED,
)
from vetvopros.db.session import check_database
from vetvopros.rag.embeddings import EmbeddingRequestError
from vetvopros.repositories.audit_repo import AuditRepository
from vetvopros.repositories.chunk_repo import ChunkRepository
from vetvopros.repositories.document_repo import DocumentRepository, PUBLISHED_AT_UNCHANGED
from vetvopros.services.rag_service import RagService, default_embedder
from vetvopros.utils.logging import get_logger

_SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_log = get_logger(__name__)

_TEMPLATES = Jinja2Templates(directory=str(Path(__file__).resolve().parent / "templates"))


def _pretty_json(value: object) -> str:
    return json.dumps(value, indent=2, ensure_ascii=False, default=str)


_TEMPLATES.env.filters["pretty_json"] = _pretty_json

router = APIRouter()

def _max_form_bytes(request: Request) -> int:
    """Максимальный размер form-body для админки.

    Источник: `config.ini` → `[admin] max_form_bytes` (несекретно).
    """
    settings = _settings(request)
    try:
        v = int(getattr(settings.admin, "max_form_bytes", 10 * 1024 * 1024))
    except Exception:
        v = 10 * 1024 * 1024
    return max(256 * 1024, v)


def _settings(request: Request) -> Settings:
    s = getattr(request.app.state, "settings", None)
    if s is None:
        raise RuntimeError("settings not configured on app.state")
    return s


def _engine(request: Request):
    eng = getattr(request.app.state, "engine", None)
    if eng is None:
        raise RuntimeError("engine not configured on app.state")
    return eng


def _rag(sf: sessionmaker[Session], settings: Settings) -> RagService:
    return RagService(
        settings,
        documents=DocumentRepository(sf),
        chunks=ChunkRepository(sf),
        embedder=default_embedder(settings),
    )


def _flash(request: Request, message: str) -> None:
    request.session["flash"] = message


def _pop_flash(request: Request) -> str | None:
    return request.session.pop("flash", None)  # type: ignore[no-any-return]


def _audit(sf: sessionmaker[Session], event_type: str, details: dict | None = None) -> None:
    AuditRepository(sf).append(user_id=None, event_type=event_type, details=details or {})


def _validate_slug(slug: str) -> str | None:
    s = slug.strip().lower()
    if not s or len(s) > 256:
        return "Некорректный slug (1–256 символов, латиница, цифры, дефисы)."
    if not _SLUG_RE.match(s):
        return "Slug: только строчные латинские буквы, цифры и дефисы между словами."
    return None


@router.get("/", response_class=HTMLResponse)
def root(request: Request) -> RedirectResponse:
    if request.session.get(SESSION_KEY_ADMIN):
        return RedirectResponse("/documents", status_code=303)
    return RedirectResponse("/login", status_code=303)


@router.get("/login", response_class=HTMLResponse, response_model=None)
def login_form(
    request: Request,
    next_url: str | None = Query(None, alias="next"),
    error: str | None = None,
) -> Response:
    if request.session.get(SESSION_KEY_ADMIN):
        dest = (
            next_url
            if (next_url and next_url.startswith("/") and not next_url.startswith("//"))
            else "/documents"
        )
        return RedirectResponse(dest, status_code=303)
    csrf = ensure_csrf_token(request)
    return _TEMPLATES.TemplateResponse(
        request,
        "login.html",
        {"csrf_token": csrf, "error": error, "next_url": next_url or ""},
    )


@router.post("/login")
def login_post(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    csrf_token: str = Form(...),
    next_url: str = Form(""),
) -> Response:
    require_csrf(request, csrf_token)
    settings = _settings(request)
    sf = get_session_factory(request)
    if verify_admin_credentials(
        username,
        password,
        settings.admin_username,
        settings.admin_password,
    ):
        request.session[SESSION_KEY_ADMIN] = True
        ensure_csrf_token(request)
        dest = (
            next_url
            if (next_url.startswith("/") and not next_url.startswith("//"))
            else "/documents"
        )
        return RedirectResponse(dest, status_code=303)
    _audit(sf, AUDIT_LOGIN_FAILED, {"reason": "bad_credentials"})
    csrf = ensure_csrf_token(request)
    return _TEMPLATES.TemplateResponse(
        request,
        "login.html",
        {"csrf_token": csrf, "error": "Неверный логин или пароль.", "next_url": next_url},
        status_code=401,
    )


@router.post("/logout")
def logout(request: Request, csrf_token: str = Form(...)) -> RedirectResponse:
    require_csrf(request, csrf_token)
    request.session.clear()
    return RedirectResponse("/login", status_code=303)


@router.get("/documents", response_class=HTMLResponse)
def documents_list(
    request: Request,
    _: None = Depends(admin_required),
    status: str | None = None,
    q: str | None = None,
) -> HTMLResponse:
    sf = get_session_factory(request)
    docs = DocumentRepository(sf).list_filtered(status=status or None, search=q or None)
    chunk_counts = ChunkRepository(sf).counts_for_documents([d.id for d in docs])
    csrf = ensure_csrf_token(request)
    return _TEMPLATES.TemplateResponse(
        request,
        "documents_list.html",
        {
            "documents": docs,
            "chunk_counts": chunk_counts,
            "filter_status": status or "",
            "search_q": q or "",
            "csrf_token": csrf,
            "flash": _pop_flash(request),
            "statuses": DOCUMENT_STATUSES,
            "show_nav": True,
        },
    )


@router.get("/documents/new", response_class=HTMLResponse)
def document_new_form(request: Request, _: None = Depends(admin_required)) -> HTMLResponse:
    csrf = ensure_csrf_token(request)
    return _TEMPLATES.TemplateResponse(
        request,
        "document_form.html",
        {
            "csrf_token": csrf,
            "doc": None,
            "error": None,
            "flash": _pop_flash(request),
            "statuses": DOCUMENT_STATUSES,
            "show_nav": True,
        },
    )


@router.post("/documents/new", response_model=None)
async def document_create(
    request: Request,
    _: None = Depends(admin_required),
) -> Response:
    form = await request.form(max_part_size=_max_form_bytes(request))
    title = str(form.get("title") or "")
    slug = str(form.get("slug") or "")
    body_markdown = str(form.get("body_markdown") or "")
    status = str(form.get("status") or "draft")
    csrf_token = str(form.get("csrf_token") or "")
    require_csrf(request, csrf_token)
    err = _validate_slug(slug)
    if status not in DOCUMENT_STATUSES:
        err = err or "Некорректный статус."
    if err:
        csrf = ensure_csrf_token(request)
        return _TEMPLATES.TemplateResponse(
            request,
            "document_form.html",
            {
                "csrf_token": csrf,
                "doc": None,
                "error": err,
                "form": {"title": title, "slug": slug, "body_markdown": body_markdown, "status": status},
                "flash": None,
                "statuses": DOCUMENT_STATUSES,
                "show_nav": True,
            },
            status_code=400,
        )
    sf = get_session_factory(request)
    repo = DocumentRepository(sf)
    try:
        doc = repo.create(
            title=title.strip(),
            slug=slug.strip().lower(),
            body_markdown=body_markdown,
            status=status,
        )
    except IntegrityError:
        csrf = ensure_csrf_token(request)
        return _TEMPLATES.TemplateResponse(
            request,
            "document_form.html",
            {
                "csrf_token": csrf,
                "doc": None,
                "error": "Документ с таким slug уже существует.",
                "form": {"title": title, "slug": slug, "body_markdown": body_markdown, "status": status},
                "flash": None,
                "statuses": DOCUMENT_STATUSES,
                "show_nav": True,
            },
            status_code=400,
        )
    _audit(
        sf,
        AUDIT_DOCUMENT_SAVED,
        {"document_id": str(doc.id), "slug": doc.slug, "status": doc.status},
    )
    index_failed = False
    if status == DOCUMENT_STATUS_PUBLISHED:
        doc = repo.update(doc.id, published_at=datetime.now(timezone.utc))
        assert doc is not None
        _audit(sf, AUDIT_DOCUMENT_PUBLISHED, {"document_id": str(doc.id), "slug": doc.slug})
        settings = _settings(request)
        if settings.features.auto_index_on_publish:
            rag = _rag(sf, settings)
            t0 = time.perf_counter()
            try:
                rag.reindex_document(doc.id)
                dt_ms = int((time.perf_counter() - t0) * 1000)
                _audit(
                    sf,
                    AUDIT_DOCUMENT_INDEXED,
                    {"document_id": str(doc.id), "slug": doc.slug, "duration_ms": dt_ms, "trigger": "auto_publish"},
                )
            except EmbeddingRequestError:
                index_failed = True
                dt_ms = int((time.perf_counter() - t0) * 1000)
                _audit(
                    sf,
                    AUDIT_DOCUMENT_INDEX_FAILED,
                    {
                        "document_id": str(doc.id),
                        "slug": doc.slug,
                        "duration_ms": dt_ms,
                        "error": "embedding_request_failed",
                        "trigger": "auto_publish",
                    },
                )
    if index_failed:
        _flash(
            request,
            "Документ создан, но автоиндексация не прошла (эмбеддинги). Откройте правку и нажмите «Индексировать» или смотрите audit.",
        )
    else:
        _flash(request, "Документ создан.")
    return RedirectResponse(f"/documents/{doc.id}/edit", status_code=303)


@router.get("/documents/{doc_id}", response_class=HTMLResponse)
def document_view(
    request: Request,
    doc_id: uuid.UUID,
    _: None = Depends(admin_required),
) -> HTMLResponse:
    sf = get_session_factory(request)
    doc = DocumentRepository(sf).get_by_id(doc_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Not found")
    chunk_count = ChunkRepository(sf).count_for_document(doc_id)
    html_body = markdown.markdown(
        doc.body_markdown,
        extensions=["fenced_code", "tables", "nl2br"],
    )
    csrf = ensure_csrf_token(request)
    return _TEMPLATES.TemplateResponse(
        request,
        "document_detail.html",
        {
            "doc": doc,
            "chunk_count": chunk_count,
            "html_body": html_body,
            "csrf_token": csrf,
            "flash": _pop_flash(request),
            "show_nav": True,
        },
    )


@router.get("/documents/{doc_id}/edit", response_class=HTMLResponse)
def document_edit_form(
    request: Request,
    doc_id: uuid.UUID,
    _: None = Depends(admin_required),
) -> HTMLResponse:
    sf = get_session_factory(request)
    doc = DocumentRepository(sf).get_by_id(doc_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Not found")
    chunk_count = ChunkRepository(sf).count_for_document(doc_id)
    csrf = ensure_csrf_token(request)
    return _TEMPLATES.TemplateResponse(
        request,
        "document_form.html",
        {
            "csrf_token": csrf,
            "doc": doc,
            "chunk_count": chunk_count,
            "error": None,
            "form": None,
            "flash": _pop_flash(request),
            "statuses": DOCUMENT_STATUSES,
            "show_nav": True,
        },
    )


def _published_at_arg(old_status: str, new_status: str) -> datetime | None | object:
    if new_status == DOCUMENT_STATUS_PUBLISHED and old_status != DOCUMENT_STATUS_PUBLISHED:
        return datetime.now(timezone.utc)
    if old_status == DOCUMENT_STATUS_PUBLISHED and new_status != DOCUMENT_STATUS_PUBLISHED:
        return None
    return PUBLISHED_AT_UNCHANGED


@router.post("/documents/{doc_id}/edit", response_model=None)
async def document_edit_post(
    request: Request,
    doc_id: uuid.UUID,
    _: None = Depends(admin_required),
) -> Response:
    form = await request.form(max_part_size=_max_form_bytes(request))
    title = str(form.get("title") or "")
    slug = str(form.get("slug") or "")
    body_markdown = str(form.get("body_markdown") or "")
    status = str(form.get("status") or "")
    csrf_token = str(form.get("csrf_token") or "")
    require_csrf(request, csrf_token)
    sf = get_session_factory(request)
    repo = DocumentRepository(sf)
    existing = repo.get_by_id(doc_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Not found")

    err = _validate_slug(slug)
    if status not in DOCUMENT_STATUSES:
        err = err or "Некорректный статус."
    if err:
        csrf = ensure_csrf_token(request)
        fake = existing
        chunk_count = ChunkRepository(sf).count_for_document(doc_id)
        return _TEMPLATES.TemplateResponse(
            request,
            "document_form.html",
            {
                "csrf_token": csrf,
                "doc": fake,
                "chunk_count": chunk_count,
                "error": err,
                "form": {"title": title, "slug": slug, "body_markdown": body_markdown, "status": status},
                "flash": None,
                "statuses": DOCUMENT_STATUSES,
                "show_nav": True,
            },
            status_code=400,
        )

    slug_norm = slug.strip().lower()
    pub_at = _published_at_arg(existing.status, status)
    try:
        updated = repo.update(
            doc_id,
            title=title.strip(),
            slug=slug_norm,
            body_markdown=body_markdown,
            status=status,
            published_at=pub_at,  # type: ignore[arg-type]
        )
    except IntegrityError:
        csrf = ensure_csrf_token(request)
        chunk_count = ChunkRepository(sf).count_for_document(doc_id)
        return _TEMPLATES.TemplateResponse(
            request,
            "document_form.html",
            {
                "csrf_token": csrf,
                "doc": existing,
                "chunk_count": chunk_count,
                "error": "Документ с таким slug уже существует.",
                "form": {"title": title, "slug": slug, "body_markdown": body_markdown, "status": status},
                "flash": None,
                "statuses": DOCUMENT_STATUSES,
                "show_nav": True,
            },
            status_code=400,
        )

    assert updated is not None
    _audit(
        sf,
        AUDIT_DOCUMENT_SAVED,
        {"document_id": str(updated.id), "slug": updated.slug, "status": updated.status},
    )
    if status == DOCUMENT_STATUS_PUBLISHED and existing.status != DOCUMENT_STATUS_PUBLISHED:
        _audit(sf, AUDIT_DOCUMENT_PUBLISHED, {"document_id": str(updated.id), "slug": updated.slug})

    settings = _settings(request)
    became_published = (
        status == DOCUMENT_STATUS_PUBLISHED and existing.status != DOCUMENT_STATUS_PUBLISHED
    )
    if settings.features.auto_index_on_publish and became_published:
        rag = _rag(sf, settings)
        t0 = time.perf_counter()
        try:
            rag.reindex_document(doc_id)
            dt_ms = int((time.perf_counter() - t0) * 1000)
            _audit(
                sf,
                AUDIT_DOCUMENT_INDEXED,
                {"document_id": str(doc_id), "slug": updated.slug, "duration_ms": dt_ms, "trigger": "auto_publish"},
            )
        except EmbeddingRequestError:
            dt_ms = int((time.perf_counter() - t0) * 1000)
            _audit(
                sf,
                AUDIT_DOCUMENT_INDEX_FAILED,
                {
                    "document_id": str(doc_id),
                    "slug": updated.slug,
                    "duration_ms": dt_ms,
                    "error": "embedding_request_failed",
                    "trigger": "auto_publish",
                },
            )

    if status != DOCUMENT_STATUS_PUBLISHED:
        _rag(sf, settings).reindex_document(doc_id)

    _flash(request, "Сохранено.")
    return RedirectResponse(f"/documents/{doc_id}/edit", status_code=303)


@router.post("/documents/{doc_id}/publish")
def document_quick_publish(
    request: Request,
    doc_id: uuid.UUID,
    _: None = Depends(admin_required),
    csrf_token: str = Form(...),
) -> RedirectResponse:
    require_csrf(request, csrf_token)
    sf = get_session_factory(request)
    repo = DocumentRepository(sf)
    existing = repo.get_by_id(doc_id)
    if existing is None:
        raise HTTPException(status_code=404)
    if existing.status == DOCUMENT_STATUS_PUBLISHED:
        _flash(request, "Документ уже опубликован.")
        return RedirectResponse(f"/documents/{doc_id}/edit", status_code=303)
    updated = repo.update(
        doc_id,
        status=DOCUMENT_STATUS_PUBLISHED,
        published_at=datetime.now(timezone.utc),
    )
    assert updated is not None
    _audit(sf, AUDIT_DOCUMENT_SAVED, {"document_id": str(doc_id), "slug": updated.slug, "status": updated.status})
    _audit(sf, AUDIT_DOCUMENT_PUBLISHED, {"document_id": str(doc_id), "slug": updated.slug})
    settings = _settings(request)
    if settings.features.auto_index_on_publish:
        rag = _rag(sf, settings)
        t0 = time.perf_counter()
        try:
            rag.reindex_document(doc_id)
            dt_ms = int((time.perf_counter() - t0) * 1000)
            _audit(
                sf,
                AUDIT_DOCUMENT_INDEXED,
                {"document_id": str(doc_id), "slug": updated.slug, "duration_ms": dt_ms, "trigger": "auto_publish"},
            )
        except EmbeddingRequestError:
            dt_ms = int((time.perf_counter() - t0) * 1000)
            _audit(
                sf,
                AUDIT_DOCUMENT_INDEX_FAILED,
                {
                    "document_id": str(doc_id),
                    "slug": updated.slug,
                    "duration_ms": dt_ms,
                    "error": "embedding_request_failed",
                    "trigger": "auto_publish",
                },
            )
    _flash(request, "Опубликовано.")
    return RedirectResponse(f"/documents/{doc_id}/edit", status_code=303)


@router.post("/documents/{doc_id}/unpublish")
def document_quick_unpublish(
    request: Request,
    doc_id: uuid.UUID,
    _: None = Depends(admin_required),
    csrf_token: str = Form(...),
) -> RedirectResponse:
    require_csrf(request, csrf_token)
    sf = get_session_factory(request)
    settings = _settings(request)
    repo = DocumentRepository(sf)
    existing = repo.get_by_id(doc_id)
    if existing is None:
        raise HTTPException(status_code=404)
    repo.update(doc_id, status=DOCUMENT_STATUS_DRAFT, published_at=None)
    _audit(
        sf,
        AUDIT_DOCUMENT_SAVED,
        {"document_id": str(doc_id), "slug": existing.slug, "status": DOCUMENT_STATUS_DRAFT},
    )
    _rag(sf, settings).reindex_document(doc_id)
    _flash(request, "Снято с публикации (черновик).")
    return RedirectResponse(f"/documents/{doc_id}/edit", status_code=303)


@router.post("/documents/{doc_id}/delete")
def document_delete(
    request: Request,
    doc_id: uuid.UUID,
    _: None = Depends(admin_required),
    csrf_token: str = Form(...),
) -> RedirectResponse:
    require_csrf(request, csrf_token)
    sf = get_session_factory(request)
    repo = DocumentRepository(sf)
    doc = repo.get_by_id(doc_id)
    if doc and repo.delete(doc_id):
        _audit(sf, "document_deleted", {"document_id": str(doc_id), "slug": doc.slug})
    _flash(request, "Документ удалён.")
    return RedirectResponse("/documents", status_code=303)


@router.post("/documents/{doc_id}/index")
def document_index(
    request: Request,
    doc_id: uuid.UUID,
    _: None = Depends(admin_required),
    csrf_token: str = Form(...),
) -> RedirectResponse:
    require_csrf(request, csrf_token)
    sf = get_session_factory(request)
    settings = _settings(request)
    doc = DocumentRepository(sf).get_by_id(doc_id)
    if doc is None:
        raise HTTPException(status_code=404)
    if doc.status != DOCUMENT_STATUS_PUBLISHED:
        _flash(request, "Индексация только для опубликованных документов.")
        return RedirectResponse(f"/documents/{doc_id}/edit", status_code=303)
    rag = _rag(sf, settings)
    t0 = time.perf_counter()
    try:
        rag.reindex_document(doc_id)
        dt_ms = int((time.perf_counter() - t0) * 1000)
        _audit(
            sf,
            AUDIT_DOCUMENT_INDEXED,
            {"document_id": str(doc_id), "slug": doc.slug, "duration_ms": dt_ms, "trigger": "manual"},
        )
        _flash(request, f"Индексация завершена за {dt_ms} мс.")
    except EmbeddingRequestError:
        dt_ms = int((time.perf_counter() - t0) * 1000)
        _audit(
            sf,
            AUDIT_DOCUMENT_INDEX_FAILED,
            {
                "document_id": str(doc_id),
                "slug": doc.slug,
                "duration_ms": dt_ms,
                "error": "embedding_request_failed",
                "trigger": "manual",
            },
        )
        _flash(request, "Ошибка индексации (эмбеддинги). Подробности в audit.")
    return RedirectResponse(f"/documents/{doc_id}/edit", status_code=303)


@router.get("/status", response_class=HTMLResponse)
def status_page(request: Request, _: None = Depends(admin_required)) -> HTMLResponse:
    settings = _settings(request)
    engine = _engine(request)
    sf = get_session_factory(request)
    db_ok = check_database(engine)
    vector_ok = False
    if db_ok:
        with engine.connect() as conn:
            row = conn.execute(text("SELECT 1 FROM pg_extension WHERE extname = 'vector' LIMIT 1")).first()
            vector_ok = row is not None
    doc_counts = DocumentRepository(sf).count_by_status()
    chunk_total = ChunkRepository(sf).count_all()
    audit = AuditRepository(sf)
    recent_index = audit.list_recent(limit=20)
    index_events = [r for r in recent_index if r.event_type in (AUDIT_DOCUMENT_INDEXED, AUDIT_DOCUMENT_INDEX_FAILED, AUDIT_REINDEX_ALL, AUDIT_REINDEX_ALL_FAILED)]
    last_job = index_events[0] if index_events else None

    import importlib.metadata

    try:
        app_ver = importlib.metadata.version("vetvopros")
    except importlib.metadata.PackageNotFoundError:
        app_ver = "dev"

    csrf = ensure_csrf_token(request)
    return _TEMPLATES.TemplateResponse(
        request,
        "status.html",
        {
            "db_ok": db_ok,
            "vector_ok": vector_ok,
            "app_ver": app_ver,
            "doc_counts": doc_counts,
            "chunk_total": chunk_total,
            "last_index_job": last_job,
            "auto_index_on_publish": settings.features.auto_index_on_publish,
            "csrf_token": csrf,
            "flash": _pop_flash(request),
            "show_nav": True,
        },
    )


@router.post("/status/reindex-all")
def status_reindex_all(
    request: Request,
    _: None = Depends(admin_required),
    csrf_token: str = Form(...),
    confirm: str = Form(""),
) -> RedirectResponse:
    require_csrf(request, csrf_token)
    if confirm != "yes":
        _flash(request, "Подтвердите переиндексацию (галочка/поле confirm).")
        return RedirectResponse("/status", status_code=303)
    sf = get_session_factory(request)
    settings = _settings(request)
    rag = _rag(sf, settings)
    t0 = time.perf_counter()
    try:
        ok, failed = rag.reindex_all_published()
        dt_ms = int((time.perf_counter() - t0) * 1000)
        _audit(
            sf,
            AUDIT_REINDEX_ALL,
            {"duration_ms": dt_ms, "succeeded": ok, "failed": failed},
        )
        _flash(request, f"Переиндексация: успешно {ok}, ошибок {failed}, {dt_ms} мс.")
    except Exception:
        _log.exception("reindex_all_unexpected")
        dt_ms = int((time.perf_counter() - t0) * 1000)
        _audit(sf, AUDIT_REINDEX_ALL_FAILED, {"duration_ms": dt_ms, "error": "unexpected"})
        _flash(request, "Критическая ошибка при переиндексации. См. audit и логи.")
    return RedirectResponse("/status", status_code=303)


@router.get("/audit", response_class=HTMLResponse)
def audit_page(
    request: Request,
    _: None = Depends(admin_required),
    event_type: str | None = None,
) -> HTMLResponse:
    sf = get_session_factory(request)
    rows = AuditRepository(sf).list_recent(limit=150, event_type=event_type or None)
    csrf = ensure_csrf_token(request)
    return _TEMPLATES.TemplateResponse(
        request,
        "audit.html",
        {
            "rows": rows,
            "filter_event": event_type or "",
            "csrf_token": csrf,
            "flash": _pop_flash(request),
            "show_nav": True,
        },
    )
