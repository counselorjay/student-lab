"""Middleware-style helper to write a `requests` row after an /api/* call.

We don't actually use Starlette middleware here because route handlers need
to choose backend, model, token counts before logging. Instead each
inference route calls `write_request_log()` once it has the data.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from .models import Request as RequestRow


def write_request_log(
    db: Session,
    *,
    user_id: str,
    api_key_id: str,
    endpoint: str,
    model: Optional[str],
    backend: Optional[str],
    status_code: int,
    prompt_tokens: Optional[int],
    output_tokens: Optional[int],
    started_at: datetime,
    ended_at: datetime,
    error: Optional[str] = None,
) -> RequestRow:
    row = RequestRow(
        id=str(uuid.uuid4()),
        user_id=user_id,
        api_key_id=api_key_id,
        endpoint=endpoint,
        model=model,
        backend=backend,
        status_code=status_code,
        prompt_tokens=prompt_tokens,
        output_tokens=output_tokens,
        latency_ms=int((ended_at - started_at).total_seconds() * 1000),
        started_at=started_at,
        ended_at=ended_at,
        error=error,
    )
    db.add(row)
    db.commit()
    return row
