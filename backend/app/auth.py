"""JWT authentication utilities and get_current_user FastAPI dependency."""

import os
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
import bcrypt as _bcrypt
from jose import JWTError, jwt
from sqlmodel import Session

from app.database import get_session
from app.table_models import User

# ── Config (loaded from .env via python-dotenv in main.py) ───────────────────

JWT_SECRET: str = os.getenv("JWT_SECRET", "dev-secret-change-in-production")
JWT_ALGORITHM: str = os.getenv("JWT_ALGORITHM", "HS256")
JWT_EXPIRE_HOURS: int = int(os.getenv("JWT_EXPIRE_HOURS", "8"))

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/token")


# ── Password helpers (bcrypt directly — avoids passlib/bcrypt 5.x compat issue) ──

def hash_password(plain: str) -> str:
    return _bcrypt.hashpw(plain.encode(), _bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    return _bcrypt.checkpw(plain.encode(), hashed.encode())


# ── Token helpers ─────────────────────────────────────────────────────────────

def create_access_token(data: dict) -> str:
    payload = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(hours=JWT_EXPIRE_HOURS)
    payload["exp"] = expire
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


# ── FastAPI dependency ────────────────────────────────────────────────────────

def get_current_user(
    token: str = Depends(oauth2_scheme),
    session: Session = Depends(get_session),
) -> User:
    """Decode the Bearer token and return the User from the database.

    Raises 401 if the token is missing, invalid, expired, or refers to a
    deleted user.
    """
    credentials_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired token",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        user_id: Optional[int] = payload.get("user_id")
        if user_id is None:
            raise credentials_error
    except JWTError:
        raise credentials_error

    user = session.get(User, user_id)
    if user is None:
        raise credentials_error
    return user


# ── Role/property scoping helper ─────────────────────────────────────────────

def property_scope(user: User) -> Optional[str]:
    """Return the property_code to filter by, or None for unscoped (admin) access."""
    if user.role == "admin" or user.property_code is None:
        return None
    return user.property_code.upper()
