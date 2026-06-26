import os
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from web_app.routers import dashboard, sessions, export, serials, print_session
from web_app.db_manager_dep import DatabaseManager, MYSQL_CONFIG


@asynccontextmanager
async def lifespan(app: FastAPI):
    db = DatabaseManager(MYSQL_CONFIG)
    db.init_db()
    db.close()
    yield


app = FastAPI(title="Serial Management", lifespan=lifespan)

templates = Jinja2Templates(directory=os.path.join(os.path.dirname(__file__), "templates"))

app.include_router(dashboard.router)
app.include_router(sessions.router)
app.include_router(export.router)
app.include_router(serials.router)
app.include_router(print_session.router)


@app.exception_handler(404)
async def not_found(request: Request, exc):
    return templates.TemplateResponse(request, "error.html", {"code": 404, "message": "Page not found"}, status_code=404)


@app.exception_handler(500)
async def server_error(request: Request, exc):
    return templates.TemplateResponse(request, "error.html", {"code": 500, "message": "Internal server error"}, status_code=500)
