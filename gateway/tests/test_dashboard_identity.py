"""CF-Access-gated /api/dashboard/* endpoints."""

from __future__ import annotations


ADMIN_HDR = {"Cf-Access-Authenticated-User-Email": "jay@counselorjay.com"}
NON_ADMIN_HDR = {"Cf-Access-Authenticated-User-Email": "stranger@example.com"}


def _admin_create_user(client, email: str, name: str) -> str:
    r = client.post(
        "/api/admin/users",
        json={"email": email, "name": name},
        headers=ADMIN_HDR,
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _admin_mint_key(client, user_id: str) -> dict:
    r = client.post(
        f"/api/admin/users/{user_id}/keys",
        json={"label": "test"},
        headers=ADMIN_HDR,
    )
    assert r.status_code == 201, r.text
    return r.json()


def test_whoami_unknown_email_returns_admin_check_only(client):
    # Admin email with no User row yet: is_admin true, no keys.
    r = client.get("/api/dashboard/whoami", headers=ADMIN_HDR)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["email"] == "jay@counselorjay.com"
    assert body["is_admin"] is True
    assert body["user_id"] is None
    assert body["name"] is None
    assert body["has_any_active_key"] is False

    # Non-admin email with no User row: is_admin false, no keys.
    r2 = client.get("/api/dashboard/whoami", headers=NON_ADMIN_HDR)
    assert r2.status_code == 200, r2.text
    body2 = r2.json()
    assert body2["email"] == "stranger@example.com"
    assert body2["is_admin"] is False
    assert body2["user_id"] is None
    assert body2["has_any_active_key"] is False


def test_whoami_known_user(client):
    user_id = _admin_create_user(client, "alice@example.com", "Alice")
    _admin_mint_key(client, user_id)

    r = client.get(
        "/api/dashboard/whoami",
        headers={"Cf-Access-Authenticated-User-Email": "alice@example.com"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["email"] == "alice@example.com"
    assert body["name"] == "Alice"
    assert body["user_id"] == user_id
    assert body["is_admin"] is False
    assert body["has_any_active_key"] is True


def test_dashboard_me_returns_keys_no_secrets(client):
    user_id = _admin_create_user(client, "bob@example.com", "Bob")
    minted = _admin_mint_key(client, user_id)
    plaintext = minted["api_key"]

    r = client.get(
        "/api/dashboard/me",
        headers={"Cf-Access-Authenticated-User-Email": "bob@example.com"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["email"] == "bob@example.com"
    assert body["user_id"] == user_id
    assert body["is_admin"] is False
    assert "quotas" in body and "used" in body
    assert isinstance(body["keys"], list)
    assert len(body["keys"]) == 1
    k = body["keys"][0]
    assert set(k.keys()) == {"id", "label", "prefix", "last_used_at", "created_at"}
    # No plaintext anywhere in the body.
    assert plaintext not in r.text
    # Sanity: 404 for an email with no user row.
    r2 = client.get(
        "/api/dashboard/me",
        headers={"Cf-Access-Authenticated-User-Email": "ghost@example.com"},
    )
    assert r2.status_code == 404


def test_dashboard_self_mint_admin_only(client):
    # Non-admin email, even with a User row, gets 403.
    _admin_create_user(client, "carol@example.com", "Carol")
    r = client.post(
        "/api/dashboard/users/me/keys",
        json={"label": "laptop"},
        headers={"Cf-Access-Authenticated-User-Email": "carol@example.com"},
    )
    assert r.status_code == 403
    assert r.json()["detail"]["error"]["code"] == "not_admin"

    # Admin without a User row yet: 404 (admin must be created first via /api/admin/users).
    r_missing = client.post(
        "/api/dashboard/users/me/keys",
        json={"label": "laptop"},
        headers=ADMIN_HDR,
    )
    assert r_missing.status_code == 404

    # Create admin user, then self-mint succeeds.
    _admin_create_user(client, "jay@counselorjay.com", "Jay")
    r_ok = client.post(
        "/api/dashboard/users/me/keys",
        json={"label": "laptop"},
        headers=ADMIN_HDR,
    )
    assert r_ok.status_code == 201, r_ok.text
    body = r_ok.json()
    assert body["api_key"].startswith("slk_")
    assert body["label"] == "laptop"
    # And the minted key works against /api/me.
    r_me = client.get("/api/me", headers={"Authorization": f"Bearer {body['api_key']}"})
    assert r_me.status_code == 200
    assert r_me.json()["is_admin"] is True
