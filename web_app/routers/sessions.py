import os
import math
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.templating import Jinja2Templates
from web_app.auth import require_role
from web_app.dependencies import get_db
import web_app.queries as queries

router = APIRouter()
templates = Jinja2Templates(directory=os.path.join(os.path.dirname(__file__), "..", "templates"))

PAGE_SIZE = 25


@router.get("/sessions")
def sessions_list(
    request: Request,
    page: int = 1,
    search: str = None,
    status_filter: str = None,
    db=Depends(get_db),
    user=Depends(require_role("view_only")),
):
    page = max(1, page)
    search = search.strip() if search and search.strip() else None
    if status_filter not in ("issued", "confirmed", "partial", "voided"):
        status_filter = None
    rows, total = queries.list_sessions(db, page, PAGE_SIZE, search=search, status_filter=status_filter)
    total_pages = max(1, math.ceil(total / PAGE_SIZE))
    return templates.TemplateResponse(request, "sessions/list.html", {
        "sessions": rows,
        "page": page,
        "total_pages": total_pages,
        "total": total,
        "search": search,
        "status_filter": status_filter,
        "user": user,
    })


DETAIL_PAGE_SIZE = 100


@router.get("/sessions/{session_id}")
def session_detail(
    session_id: int,
    request: Request,
    page: int = 1,
    db=Depends(get_db),
    user=Depends(require_role("view_only")),
):
    page = max(1, page)
    session = queries.get_session(db, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    rows, total_rows = queries.get_session_rows_paged(db, session_id, page, DETAIL_PAGE_SIZE)
    total_pages = max(1, math.ceil(total_rows / DETAIL_PAGE_SIZE))
    return templates.TemplateResponse(request, "sessions/detail.html", {
        "session": session,
        "rows": rows,
        "total_rows": total_rows,
        "page": page,
        "total_pages": total_pages,
        "user": user,
    })
