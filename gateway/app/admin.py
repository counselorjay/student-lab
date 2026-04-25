"""Admin endpoints — create users, mint keys, revoke keys, dump usage."""

from __future__ import annotations

import csv
import io
import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import make_api_key, require_admin
from .config import get_settings
from .db import get_db
from .models import ApiKey, Request as RequestRow, User


router = APIRouter(prefix="/api/admin", tags=["admin"])


class CreateUserPayload(BaseModel):
    email: str
    name: str
    daily_request_limit: Optional[int] = None
    daily_token_limit: Optional[int] = None
    notes: Optional[str] = None


class CreateKeyPayload(BaseModel):
    label: Optional[str] = None
    expires_at: Optional[datetime] = None


@router.post("/users", status_code=status.HTTP_201_CREATED)
def create_user(
    payload: CreateUserPayload,
    db: Session = Depends(get_db),
    _admin: str = Depends(require_admin),
):
    settings = get_settings()
    existing = db.execute(select(User).where(User.email == str(payload.email).lower())).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(
            status_code=409,
            detail={"error": {"code": "user_exists", "message": "User with that email already exists."}},
        )
    user = User(
        id=str(uuid.uuid4()),
        email=str(payload.email).lower(),
        name=payload.name,
        daily_request_limit=payload.daily_request_limit or settings.default_daily_request_limit,
        daily_token_limit=payload.daily_token_limit or settings.default_daily_token_limit,
        notes=payload.notes,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return {
        "id": user.id,
        "email": user.email,
        "name": user.name,
        "daily_request_limit": user.daily_request_limit,
        "daily_token_limit": user.daily_token_limit,
    }


@router.get("/users")
def list_users(
    db: Session = Depends(get_db),
    _admin: str = Depends(require_admin),
):
    rows = db.execute(select(User).order_by(User.created_at)).scalars().all()
    return [
        {
            "id": u.id,
            "email": u.email,
            "name": u.name,
            "active": bool(u.active),
            "daily_request_limit": u.daily_request_limit,
            "daily_token_limit": u.daily_token_limit,
            "created_at": u.created_at.isoformat() if u.created_at else None,
        }
        for u in rows
    ]


@router.post("/users/{user_id}/keys", status_code=status.HTTP_201_CREATED)
def mint_key(
    user_id: str,
    payload: CreateKeyPayload,
    db: Session = Depends(get_db),
    _admin: str = Depends(require_admin),
):
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(
            status_code=404,
            detail={"error": {"code": "user_not_found", "message": "User not found."}},
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


@router.delete("/keys/{key_id}")
def revoke_key(
    key_id: str,
    db: Session = Depends(get_db),
    _admin: str = Depends(require_admin),
):
    key = db.get(ApiKey, key_id)
    if key is None:
        raise HTTPException(
            status_code=404,
            detail={"error": {"code": "key_not_found", "message": "Key not found."}},
        )
    if key.revoked_at is None:
        key.revoked_at = datetime.utcnow()
        db.commit()
    return {"id": key.id, "revoked_at": key.revoked_at.isoformat()}


@router.get("/usage")
def admin_usage(
    from_: Optional[datetime] = Query(default=None, alias="from"),
    to: Optional[datetime] = Query(default=None),
    fmt: str = Query(default="json"),
    db: Session = Depends(get_db),
    _admin: str = Depends(require_admin),
):
    q = select(RequestRow).order_by(RequestRow.started_at)
    if from_ is not None:
        q = q.where(RequestRow.started_at >= from_)
    if to is not None:
        q = q.where(RequestRow.started_at < to)
    rows = db.execute(q).scalars().all()

    if fmt == "csv":
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(
            [
                "id",
                "user_id",
                "endpoint",
                "model",
                "backend",
                "status_code",
                "prompt_tokens",
                "output_tokens",
                "latency_ms",
                "started_at",
            ]
        )
        for r in rows:
            w.writerow(
                [
                    r.id,
                    r.user_id,
                    r.endpoint,
                    r.model or "",
                    r.backend or "",
                    r.status_code,
                    r.prompt_tokens or 0,
                    r.output_tokens or 0,
                    r.latency_ms,
                    r.started_at.isoformat(),
                ]
            )
        return Response(content=buf.getvalue(), media_type="text/csv")

    return [
        {
            "id": r.id,
            "user_id": r.user_id,
            "endpoint": r.endpoint,
            "model": r.model,
            "backend": r.backend,
            "status_code": r.status_code,
            "prompt_tokens": r.prompt_tokens,
            "output_tokens": r.output_tokens,
            "latency_ms": r.latency_ms,
            "started_at": r.started_at.isoformat(),
        }
        for r in rows
    ]
