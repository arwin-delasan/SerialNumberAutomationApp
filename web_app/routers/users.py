import os
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from web_app.auth import hash_password, require_role
from web_app.csrf import csrf_protect
from web_app.dependencies import get_db
import web_app.queries as queries

router = APIRouter(prefix="/users")
templates = Jinja2Templates(directory=os.path.join(os.path.dirname(__file__), "..", "templates"))

VALID_ROLES = {"view_only", "view_actions", "admin"}


@router.get("")
def users_list(request: Request, conn=Depends(get_db), user=Depends(require_role("admin"))):
    users = queries.list_users(conn)
    return templates.TemplateResponse(request, "users/list.html", {
        "users": users,
        "user": user,
        "error": request.query_params.get("error", ""),
    })


@router.post("/create")
def users_create(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    role: str = Form(...),
    conn=Depends(get_db),
    user=Depends(require_role("admin")),
    _csrf=Depends(csrf_protect),
):
    if role not in VALID_ROLES:
        return RedirectResponse("/users?error=Invalid+role", status_code=303)
    if not username.strip():
        return RedirectResponse("/users?error=Username+cannot+be+empty", status_code=303)
    if len(password) < 8:
        return RedirectResponse("/users?error=Password+must+be+at+least+8+characters", status_code=303)
    existing = queries.get_user_by_username(conn, username.strip())
    if existing:
        return RedirectResponse("/users?error=Username+already+exists", status_code=303)
    queries.create_user(conn, username.strip(), hash_password(password), role)
    return RedirectResponse("/users", status_code=303)


@router.post("/{user_id}/edit")
def users_edit(
    user_id: int,
    request: Request,
    username: str = Form(...),
    role: str = Form(...),
    password: str = Form(""),
    conn=Depends(get_db),
    user=Depends(require_role("admin")),
    _csrf=Depends(csrf_protect),
):
    if role not in VALID_ROLES:
        return RedirectResponse("/users?error=Invalid+role", status_code=303)
    if not username.strip():
        return RedirectResponse("/users?error=Username+cannot+be+empty", status_code=303)
    existing = queries.get_user_by_username(conn, username.strip())
    if existing and existing["user_id"] != user_id:
        return RedirectResponse("/users?error=Username+already+taken", status_code=303)
    hashed = hash_password(password) if password.strip() else None
    queries.update_user(conn, user_id, username.strip(), role, hashed)
    return RedirectResponse("/users", status_code=303)


@router.post("/{user_id}/delete")
def users_delete(
    user_id: int,
    conn=Depends(get_db),
    user=Depends(require_role("admin")),
    _csrf=Depends(csrf_protect),
):
    if user_id == user["user_id"]:
        return RedirectResponse("/users?error=You+cannot+delete+your+own+account", status_code=303)
    target = queries.get_user_by_id(conn, user_id)
    if target and target["role"] == "admin" and queries.count_admins(conn) <= 1:
        return RedirectResponse("/users?error=Cannot+delete+the+last+admin+account", status_code=303)
    queries.delete_user(conn, user_id)
    return RedirectResponse("/users", status_code=303)
