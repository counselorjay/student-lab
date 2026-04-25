"""API key auth: happy path, bad format, revoked."""

from __future__ import annotations

from datetime import datetime


def test_me_happy_path(client, seeded_user):
    key = seeded_user["api_key"]
    r = client.get("/api/me", headers={"Authorization": f"Bearer {key}"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["email"] == "alice@example.com"
    assert body["quotas"]["requests_per_day"] == 10
    assert body["used"]["requests_today"] == 0


def test_me_missing_auth(client):
    r = client.get("/api/me")
    assert r.status_code == 401
    assert r.json()["detail"]["error"]["code"] == "missing_auth"


def test_me_bad_format(client):
    r = client.get("/api/me", headers={"Authorization": "Bearer not-a-real-key"})
    assert r.status_code == 401
    assert r.json()["detail"]["error"]["code"] == "bad_key_format"


def test_me_invalid_key(client):
    fake = "slk_" + "0" * 32
    r = client.get("/api/me", headers={"Authorization": f"Bearer {fake}"})
    assert r.status_code == 401
    assert r.json()["detail"]["error"]["code"] == "invalid_key"


def test_revoked_key_rejected(client, seeded_user, db):
    seeded_user["key"].revoked_at = datetime.utcnow()
    db.commit()
    r = client.get(
        "/api/me",
        headers={"Authorization": f"Bearer {seeded_user['api_key']}"},
    )
    assert r.status_code == 401
    assert r.json()["detail"]["error"]["code"] == "invalid_key"


def test_inactive_user_rejected(client, seeded_user, db):
    seeded_user["user"].active = 0
    db.commit()
    r = client.get(
        "/api/me",
        headers={"Authorization": f"Bearer {seeded_user['api_key']}"},
    )
    assert r.status_code == 403
