"""Password hashing and JWT session tokens."""

from __future__ import annotations

from datetime import datetime
from datetime import timedelta
from datetime import timezone
from typing import Any
from typing import Dict
from typing import Optional

import jwt
from fastapi import Depends
from fastapi import HTTPException
from fastapi import status
from fastapi.security import HTTPAuthorizationCredentials
from fastapi.security import HTTPBearer
from passlib.context import CryptContext

from . import config
from . import db as db_mod

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
bearer_scheme = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return pwd_context.verify(password, password_hash)


def create_access_token(*, user_id: int, username: str, role: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "username": username,
        "role": role,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=config.TOKEN_TTL_SECONDS)).timestamp()),
    }
    return jwt.encode(payload, config.SESSION_SECRET, algorithm="HS256")


def decode_access_token(token: str) -> Dict[str, Any]:
    try:
        return jwt.decode(token, config.SESSION_SECRET, algorithms=["HS256"])
    except jwt.PyJWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired session.",
        ) from exc


def public_user(row: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": row["id"],
        "username": row["username"],
        "role": row["role"],
        "email": row.get("email"),
        "status": (row.get("status") or db_mod.DEFAULT_USER_STATUS),
    }


def user_is_approved(row: Dict[str, Any]) -> bool:
    return str(row.get("status") or "").strip().lower() == "approved"


def assert_user_approved(row: Dict[str, Any]) -> None:
    status_key = str(row.get("status") or "").strip().lower()
    if status_key == "approved":
        return
    if status_key == "pending":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is pending approval.",
        )
    if status_key == "rejected":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account was rejected.",
        )
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Account is not approved.",
    )


def seed_admin_user_if_needed() -> None:
    if db_mod.count_users() > 0:
        return
    if not config.SEED_PASSWORD:
        raise RuntimeError(
            "No users in DB and UPLOAD_SEED_PASSWORD is unset. "
            "Copy backend/.env.example to backend/.env and set credentials."
        )
    db_mod.create_user(
        username=config.SEED_USERNAME,
        password_hash=hash_password(config.SEED_PASSWORD),
        role="admin",
        status="approved",
    )


async def require_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
) -> Dict[str, Any]:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required.",
        )
    payload = decode_access_token(credentials.credentials)
    try:
        user_id = int(payload.get("sub") or 0)
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid session subject.",
        ) from exc
    user = db_mod.get_user_by_id(user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User no longer exists.",
        )
    assert_user_approved(user)
    return user


def _is_worker_token(raw: str) -> bool:
    expected = config.WORKER_API_TOKEN
    return bool(expected) and raw == expected


async def require_user_or_worker(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
) -> Dict[str, Any]:
    """Human JWT session or shared WORKER_API_TOKEN for service-to-service calls."""
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required.",
        )
    token = credentials.credentials
    if _is_worker_token(token):
        return {"id": 0, "username": "worker", "role": "worker", "is_worker": True}
    user = await require_user(credentials)
    user = dict(user)
    user["is_worker"] = False
    return user
