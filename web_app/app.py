import logging
import os
import sys
from contextlib import asynccontextmanager
from fastapi import Depends, FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from web_app.routers import dashboard, sessions, export, serials, print_session
from web_app.routers import auth as auth_router, users as users_router, settings as settings_router
from web_app.db_manager_dep import DatabaseManager, MYSQL_CONFIG
from web_app.auth import NeedsLogin
from web_app.csrf import get_csrf_token
from web_app.dependencies import init_pool

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "serial_exporter"))
from config import SESSION_SECRET_KEY


@asynccontextmanager
async def lifespan(app: FastAPI):
    if SESSION_SECRET_KEY == "change-me-in-production-32chars!":
        import warnings
        warnings.warn(
            "SESSION_SECRET_KEY is using the default weak value — set it in .env before deploying!",
            stacklevel=2,
        )
    db = DatabaseManager(MYSQL_CONFIG)
    db.init_db()
    db.close()
    init_pool()
    yield


app = FastAPI(title="Serial Management", lifespan=lifespan, dependencies=[Depends(get_csrf_token)])

app.mount("/static", StaticFiles(directory=os.path.join(os.path.dirname(__file__), "static")), name="static")
app.add_middleware(SessionMiddleware, secret_key=SESSION_SECRET_KEY, same_site="lax")

templates = Jinja2Templates(directory=os.path.join(os.path.dirname(__file__), "templates"))

app.include_router(auth_router.router)
app.include_router(dashboard.router)
app.include_router(sessions.router)
app.include_router(export.router)
app.include_router(serials.router)
app.include_router(print_session.router)
app.include_router(users_router.router)
app.include_router(settings_router.router)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "same-origin"
    return response


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
    logging.exception("Unhandled 500 on %s: %s", request.url.path, exc)
    return templates.TemplateResponse(
        request, "error.html",
        {"code": 500, "message": "Internal server error", "user": None},
        status_code=500,
    )
