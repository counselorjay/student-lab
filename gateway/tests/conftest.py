"""Pytest fixtures: in-memory SQLite, seeded user + key, FastAPI client."""

from __future__ import annotations

import uuid
from typing import Iterator

import pytest
from fastapi.testclient import TestClient

from app import db as db_module
from app.auth import make_api_key
from app.config import Settings, set_settings_for_test
from app.models import ApiKey, User
from app.router import BackendRegistry


@pytest.fixture(autouse=True)
def _settings() -> Iterator[Settings]:
    s = Settings(
        admin_email="jay@counselorjay.com",
        backend_m5_max="http://m5-max.test",
        backend_m5_pro="http://m5-pro.test",
        db_path=":memory:",
        health_probe_interval=3600,
    )
    set_settings_for_test(s)
    yield s


@pytest.fixture
def db():
    db_module.reset_for_test("sqlite:///:memory:")
    yield db_module.get_session_factory()()


@pytest.fixture
def seeded_user(db):
    user = User(
        id=str(uuid.uuid4()),
        email="alice@example.com",
        name="Alice",
        daily_request_limit=10,
        daily_token_limit=10000,
    )
    db.add(user)
    full, prefix, hashed = make_api_key()
    key = ApiKey(
        id=str(uuid.uuid4()),
        user_id=user.id,
        key_prefix=prefix,
        key_hash=hashed,
        label="test",
    )
    db.add(key)
    db.commit()
    return {"user": user, "key": key, "api_key": full}


@pytest.fixture
def seeded_admin(db):
    user = User(
        id=str(uuid.uuid4()),
        email="jay@counselorjay.com",
        name="Jay",
        daily_request_limit=1000,
        daily_token_limit=10_000_000,
    )
    db.add(user)
    db.commit()
    return user


@pytest.fixture
def client(_settings, db) -> Iterator[TestClient]:
    """Build the app without lifespan probes; install a fake registry."""
    from app.main import create_app

    app = create_app()
    # Bypass lifespan side effects by setting state up front and using TestClient
    # without entering the lifespan context. We do that by avoiding `with TestClient`.
    registry = BackendRegistry(_settings)
    for b in registry.backends.values():
        b.online = True
        b.models_loaded = [
            "qwen3.5:35b-a3b-nvfp4",
            "gemma4:13b",
            "gemma4:e4b",
            "nomic-embed-text",
        ]
    app.state.registry = registry

    # Don't trigger lifespan; just yield the client.
    tc = TestClient(app, raise_server_exceptions=True)
    # Manually skip lifespan startup by not using `with`.
    yield tc
