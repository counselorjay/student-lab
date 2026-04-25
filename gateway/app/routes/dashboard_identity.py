"""CF-Access-gated identity endpoints for the dashboard.

These let the dashboard render before a student has minted an API key.
Auth comes from the Cf-Access-Authenticated-User-Email header, not Bearer.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import make_api_key, require_cf_access_email
from ..config import get_settings
from ..db import get_db
from ..models import ApiKey, User
from ..quota import get_usage


router = APIRouter(prefix="/api/dashboard", tags=["dashboard-identity"])


class CreateKeyPayload(BaseModel):
    label: Optional[str] = None
    expires_at: Optional[datetime] = None


def _is_admin(email: str) -> bool:
    return email == get_settings().admin_email.strip().lower()


def _user_by_email(db: Session, email: str) -> Optional[User]:
    return db.execute(select(User).where(User.email == email)).scalar_one_or_none()


def _has_active_key(db: Session, user_id: str) -> bool:
    now = datetime.utcnow()
    rows = db.execute(select(ApiKey).where(ApiKey.user_id == user_id)).scalars().all()
    for r in rows:
        if r.revoked_at is not None:
            continue
        if r.expires_at is not None and r.expires_at < now:
            continue
        return True
    return False


@router.get("/whoami")
def whoami(
    email: str = Depends(require_cf_access_email),
    db: Session = Depends(get_db),
):
    user = _user_by_email(db, email)
    if user is None:
        return {
            "email": email,
            "name": None,
            "user_id": None,
            "is_admin": _is_admin(email),
            "has_any_active_key": False,
        }
    return {
        "email": user.email,
        "name": user.name,
        "user_id": user.id,
        "is_admin": _is_admin(user.email),
        "has_any_active_key": _has_active_key(db, user.id),
    }


@router.get("/me")
def dashboard_me(
    email: str = Depends(require_cf_access_email),
    db: Session = Depends(get_db),
):
    user = _user_by_email(db, email)
    if user is None:
        raise HTTPException(
            status_code=404,
            detail={"error": {"code": "user_not_found", "message": "No user record for this email."}},
        )
    usage = get_usage(db, user.id)
    keys = db.execute(select(ApiKey).where(ApiKey.user_id == user.id)).scalars().all()
    return {
        "user_id": user.id,
        "email": user.email,
        "name": user.name,
        "is_admin": _is_admin(user.email),
        "quotas": {
            "requests_per_day": user.daily_request_limit,
            "tokens_per_day": user.daily_token_limit,
        },
        "used": {
            "requests_today": usage.requests_today,
            "tokens_today": usage.tokens_today,
        },
        "keys": [
            {
                "id": k.id,
                "label": k.label,
                "prefix": k.key_prefix,
                "last_used_at": k.last_used_at.isoformat() if k.last_used_at else None,
                "created_at": k.created_at.isoformat() if k.created_at else None,
            }
            for k in keys
        ],
    }


@router.post("/users/me/keys", status_code=status.HTTP_201_CREATED)
def mint_self_key(
    payload: CreateKeyPayload,
    email: str = Depends(require_cf_access_email),
    db: Session = Depends(get_db),
):
    """Admin self-mint from the dashboard. Non-admin emails get 403.

    Students mint keys via /api/admin/users/{id}/keys, which requires Jay.
    """
    if not _is_admin(email):
        raise HTTPException(
            status_code=403,
            detail={"error": {"code": "not_admin", "message": "Only admin can self-mint via this path."}},
        )
    user = _user_by_email(db, email)
    if user is None:
        raise HTTPException(
            status_code=404,
            detail={"error": {"code": "user_not_found", "message": "Admin user record missing; create it first."}},
        )
    full, prefix, hashed = make_api_key()
    key = ApiKey(
        id=str(uuid.uuid4()),
        user_id=user.id,
        key_prefix=prefix,
        key_hash=hashed,
        label=payload.label,
        expires_at=payload.expires_at,
    )
    db.add(key)
    db.commit()
    db.refresh(key)
    return {
        "id": key.id,
        "user_id": user.id,
        "label": key.label,
        "key_prefix": key.key_prefix,
        "api_key": full,  # plaintext, returned ONCE
        "expires_at": key.expires_at.isoformat() if key.expires_at else None,
    }
