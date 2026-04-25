"""Inference passthrough + token counting + reserved-model lockout."""

from __future__ import annotations

import json

import pytest
import respx
from httpx import Response


@pytest.mark.asyncio
async def test_chat_passthrough_and_logs(client, seeded_user, db):
    key = seeded_user["api_key"]
    body = {
        "model": "qwen3.5:35b-a3b-nvfp4",
        "messages": [{"role": "user", "content": "hi"}],
        "stream": False,
    }
    upstream = {
        "model": "qwen3.5:35b-a3b-nvfp4",
        "message": {"role": "assistant", "content": "hello"},
        "done": True,
        "prompt_eval_count": 5,
        "eval_count": 7,
    }
    with respx.mock(assert_all_called=False) as m:
        m.post("http://m5-max.test/api/chat").mock(return_value=Response(200, json=upstream))

        r = client.post(
            "/api/chat",
            headers={"Authorization": f"Bearer {key}"},
            json=body,
        )
    assert r.status_code == 200, r.text
    assert r.json()["message"]["content"] == "hello"

    # Log row written.
    from app.models import Request as RequestRow
    rows = db.query(RequestRow).all()
    assert len(rows) == 1
    assert rows[0].endpoint == "/api/chat"
    assert rows[0].backend == "m5-max"
    assert rows[0].prompt_tokens == 5
    assert rows[0].output_tokens == 7
    assert rows[0].status_code == 200


@pytest.mark.asyncio
async def test_reserved_model_blocked(client, seeded_user):
    key = seeded_user["api_key"]
    for tag in ("qwen3.6:35b", "qwen3.6:latest", "qwen3.6:35b-a3b-nvfp4"):
        r = client.post(
            "/api/chat",
            headers={"Authorization": f"Bearer {key}"},
            json={"model": tag, "messages": []},
        )
        assert r.status_code == 403, f"{tag} should be locked"
        assert r.json()["error"]["code"] == "model_locked"


@pytest.mark.asyncio
async def test_quota_enforced(client, seeded_user, db):
    """Crank usage above the limit, expect 429."""
    from datetime import datetime
    from app.models import Request as RequestRow

    user = seeded_user["user"]
    key = seeded_user["key"]
    now = datetime.utcnow()
    for i in range(user.daily_request_limit):
        db.add(
            RequestRow(
                id=f"r{i}",
                user_id=user.id,
                api_key_id=key.id,
                endpoint="/api/chat",
                model="x",
                backend="m5-max",
                status_code=200,
                prompt_tokens=1,
                output_tokens=1,
                latency_ms=1,
                started_at=now,
                ended_at=now,
            )
        )
    db.commit()

    r = client.post(
        "/api/chat",
        headers={"Authorization": f"Bearer {seeded_user['api_key']}"},
        json={"model": "qwen3.5:35b-a3b-nvfp4", "messages": []},
    )
    assert r.status_code == 429
    assert "Retry-After" in r.headers


@pytest.mark.asyncio
async def test_tags_merges_and_dedupes(client, seeded_user):
    key = seeded_user["api_key"]
    with respx.mock(assert_all_called=False) as m:
        m.get("http://m5-max.test/api/tags").mock(
            return_value=Response(200, json={"models": [{"name": "a"}, {"name": "b"}]})
        )
        m.get("http://m5-pro.test/api/tags").mock(
            return_value=Response(200, json={"models": [{"name": "b"}, {"name": "c"}, {"name": "qwen3.6:35b"}]})
        )

        r = client.get("/api/tags", headers={"Authorization": f"Bearer {key}"})
    assert r.status_code == 200
    names = {m["name"] for m in r.json()["models"]}
    assert names == {"a", "b", "c"}  # qwen3.6 filtered out
