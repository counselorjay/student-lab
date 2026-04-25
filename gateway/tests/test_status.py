"""/healthz and /api/status."""

from __future__ import annotations


def test_healthz_no_auth(client):
    r = client.get("/healthz")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert "m5-max" in body["backends"]


def test_status_no_auth(client):
    r = client.get("/api/status")
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body["backends"], list)
    assert any(b["name"] == "m5-max" for b in body["backends"])


def test_dashboard_root_returns_html(client):
    r = client.get("/dashboard/")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")


ADMIN_HDR = {"Cf-Access-Authenticated-User-Email": "jay@counselorjay.com"}


def _mint_via_admin(client, email: str, name: str) -> str:
    r1 = client.post(
        "/api/admin/users",
        json={"email": email, "name": name},
        headers=ADMIN_HDR,
    )
    assert r1.status_code == 201, r1.text
    user_id = r1.json()["id"]
    r2 = client.post(
        f"/api/admin/users/{user_id}/keys",
        json={"label": "test"},
        headers=ADMIN_HDR,
    )
    assert r2.status_code == 201, r2.text
    return r2.json()["api_key"]


def test_api_me_is_admin_true_for_admin_email(client):
    api_key = _mint_via_admin(client, "jay@counselorjay.com", "Jay")
    r = client.get("/api/me", headers={"Authorization": f"Bearer {api_key}"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["email"] == "jay@counselorjay.com"
    assert body["is_admin"] is True


def test_api_me_is_admin_false_for_non_admin(client):
    api_key = _mint_via_admin(client, "alice@example.com", "Alice")
    r = client.get("/api/me", headers={"Authorization": f"Bearer {api_key}"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["email"] == "alice@example.com"
    assert body["is_admin"] is False
