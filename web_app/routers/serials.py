import os
import csv
import io
import math
from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from fastapi.templating import Jinja2Templates
from web_app.dependencies import get_db
import web_app.queries as queries

sys_path_dir = os.path.join(os.path.dirname(__file__), "..", "..", "serial_exporter")
import sys
sys.path.insert(0, sys_path_dir)
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
):
    rows, total = queries.list_all_serials(db, page, PAGE_SIZE, sort)
    total_pages = max(1, math.ceil(total / PAGE_SIZE))
    bounds = queries.get_serial_bounds(db)

    first_serial = rows[0]["serial_number"] if rows else None
    last_serial = rows[-1]["serial_number"] if rows else None
    min_serial = bounds["min_serial"] if bounds else None
    max_serial = bounds["max_serial"] if bounds else None

    return templates.TemplateResponse(request, "serials.html", {
        "rows": rows,
        "page": page,
        "sort": sort,
        "total": total,
        "total_pages": total_pages,
        "first_serial": first_serial,
        "last_serial": last_serial,
        "min_serial": min_serial,
        "max_serial": max_serial,
    })


@router.get("/serials/export")
def serials_export(start_serial: int, end_serial: int, db=Depends(get_db)):
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
