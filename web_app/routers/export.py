import os
import csv
import io
import sys
from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from web_app.auth import require_role
from web_app.dependencies import get_db
import web_app.queries as queries

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "serial_exporter"))
from config import SERIAL_COLUMN_HEADER, RANDOM_COLUMN_HEADER

router = APIRouter()
templates = Jinja2Templates(directory=os.path.join(os.path.dirname(__file__), "..", "templates"))


@router.get("/export")
def export_form(request: Request, error: str = "", user=Depends(require_role("view_only"))):
    return templates.TemplateResponse(request, "serials/export.html", {"error": error, "user": user})


@router.get("/export/download")
def export_download(
    start_serial: int,
    end_serial: int,
    db=Depends(get_db),
    user=Depends(require_role("view_only")),
):
    if start_serial > end_serial:
        return RedirectResponse(url="/export?error=Start+serial+must+be+less+than+or+equal+to+end+serial")
    if (end_serial - start_serial) >= 15_000:
        return RedirectResponse(url="/export?error=Export+range+cannot+exceed+15,000+serials+at+once")

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
        headers={"Content-Disposition": "attachment; filename=export.csv"},
    )
