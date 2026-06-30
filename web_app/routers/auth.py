import os
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from web_app.auth import verify_password
from web_app.csrf import csrf_protect
from web_app.dependencies import get_db
import web_app.queries as queries

router = APIRouter()
templates = Jinja2Templates(directory=os.path.join(os.path.dirname(__file__), "..", "templates"))

MAX_ATTEMPTS = 5
LOCKOUT_MINUTES = 1


@router.get("/login")
def login_form(request: Request):
    if request.session.get("user_id"):
        return RedirectResponse("/", status_code=302)
    next_url = request.query_params.get("next", "/")
    return templates.TemplateResponse(request, "login.html", {"next": next_url})


@router.post("/login")
def login_post(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    next: str = Form("/"),
    conn=Depends(get_db),
    _csrf=Depends(csrf_protect),
):
    # Check if currently locked out
    lockout_until = request.session.get("lockout_until")
    if lockout_until:
        remaining = int(lockout_until - datetime.now().timestamp())
        if remaining > 0:
            mins, secs = divmod(remaining, 60)
            msg = f"Too many failed attempts. Try again in {mins}m {secs}s." if mins else f"Too many failed attempts. Try again in {secs}s."
            return templates.TemplateResponse(
                request, "login.html", {"error": msg, "next": next}, status_code=429
            )
        # Cooldown expired — reset
        request.session.pop("lockout_until", None)
        request.session.pop("login_attempts", None)

    # Validate credentials
    user = queries.get_user_by_username(conn, username)
    if not user or not verify_password(password, user["password_hash"]):
        attempts = request.session.get("login_attempts", 0) + 1
        request.session["login_attempts"] = attempts
        if attempts >= MAX_ATTEMPTS:
            request.session["lockout_until"] = (datetime.now() + timedelta(minutes=LOCKOUT_MINUTES)).timestamp()
            request.session.pop("login_attempts", None)
            error = f"Too many failed attempts. Locked out for {LOCKOUT_MINUTES} minutes."
        else:
            left = MAX_ATTEMPTS - attempts
            error = f"Invalid username or password. {left} attempt{'s' if left != 1 else ''} remaining."
        return templates.TemplateResponse(
            request, "login.html", {"error": error, "next": next}, status_code=401
        )

    # Success — clear counters and set session
    request.session.pop("login_attempts", None)
    request.session.pop("lockout_until", None)
    request.session["user_id"] = user["user_id"]
    safe_next = next if next.startswith("/") else "/"
    return RedirectResponse(safe_next, status_code=302)


@router.post("/logout")
def logout(request: Request, _csrf=Depends(csrf_protect)):
    request.session.clear()
    return RedirectResponse("/login", status_code=302)
