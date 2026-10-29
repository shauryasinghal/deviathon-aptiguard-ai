"""FastAPI dependencies: authenticated user and server-side permission checks."""
from __future__ import annotations

from collections.abc import Callable

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models import User

bearer = HTTPBearer(auto_error=False)


def get_current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(bearer), db: Session = Depends(get_db)
) -> User:
    if creds is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Authentication required", {"WWW-Authenticate": "Bearer"})
    from app.core.security import decode_token

    try:
        payload = decode_token(creds.credentials)
    except jwt.PyJWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token", {"WWW-Authenticate": "Bearer"})
    try:
        user = db.get(User, int(payload["sub"]))
    except (TypeError, ValueError):
        user = None
    if not user or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User inactive or not found")
    if payload.get("tv") != (user.token_version or 0):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session has been revoked; please sign in again")
    return user


def user_permissions(user: User) -> set[str]:
    return {p.code for p in user.role.permissions}


def require(*perms: str) -> Callable[..., User]:
    """Dependency factory: user must hold ALL listed permissions."""

    def _dep(user: User = Depends(get_current_user)) -> User:
        missing = [p for p in perms if p not in user_permissions(user)]
        if missing:
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"Missing permission: {', '.join(missing)}")
        return user

    return _dep
