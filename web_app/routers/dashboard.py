import os
from fastapi import APIRouter, Depends, Request
from fastapi.templating import Jinja2Templates
from web_app.auth import require_role
from web_app.dependencies import get_db
import web_app.queries as queries

router = APIRouter()
templates = Jinja2Templates(directory=os.path.join(os.path.dirname(__file__), "..", "templates"))


@router.get("/")
def dashboard(request: Request, db=Depends(get_db), user=Depends(require_role("view_only"))):
    counter = queries.get_counter_state(db)
    stats = queries.get_dashboard_stats(db)
    recent = queries.get_recent_sessions(db, limit=10)
    return templates.TemplateResponse(request, "dashboard.html", {
        "counter": counter,
        "stats": stats,
        "recent": recent,
        "user": user,
    })
