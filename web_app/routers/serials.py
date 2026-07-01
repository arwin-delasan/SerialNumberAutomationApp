import os
import csv
import io
import math
from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from web_app.auth import require_role
from web_app.csrf import csrf_protect
from web_app.dependencies import get_db
import web_app.queries as queries

from web_app.config import SERIAL_COLUMN_HEADER, RANDOM_COLUMN_HEADER

router = APIRouter()
templates = Jinja2Templates(directory=os.path.join(os.path.dirname(__file__), "..", "templates"))

PAGE_SIZE = 100


@router.get("/serials")
def serials_view(
    request: Request,
    page: int = 1,
    sort: str = "desc",
    search: str = None,
    status_filter: str = None,
    db=Depends(get_db),
    user=Depends(require_role("view_only")),
):
    page = max(1, page)
    if status_filter not in ("used", "unused"):
        status_filter = None
    search = search.strip() if search and search.strip() else None
    rows, total = queries.list_all_serials(
        db, page, PAGE_SIZE, sort,
        search=search,
        status_filter=status_filter,
    )
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
        "search": search,
        "status_filter": status_filter,
        "total": total,
        "total_pages": total_pages,
        "first_serial": first_serial,
        "last_serial": last_serial,
        "min_serial": min_serial,
        "max_serial": max_serial,
        "user": user,
    })


@router.post("/serials/bulk-status")
async def bulk_serial_status(
    request: Request,
    db=Depends(get_db),
    user=Depends(require_role("view_actions")),
    _csrf=Depends(csrf_protect),
):
    body = await request.json()
    status = body.get("status")
    ranges = body.get("ranges", [])
    serials = body.get("serials", [])

    if status not in ("used", "unused"):
        return JSONResponse({"ok": False, "error": "Invalid status"}, status_code=400)

    for r in ranges:
        if not isinstance(r.get("start"), int) or not isinstance(r.get("end"), int):
            return JSONResponse({"ok": False, "error": "Invalid range values"}, status_code=400)
        if r["start"] > r["end"]:
            return JSONResponse({"ok": False, "error": f"Range start {r['start']} must be ≤ end {r['end']}"}, status_code=400)

    try:
        serials = [int(s) for s in serials]
    except (ValueError, TypeError):
        return JSONResponse({"ok": False, "error": "Invalid serial numbers"}, status_code=400)

    if not ranges and not serials:
        return JSONResponse({"ok": False, "error": "No ranges or serials provided"}, status_code=400)

    affected = queries.bulk_update_serial_status(db, ranges, serials, status)
    return JSONResponse({"ok": True, "affected": affected})


@router.post("/serials/{row_id}/toggle-status")
def toggle_serial_status(
    row_id: int,
    db=Depends(get_db),
    user=Depends(require_role("view_actions")),
    _csrf=Depends(csrf_protect),
):
    cur = db.cursor()
    cur.execute("SELECT status FROM session_rows WHERE row_id = ?", (row_id,))
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
    status_filter: str = None,
    db=Depends(get_db),
    user=Depends(require_role("view_only")),
):
    if (end_serial - start_serial) >= 15_000:
        return RedirectResponse("/serials?error=Export+range+cannot+exceed+15,000+serials+at+once", status_code=303)
    if status_filter not in ("used", "unused"):
        status_filter = None

    def csv_stream():
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow([SERIAL_COLUMN_HEADER, RANDOM_COLUMN_HEADER])
        yield buf.getvalue()
        for row in queries.get_confirmed_rows_in_range(db, start_serial, end_serial, status_filter):
            buf = io.StringIO()
            writer = csv.writer(buf)
            writer.writerow([row["serial_number"], row["random_number"]])
            yield buf.getvalue()

    suffix = f"_{status_filter}" if status_filter else ""
    return StreamingResponse(
        csv_stream(),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=serials_{start_serial}_to_{end_serial}{suffix}.csv"},
    )
