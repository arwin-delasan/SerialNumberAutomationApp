import os
import sys
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from web_app.routers import dashboard, sessions, export, serials, print_session
from web_app.routers import auth as auth_router, users as users_router, settings as settings_router
from web_app.db_manager_dep import DatabaseManager, MYSQL_CONFIG
from web_app.auth import NeedsLogin, seed_default_admin

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "serial_exporter"))
from config import SESSION_SECRET_KEY


@asynccontextmanager
async def lifespan(app: FastAPI):
    db = DatabaseManager(MYSQL_CONFIG)
    db.init_db()
    seed_default_admin(db)
    db.close()
    yield


app = FastAPI(title="Serial Management", lifespan=lifespan)

app.add_middleware(SessionMiddleware, secret_key=SESSION_SECRET_KEY)

templates = Jinja2Templates(directory=os.path.join(os.path.dirname(__file__), "templates"))

app.include_router(auth_router.router)
app.include_router(dashboard.router)
app.include_router(sessions.router)
app.include_router(export.router)
app.include_router(serials.router)
app.include_router(print_session.router)
app.include_router(users_router.router)
app.include_router(settings_router.router)


@app.exception_handler(NeedsLogin)
async def needs_login(request: Request, exc: NeedsLogin):
    return RedirectResponse(f"/login?next={exc.next_url}", status_code=302)


@app.exception_handler(403)
async def forbidden(request: Request, exc):
    return templates.TemplateResponse(
        request, "error.html",
        {"code": 403, "message": "You don't have permission to access this page", "user": None},
        status_code=403,
    )


@app.exception_handler(404)
async def not_found(request: Request, exc):
    return templates.TemplateResponse(
        request, "error.html",
        {"code": 404, "message": "Page not found", "user": None},
        status_code=404,
    )


@app.exception_handler(500)
async def server_error(request: Request, exc):
    return templates.TemplateResponse(
        request, "error.html",
        {"code": 500, "message": "Internal server error", "user": None},
        status_code=500,
    )
