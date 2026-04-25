"""Authentication helpers — API key bearer for /api, CF Access header for /dashboard."""

from __future__ import annotations

import secrets
from datetime import datetime
from dataclasses import dataclass
from typing import Optional

import bcrypt
from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import get_settings
from .db import get_db
from .models import ApiKey, User


KEY_PREFIX_LEN = 8
KEY_BODY_HEX_LEN = 32
KEY_PREFIX_TAG = "slk_"


@dataclass
class AuthedUser:
    user: User
    api_key: ApiKey


def make_api_key() -> tuple[str, str, str]:
    """Generate a new API key.

    Returns: (full_key, prefix_for_lookup, bcrypt_hash).
    """
    body = secrets.token_hex(KEY_BODY_HEX_LEN // 2)  # 32 hex chars
    full = f"{KEY_PREFIX_TAG}{body}"
    prefix = full[:KEY_PREFIX_LEN]
    hashed = bcrypt.hashpw(full.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
    return full, prefix, hashed


def verify_key(candidate: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(candidate.encode("utf-8"), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def _error(code: str, message: str, http: int) -> HTTPException:
    return HTTPException(status_code=http, detail={"error": {"code": code, "message": message}})


def require_api_key(
    authorization: Optional[str] = Header(default=None),
    db: Session = Depends(get_db),
) -> AuthedUser:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise _error("missing_auth", "Missing bearer token.", status.HTTP_401_UNAUTHORIZED)
    token = authorization.split(" ", 1)[1].strip()
    if not token.startswith(KEY_PREFIX_TAG) or len(token) < KEY_PREFIX_LEN + 4:
        raise _error("bad_key_format", "Bad API key format.", status.HTTP_401_UNAUTHORIZED)

    prefix = token[:KEY_PREFIX_LEN]
    rows = db.execute(select(ApiKey).where(ApiKey.key_prefix == prefix)).scalars().all()
    now = datetime.utcnow()
    for row in rows:
        if row.revoked_at is not None:
            continue
        if row.expires_at is not None and row.expires_at < now:
            continue
        if not verify_key(token, row.key_hash):
            continue
        user = db.get(User, row.user_id)
        if user is None or user.active != 1:
            raise _error("user_inactive", "User is inactive.", status.HTTP_403_FORBIDDEN)
        row.last_used_at = now
        db.commit()
        return AuthedUser(user=user, api_key=row)

    raise _error("invalid_key", "Invalid or revoked API key.", status.HTTP_401_UNAUTHORIZED)


def require_cf_access_email(
    cf_access_authenticated_user_email: Optional[str] = Header(default=None),
) -> str:
    if not cf_access_authenticated_user_email:
        raise _error(
            "missing_cf_access",
            "This endpoint requires Cloudflare Access.",
            status.HTTP_401_UNAUTHORIZED,
        )
    return cf_access_authenticated_user_email.strip().lower()


def require_admin(
    email: str = Depends(require_cf_access_email),
) -> str:
    settings = get_settings()
    if email != settings.admin_email.strip().lower():
        raise _error("not_admin", "Admin only.", status.HTTP_403_FORBIDDEN)
    return email
