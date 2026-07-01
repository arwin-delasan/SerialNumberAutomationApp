import bcrypt as _bcrypt
from fastapi import Depends, HTTPException, Request
from web_app.dependencies import get_db
import web_app.queries as queries

ROLE_LEVELS = {"view_only": 1, "view_actions": 2, "admin": 3}


def hash_password(password: str) -> str:
    return _bcrypt.hashpw(password.encode(), _bcrypt.gensalt()).decode()


def verify_password(password: str, hashed: str) -> bool:
    return _bcrypt.checkpw(password.encode(), hashed.encode())


class NeedsLogin(Exception):
    def __init__(self, next_url: str = "/"):
        self.next_url = next_url


def require_role(min_role: str):
    def dependency(request: Request, conn=Depends(get_db)):
        user_id = request.session.get("user_id")
        if not user_id:
            raise NeedsLogin(str(request.url.path))
        user = queries.get_user_by_id(conn, user_id)
        if user is None:
            request.session.clear()
            raise NeedsLogin(str(request.url.path))
        if ROLE_LEVELS.get(user["role"], 0) < ROLE_LEVELS[min_role]:
            raise HTTPException(status_code=403, detail="Access denied")
        return user
    return dependency
