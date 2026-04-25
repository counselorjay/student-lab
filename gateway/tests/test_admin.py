"""Admin endpoint coverage."""

from __future__ import annotations


ADMIN_HDR = {"Cf-Access-Authenticated-User-Email": "jay@counselorjay.com"}
NOT_ADMIN_HDR = {"Cf-Access-Authenticated-User-Email": "alice@example.com"}


def test_create_user_requires_admin(client):
    r = client.post(
        "/api/admin/users",
        json={"email": "bob@example.com", "name": "Bob"},
        headers=NOT_ADMIN_HDR,
    )
    assert r.status_code == 403
    assert r.json()["detail"]["error"]["code"] == "not_admin"


def test_create_user_no_cf_header(client):
    r = client.post(
        "/api/admin/users",
        json={"email": "bob@example.com", "name": "Bob"},
    )
    assert r.status_code == 401


def test_create_user_happy(client):
    r = client.post(
        "/api/admin/users",
        json={"email": "Bob@Example.com", "name": "Bob"},
        headers=ADMIN_HDR,
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["email"] == "bob@example.com"
    assert body["daily_request_limit"] == 200


def test_mint_key_returns_plaintext_once(client):
    r1 = client.post(
        "/api/admin/users",
        json={"email": "carol@example.com", "name": "Carol"},
        headers=ADMIN_HDR,
    )
    user_id = r1.json()["id"]

    r2 = client.post(
        f"/api/admin/users/{user_id}/keys",
        json={"label": "laptop"},
        headers=ADMIN_HDR,
    )
    assert r2.status_code == 201
    body = r2.json()
    assert body["api_key"].startswith("slk_")
    assert len(body["api_key"]) == 4 + 32

    # Now use it.
    r3 = client.get("/api/me", headers={"Authorization": f"Bearer {body['api_key']}"})
    assert r3.status_code == 200
    assert r3.json()["email"] == "carol@example.com"


def test_revoke_key(client):
    r1 = client.post(
        "/api/admin/users",
        json={"email": "dan@example.com", "name": "Dan"},
        headers=ADMIN_HDR,
    )
    user_id = r1.json()["id"]
    r2 = client.post(
        f"/api/admin/users/{user_id}/keys",
        json={"label": "x"},
        headers=ADMIN_HDR,
    )
    key_id = r2.json()["id"]
    api_key = r2.json()["api_key"]

    r3 = client.delete(f"/api/admin/keys/{key_id}", headers=ADMIN_HDR)
    assert r3.status_code == 200

    r4 = client.get("/api/me", headers={"Authorization": f"Bearer {api_key}"})
    assert r4.status_code == 401


def test_admin_usage_csv(client):
    r = client.get("/api/admin/usage?fmt=csv", headers=ADMIN_HDR)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    assert "id,user_id,endpoint" in r.text
