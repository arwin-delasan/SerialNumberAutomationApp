import os
import sys
from pathlib import Path

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from web_app.auth import require_role
from web_app.csrf import csrf_protect
from web_app.dependencies import get_db
import web_app.queries as queries

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "serial_exporter"))
from config import LBL_PATH, find_lbl_file

router = APIRouter(prefix="/settings")
templates = Jinja2Templates(directory=os.path.join(os.path.dirname(__file__), "..", "templates"))


def _current_lbl_state(conn, user_id: int) -> dict:
    """Return the active lbl_path for this user and its source label."""
    db_val = queries.get_setting(conn, user_id, "lbl_path")
    if db_val:
        return {"path": db_val, "source": "db"}
    if LBL_PATH != "ZebraAutomated.lbl":
        return {"path": LBL_PATH, "source": "env"}
    discovered = find_lbl_file()
    if discovered:
        return {"path": discovered, "source": "auto"}
    return {"path": None, "source": "none"}


@router.get("")
def settings_page(
    request: Request,
    discovered: str = "",
    saved: str = "",
    error: str = "",
    conn=Depends(get_db),
    user=Depends(require_role("view_actions")),
):
    state = _current_lbl_state(conn, user["user_id"])
    return templates.TemplateResponse(request, "settings/index.html", {
        "user": user,
        "lbl_state": state,
        "discovered": discovered or None,
        "saved": saved,
        "error": error,
    })


@router.post("/discover")
def settings_discover(
    request: Request,
    conn=Depends(get_db),
    user=Depends(require_role("view_actions")),
    _csrf=Depends(csrf_protect),
):
    found = find_lbl_file()
    if found:
        return RedirectResponse(f"/settings?discovered={found}", status_code=303)
    return RedirectResponse("/settings?error=ZebraAutomated.lbl+not+found+in+common+locations", status_code=303)


@router.post("/lbl-path")
def settings_save_lbl(
    path: str = Form(""),
    conn=Depends(get_db),
    user=Depends(require_role("view_actions")),
    _csrf=Depends(csrf_protect),
):
    resolved = Path(path.strip()).resolve()
    if not path.strip():
        return RedirectResponse("/settings?error=Path+cannot+be+empty", status_code=303)
    if resolved.suffix.lower() != ".lbl":
        return RedirectResponse("/settings?error=Path+must+point+to+a+.lbl+file", status_code=303)
    if not resolved.exists():
        return RedirectResponse("/settings?error=File+not+found", status_code=303)
    queries.set_setting(conn, user["user_id"], "lbl_path", str(resolved))
    return RedirectResponse("/settings?saved=1", status_code=303)
