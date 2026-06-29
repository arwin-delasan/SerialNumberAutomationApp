import os
import csv
import io
import math
import sys
from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from web_app.auth import require_role
from web_app.dependencies import get_db
import web_app.queries as queries

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "serial_exporter"))
from config import SERIAL_COLUMN_HEADER, RANDOM_COLUMN_HEADER

router = APIRouter()
templates = Jinja2Templates(directory=os.path.join(os.path.dirname(__file__), "..", "templates"))

PAGE_SIZE = 100


@router.get("/serials")
def serials_view(
    request: Request,
    page: int = 1,
    sort: str = "desc",
    db=Depends(get_db),
    user=Depends(require_role("view_only")),
):
    rows, total = queries.list_all_serials(db, page, PAGE_SIZE, sort)
    total_pages = max(1, math.ceil(total / PAGE_SIZE))
    bounds = queries.get_serial_bounds(db)

    first_serial = rows[0]["serial_number"] if rows else None
    last_serial = rows[-1]["serial_number"] if rows else None
    min_serial = bounds["min_serial"] if bounds else None
    max_serial = bounds["max_serial"] if bounds else None

    return templates.TemplateResponse(request, "serials/list.html", {
        "rows": rows,
        "page": page,
        "sort": sort,
        "total": total,
        "total_pages": total_pages,
        "first_serial": first_serial,
        "last_serial": last_serial,
        "min_serial": min_serial,
        "max_serial": max_serial,
        "user": user,
    })


@router.post("/serials/{row_id}/toggle-status")
def toggle_serial_status(
    row_id: int,
    db=Depends(get_db),
    user=Depends(require_role("view_actions")),
):
    with db.cursor(dictionary=True) as cur:
        cur.execute("SELECT status FROM session_rows WHERE row_id = %s", (row_id,))
        row = cur.fetchone()
    if not row:
        return JSONResponse({"ok": False, "error": "Row not found"}, status_code=404)
    new_status = "used" if row["status"] == "unused" else "unused"
    queries.update_serial_status(db, row_id, new_status)
    return JSONResponse({"ok": True, "status": new_status})


@router.get("/serials/export")
def serials_export(
    start_serial: int,
    end_serial: int,
    db=Depends(get_db),
    user=Depends(require_role("view_only")),
):
    if (end_serial - start_serial) > 50_000:
        return RedirectResponse("/serials?error=Export+range+cannot+exceed+50,000+serials+at+once", status_code=303)

    def csv_stream():
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow([SERIAL_COLUMN_HEADER, RANDOM_COLUMN_HEADER])
        yield buf.getvalue()
        for row in queries.get_confirmed_rows_in_range(db, start_serial, end_serial):
            buf = io.StringIO()
            writer = csv.writer(buf)
            writer.writerow([row["serial_number"], row["random_number"]])
            yield buf.getvalue()

    return StreamingResponse(
        csv_stream(),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=serials_{start_serial}_to_{end_serial}.csv"},
    )
