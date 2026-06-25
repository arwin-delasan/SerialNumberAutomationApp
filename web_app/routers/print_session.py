import os
import sys
import csv
import io

from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "serial_exporter"))
from config import SERIAL_STEP, RANDOM_STEP, QUANTITY_WARN_THRESHOLD, SERIAL_COLUMN_HEADER, RANDOM_COLUMN_HEADER
from csv_exporter import write_csv
import web_app.queries as queries
from web_app.db_manager_dep import get_db_manager

router = APIRouter(prefix="/print")
templates = Jinja2Templates(directory=os.path.join(os.path.dirname(__file__), "..", "templates"))

# CSV dir: same folder as the .lbl file so ZebraDesigner finds it
CSV_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "serial_exporter")


def _build_csv_path(session_id: int) -> str:
    return os.path.join(CSV_DIR, f"print_queue.csv")


def _generate_csv(session: dict) -> tuple[list[int], list[int]]:
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
def print_start(request: Request, error: str = "", warn: str = "", db=Depends(get_db_manager)):
    seeded = db.has_counter()
    next_serial = db.get_next_serial() if seeded else None
    next_random = db.get_next_random() if seeded else None
    return templates.TemplateResponse(request, "print_start.html", {
        "seeded": seeded,
        "next_serial": next_serial,
        "next_random": next_random,
        "warn_threshold": QUANTITY_WARN_THRESHOLD,
        "error": error,
        "warn": warn,
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
):
    if qty < 1:
        return RedirectResponse("/print?error=Quantity+must+be+at+least+1", status_code=303)

    if not db.has_counter():
        if not start_serial or not start_random:
            return RedirectResponse("/print?error=Starting+serial+and+random+are+required", status_code=303)
        if start_serial < 1 or start_random < 1:
            return RedirectResponse("/print?error=Starting+values+must+be+at+least+1", status_code=303)
        db.seed_counters(start_serial, start_random)

    session = db.reserve_range(qty)
    serials, randoms = _generate_csv(session)

    try:
        write_csv(serials, randoms, _build_csv_path(session["session_id"]))
    except Exception as e:
        pass  # CSV write failure is non-blocking; user can still confirm/void

    return RedirectResponse(f"/print/confirm/{session['session_id']}", status_code=303)


# ---------------------------------------------------------------------------
# Step 2 — Confirmation screen
# ---------------------------------------------------------------------------
@router.get("/confirm/{session_id}")
def print_confirm(session_id: int, request: Request, error: str = "", db=Depends(get_db_manager)):
    conn = db.connect()
    session = queries.get_session(conn, session_id)
    if session is None or session["status"] != "issued":
        return RedirectResponse("/print", status_code=303)
    return templates.TemplateResponse(request, "print_confirm.html", {
        "session": session,
        "error": error,
    })


# ---------------------------------------------------------------------------
# Download CSV for this session
# ---------------------------------------------------------------------------
@router.get("/csv/{session_id}")
def print_download_csv(session_id: int, db=Depends(get_db_manager)):
    conn = db.connect()
    session = queries.get_session(conn, session_id)
    if session is None:
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
def print_complete(session_id: int, db=Depends(get_db_manager)):
    conn = db.connect()
    session = queries.get_session(conn, session_id)
    if session:
        db.confirm_session(session_id, session["serial_range_end"])
    return RedirectResponse("/print", status_code=303)


# ---------------------------------------------------------------------------
# Incomplete
# ---------------------------------------------------------------------------
@router.post("/incomplete/{session_id}")
def print_incomplete(session_id: int, last_good_serial: int = Form(...), db=Depends(get_db_manager)):
    conn = db.connect()
    session = queries.get_session(conn, session_id)
    if session is None:
        return RedirectResponse("/print", status_code=303)

    if not (session["serial_range_start"] <= last_good_serial <= session["serial_range_end"]):
        return RedirectResponse(
            f"/print/confirm/{session_id}?error=Serial+{last_good_serial}+is+outside+the+reserved+range",
            status_code=303,
        )

    db.confirm_session(session_id, last_good_serial)
    return RedirectResponse("/print", status_code=303)


# ---------------------------------------------------------------------------
# Void / Cancel
# ---------------------------------------------------------------------------
@router.post("/void/{session_id}")
def print_void(session_id: int, db=Depends(get_db_manager)):
    db.void_session(session_id)
    return RedirectResponse("/print", status_code=303)
