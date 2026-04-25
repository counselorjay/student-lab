"""Per-user rate limit checks via SQL aggregation against the requests table."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import Request, User


@dataclass
class Usage:
    requests_today: int
    tokens_today: int


@dataclass
class QuotaCheck:
    ok: bool
    usage: Usage
    retry_after_seconds: Optional[int]
    reason: Optional[str]


def _today_window(now: Optional[datetime] = None) -> tuple[datetime, datetime]:
    now = now or datetime.utcnow()
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=1)
    return start, end


def get_usage(db: Session, user_id: str, now: Optional[datetime] = None) -> Usage:
    start, end = _today_window(now)
    row = db.execute(
        select(
            func.count(Request.id),
            func.coalesce(
                func.sum(func.coalesce(Request.prompt_tokens, 0) + func.coalesce(Request.output_tokens, 0)),
                0,
            ),
        ).where(
            Request.user_id == user_id,
            Request.started_at >= start,
            Request.started_at < end,
        )
    ).one()
    return Usage(requests_today=int(row[0] or 0), tokens_today=int(row[1] or 0))


def check_quota(db: Session, user: User, now: Optional[datetime] = None) -> QuotaCheck:
    now = now or datetime.utcnow()
    usage = get_usage(db, user.id, now)
    _, end = _today_window(now)
    retry = int((end - now).total_seconds())

    if usage.requests_today >= user.daily_request_limit:
        return QuotaCheck(False, usage, retry, "daily_request_limit_exceeded")
    if usage.tokens_today >= user.daily_token_limit:
        return QuotaCheck(False, usage, retry, "daily_token_limit_exceeded")
    return QuotaCheck(True, usage, None, None)
