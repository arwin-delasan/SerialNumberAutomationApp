import secrets
from fastapi import HTTPException, Request


def get_csrf_token(request: Request) -> str:
    if "csrf_token" not in request.session:
        request.session["csrf_token"] = secrets.token_hex(32)
    return request.session["csrf_token"]


async def csrf_protect(request: Request):
    session_token = request.session.get("csrf_token", "")
    if not session_token:
        raise HTTPException(status_code=403, detail="CSRF token missing")
    header_token = request.headers.get("X-CSRF-Token", "")
    if header_token:
        if not secrets.compare_digest(header_token, session_token):
            raise HTTPException(status_code=403, detail="Invalid CSRF token")
        return
    form = await request.form()
    form_token = form.get("_csrf", "")
    if not secrets.compare_digest(form_token, session_token):
        raise HTTPException(status_code=403, detail="Invalid CSRF token")
