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
    db=Depends(get_db),
    user=Depends(require_role("view_only")),
):
    rows, total = queries.list_sessions(db, page, PAGE_SIZE)
    total_pages = max(1, math.ceil(total / PAGE_SIZE))
    return templates.TemplateResponse(request, "sessions.html", {
        "sessions": rows,
        "page": page,
        "total_pages": total_pages,
        "total": total,
        "user": user,
    })


@router.get("/sessions/{session_id}")
def session_detail(
    session_id: int,
    request: Request,
    db=Depends(get_db),
    user=Depends(require_role("view_only")),
):
    session = queries.get_session(db, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    rows = queries.get_session_rows(db, session_id)
    return templates.TemplateResponse(request, "session_detail.html", {
        "session": session,
        "rows": rows,
        "user": user,
    })
