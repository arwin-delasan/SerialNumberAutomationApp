import os
import sys
import csv
import io
import subprocess
import threading
import time
from datetime import datetime

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from web_app.auth import require_role
from web_app.csrf import csrf_protect

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "serial_exporter"))
from config import SERIAL_STEP, RANDOM_STEP, QUANTITY_WARN_THRESHOLD, SERIAL_COLUMN_HEADER, RANDOM_COLUMN_HEADER, SESSION_TIMEOUT_MINUTES, LBL_PATH, find_lbl_file
from csv_exporter import write_csv
import web_app.queries as queries
from web_app.db_manager_dep import get_db_manager

router = APIRouter(prefix="/print")
templates = Jinja2Templates(directory=os.path.join(os.path.dirname(__file__), "..", "templates"))

CSV_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "serial_exporter")
CSV_PATH = os.path.join(CSV_DIR, "print_queue.csv")

ZEBRA_PROCESS = "Design.exe"


def _check_active_session(db, conn):
    """Return active session if within timeout, auto-void and return None if expired."""
    active = queries.get_active_session(conn)
    if not active:
        return None
    age_minutes = (datetime.now() - active["created_at"]).total_seconds() / 60
    if age_minutes >= SESSION_TIMEOUT_MINUTES:
        db.void_session(active["session_id"])
        return None
    return active


def _owns(session, user) -> bool:
    """True if this user started the session or is admin."""
    return session["started_by_user_id"] == user["user_id"] or user["role"] == "admin"


def _resolve_lbl_path(conn, user_id: int) -> str:
    """User DB setting > env var (if explicitly set) > auto-discovered > default."""
    db_val = queries.get_setting(conn, user_id, "lbl_path")
    if db_val:
        return db_val
    if LBL_PATH != "ZebraAutomated.lbl":
        return LBL_PATH
    discovered = find_lbl_file()
    return discovered if discovered else LBL_PATH


def _open_label(conn, user_id: int):
    """Open ZebraAutomated.lbl after a 2-second delay. Silent if file not found."""
    path = _resolve_lbl_path(conn, user_id)
    def _delayed():
        time.sleep(2)
        resolved = os.path.abspath(path)
        if os.path.exists(resolved):
            os.startfile(resolved)
    threading.Thread(target=_delayed, daemon=True).start()


def _close_zebra():
    """Kill ZebraDesigner if running. Silent if not found."""
    subprocess.run(["taskkill", "/F", "/IM", ZEBRA_PROCESS], capture_output=True)


def _generate_csv(session: dict) -> tuple:
    start_s = session["serial_range_start"]
    start_r = session["random_range_start"]
    qty = session["quantity_requested"]
    serials = [start_s + i * SERIAL_STEP for i in range(qty)]
    randoms = [start_r + i * RANDOM_STEP for i in range(qty)]
    return serials, randoms


# ---------------------------------------------------------------------------
# Step 1 — Show start form
# ---------------------------------------------------------------------------
@router.get("")
def print_start(
    request: Request,
    error: str = "",
    warn: str = "",
    db=Depends(get_db_manager),
    user=Depends(require_role("view_actions")),
):
    conn = db.connect()
    active = _check_active_session(db, conn)
    if active:
        if _owns(active, user):
            return RedirectResponse(f"/print/confirm/{active['session_id']}", status_code=303)
        # Another user is printing — show locked state
        owner = queries.get_user_by_id(conn, active["started_by_user_id"])
        return templates.TemplateResponse(request, "print/start.html", {
            "seeded": True,
            "next_serial": None,
            "next_random": None,
            "warn_threshold": QUANTITY_WARN_THRESHOLD,
            "error": "",
            "warn": "",
            "user": user,
            "locked_by": owner["username"] if owner else "another user",
            "locked_since": active["created_at"],
            "active_session_id": active["session_id"],
        })

    seeded = db.has_counter()
    next_serial = db.get_next_serial() if seeded else None
    next_random = db.get_next_random() if seeded else None
    return templates.TemplateResponse(request, "print/start.html", {
        "seeded": seeded,
        "next_serial": next_serial,
        "next_random": next_random,
        "warn_threshold": QUANTITY_WARN_THRESHOLD,
        "error": error,
        "warn": warn,
        "user": user,
        "locked_by": None,
        "locked_since": None,
        "active_session_id": None,
    })


# ---------------------------------------------------------------------------
# Step 1 — POST: seed + reserve + generate CSV
# ---------------------------------------------------------------------------
@router.post("/start")
def print_do_start(
    qty: int = Form(...),
    start_serial: int = Form(None),
    start_random: int = Form(None),
    db=Depends(get_db_manager),
    user=Depends(require_role("view_actions")),
    _csrf=Depends(csrf_protect),
):
    conn = db.connect()
    active = _check_active_session(db, conn)
    if active:
        if _owns(active, user):
            return RedirectResponse(f"/print/confirm/{active['session_id']}", status_code=303)
        return RedirectResponse("/print", status_code=303)

    if qty < 1:
        return RedirectResponse("/print?error=Quantity+must+be+at+least+1", status_code=303)
    if qty > 15_000:
        return RedirectResponse("/print?error=Quantity+cannot+exceed+15,000+labels+per+session", status_code=303)

    if not db.has_counter():
        if not start_serial or not start_random:
            return RedirectResponse("/print?error=Starting+serial+and+random+are+required", status_code=303)
        if start_serial < 1 or start_random < 1:
            return RedirectResponse("/print?error=Starting+values+must+be+at+least+1", status_code=303)
        db.seed_counters(start_serial, start_random)

    try:
        session = db.reserve_range(qty, user_id=user["user_id"])
    except RuntimeError:
        conn = db.connect()
        active = queries.get_active_session(conn)
        if active and _owns(active, user):
            return RedirectResponse(f"/print/confirm/{active['session_id']}", status_code=303)
        return RedirectResponse("/print", status_code=303)

    serials, randoms = _generate_csv(session)
    try:
        write_csv(serials, randoms, CSV_PATH)
    except Exception as e:
        import logging
        logging.error("CSV write failed for session %s: %s", session["session_id"], e)
        return RedirectResponse(
            f"/print/confirm/{session['session_id']}?error=CSV+write+failed",
            status_code=303,
        )

    _open_label(conn, user["user_id"])
    return RedirectResponse(f"/print/confirm/{session['session_id']}", status_code=303)


# ---------------------------------------------------------------------------
# Step 2 — Confirmation screen
# ---------------------------------------------------------------------------
@router.get("/confirm/{session_id}")
def print_confirm(
    session_id: int,
    request: Request,
    error: str = "",
    db=Depends(get_db_manager),
    user=Depends(require_role("view_actions")),
):
    conn = db.connect()
    session = queries.get_session(conn, session_id)
    if session is None or session["status"] != "issued":
        return RedirectResponse("/print", status_code=303)
    if not _owns(session, user):
        return RedirectResponse("/print", status_code=303)
    age_minutes = int((datetime.now() - session["created_at"]).total_seconds() / 60)
    return templates.TemplateResponse(request, "print/confirm.html", {
        "session": session,
        "error": error,
        "age_minutes": age_minutes,
        "timeout_minutes": SESSION_TIMEOUT_MINUTES,
        "user": user,
    })


# ---------------------------------------------------------------------------
# Download CSV for this session
# ---------------------------------------------------------------------------
@router.get("/csv/{session_id}")
def print_download_csv(
    session_id: int,
    db=Depends(get_db_manager),
    user=Depends(require_role("view_actions")),
):
    conn = db.connect()
    session = queries.get_session(conn, session_id)
    if session is None or not _owns(session, user):
        return RedirectResponse("/print", status_code=303)

    serials, randoms = _generate_csv(session)

    def stream():
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow([SERIAL_COLUMN_HEADER, RANDOM_COLUMN_HEADER])
        yield buf.getvalue()
        for s, r in zip(serials, randoms):
            buf = io.StringIO()
            writer = csv.writer(buf)
            writer.writerow([s, r])
            yield buf.getvalue()

    filename = f"print_queue_session_{session_id}.csv"
    return StreamingResponse(
        stream(),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


# ---------------------------------------------------------------------------
# Complete
# ---------------------------------------------------------------------------
@router.post("/complete/{session_id}")
def print_complete(
    session_id: int,
    db=Depends(get_db_manager),
    user=Depends(require_role("view_actions")),
    _csrf=Depends(csrf_protect),
):
    conn = db.connect()
    session = queries.get_session(conn, session_id)
    if session and _owns(session, user):
        db.confirm_session(session_id, session["serial_range_end"])
    _close_zebra()
    return RedirectResponse("/print", status_code=303)


# ---------------------------------------------------------------------------
# Incomplete
# ---------------------------------------------------------------------------
@router.post("/incomplete/{session_id}")
def print_incomplete(
    session_id: int,
    last_good_serial: int = Form(...),
    db=Depends(get_db_manager),
    user=Depends(require_role("view_actions")),
    _csrf=Depends(csrf_protect),
):
    conn = db.connect()
    session = queries.get_session(conn, session_id)
    if session is None or not _owns(session, user):
        return RedirectResponse("/print", status_code=303)

    if not (session["serial_range_start"] <= last_good_serial <= session["serial_range_end"]):
        return RedirectResponse(
            f"/print/confirm/{session_id}?error=Serial+{last_good_serial}+is+outside+the+reserved+range",
            status_code=303,
        )

    db.confirm_session(session_id, last_good_serial)
    _close_zebra()
    return RedirectResponse("/print", status_code=303)


# ---------------------------------------------------------------------------
# Void / Cancel
# ---------------------------------------------------------------------------
@router.post("/void/{session_id}")
def print_void(
    session_id: int,
    db=Depends(get_db_manager),
    user=Depends(require_role("view_actions")),
    _csrf=Depends(csrf_protect),
):
    conn = db.connect()
    session = queries.get_session(conn, session_id)
    if session and _owns(session, user):
        db.void_session(session_id)
    _close_zebra()
    return RedirectResponse("/print", status_code=303)
