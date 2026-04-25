"""Status, /api/me, and /healthz."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from ..auth import AuthedUser, require_api_key
from ..config import get_settings
from ..db import get_db
from ..quota import get_usage
from ..router import BackendRegistry


router = APIRouter(tags=["status"])


def _get_registry(request: Request) -> BackendRegistry:
    return request.app.state.registry


@router.get("/api/status")
async def api_status(request: Request):
    registry = _get_registry(request)
    return {
        "backends": registry.snapshot(),
        "queue": [],  # in-flight per-user list deferred to v2
    }


@router.get("/api/me")
async def api_me(
    db: Session = Depends(get_db),
    authed: AuthedUser = Depends(require_api_key),
):
    u = authed.user
    settings = get_settings()
    usage = get_usage(db, u.id)
    return {
        "user_id": u.id,
        "email": u.email,
        "name": u.name,
        "is_admin": u.email == settings.admin_email.strip().lower(),
        "quotas": {
            "requests_per_day": u.daily_request_limit,
            "tokens_per_day": u.daily_token_limit,
        },
        "used": {
            "requests_today": usage.requests_today,
            "tokens_today": usage.tokens_today,
        },
        "key_prefix": authed.api_key.key_prefix,
    }


@router.get("/healthz")
async def healthz(request: Request):
    registry = _get_registry(request)
    backends = {b["name"]: b["online"] for b in registry.snapshot()}
    return {"ok": True, "backends": backends}
