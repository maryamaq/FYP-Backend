"""utils/auth_utils.py — JWT creation and FastAPI dependency"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt

from config import settings

logger = logging.getLogger(__name__)
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


def create_token(user_id: int, role: str) -> str:
    """Create a signed JWT token encoding user_id and role."""
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.TOKEN_EXPIRE_MINUTES)
    payload = {"sub": str(user_id), "role": role, "exp": expire}
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def decode_token(token: str) -> dict:
    """Decode and validate a JWT. Raises HTTP 401 if invalid or expired."""
    credentials_exc = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        user_id_str: Optional[str] = payload.get("sub")
        role: Optional[str] = payload.get("role")
        if user_id_str is None or role is None:
            raise credentials_exc
        return {"user_id": int(user_id_str), "role": role}
    except JWTError as exc:
        logger.warning("JWT decode error: %s", exc)
        raise credentials_exc


def get_current_user(token: str = Depends(oauth2_scheme)) -> dict:
    """FastAPI dependency — returns current user dict from Bearer token."""
    return decode_token(token)


# ── Authorization helpers (used by the routers) ───────────────────────────
# Rule: the user id and role always come from the signed token, never from
# a value the client sends in the URL or body.

def require_role(*allowed_roles: str):
    """Dependency: user must be logged in AND have one of the allowed roles."""
    def checker(current_user: dict = Depends(get_current_user)) -> dict:
        if current_user["role"] not in allowed_roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                                detail="You do not have permission to do this.")
        return current_user
    return checker


def require_same_user(current_user: dict, user_id: int) -> None:
    """Raise 403 if the user_id in the URL/body is not the logged-in user."""
    if current_user["user_id"] != user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="You can only access your own data.")


def check_session_access(cursor, session_id: int, current_user: dict,
                         allow_assigned_psychologist: bool = False,
                         allow_notified_advisor: bool = False) -> int:
    """
    Make sure the session belongs to the logged-in user. Returns the session owner's user_id.
    If allow_assigned_psychologist is True, a psychologist who has an appointment
    for this session may also access it (read-only screens).
    If allow_notified_advisor is True, an advisor who was notified about this
    session (AdvisorNotifications) may also access it (result screen only).
    Not found and not allowed both give 404, so people cannot guess valid session ids.
    """
    cursor.execute("SELECT user_id FROM Sessions WHERE session_id = ?", (session_id,))
    row = cursor.fetchone()
    if row:
        if row.user_id == current_user["user_id"]:
            return row.user_id
        if allow_assigned_psychologist and current_user["role"] == "psychologist":
            cursor.execute(
                "SELECT 1 FROM Appointments WHERE session_id = ? AND psychologist_id = ?",
                (session_id, current_user["user_id"]),
            )
            if cursor.fetchone():
                return row.user_id
        if allow_notified_advisor and current_user["role"] == "advisor":
            cursor.execute(
                "SELECT 1 FROM AdvisorNotifications WHERE session_id = ? AND advisor_id = ?",
                (session_id, current_user["user_id"]),
            )
            if cursor.fetchone():
                return row.user_id
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found.")


def require_open_session(cursor, session_id: int) -> None:
    """404 if the session does not exist, 409 if it has already ended.
    Call it AFTER check_session_access (which does the ownership check)."""
    cursor.execute("SELECT end_time FROM Sessions WHERE session_id = ?", (session_id,))
    row = cursor.fetchone()
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found.")
    if row.end_time is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Session already ended.")
