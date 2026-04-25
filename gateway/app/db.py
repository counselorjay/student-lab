"""SQLAlchemy engine, session, and migration on startup."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from .config import get_settings
from .models import Base


_engine: Optional[Engine] = None
_SessionLocal: Optional[sessionmaker[Session]] = None


def _make_engine(db_url: str) -> Engine:
    return create_engine(
        db_url,
        future=True,
        connect_args={"check_same_thread": False} if db_url.startswith("sqlite") else {},
    )


def init_engine(db_url: Optional[str] = None) -> Engine:
    """Initialize the engine + session factory and run CREATE TABLE IF NOT EXISTS."""
    global _engine, _SessionLocal
    if db_url is None:
        path = get_settings().db_full_path
        db_url = f"sqlite:///{path}"
    _engine = _make_engine(db_url)
    _SessionLocal = sessionmaker(bind=_engine, autoflush=False, autocommit=False, future=True)
    Base.metadata.create_all(_engine)
    return _engine


def get_engine() -> Engine:
    if _engine is None:
        init_engine()
    assert _engine is not None
    return _engine


def get_session_factory() -> sessionmaker[Session]:
    if _SessionLocal is None:
        init_engine()
    assert _SessionLocal is not None
    return _SessionLocal


@contextmanager
def session_scope() -> Iterator[Session]:
    s = get_session_factory()()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()


def get_db() -> Iterator[Session]:
    """FastAPI dependency."""
    s = get_session_factory()()
    try:
        yield s
    finally:
        s.close()


def reset_for_test(db_url: str = "sqlite:///:memory:") -> Engine:
    """Test hook: rebuild engine against a fresh DB and recreate schema.

    Uses StaticPool so every session shares one connection to the in-memory DB.
    """
    global _engine, _SessionLocal
    _engine = create_engine(
        db_url,
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    _SessionLocal = sessionmaker(bind=_engine, autoflush=False, autocommit=False, future=True)
    Base.metadata.drop_all(_engine)
    Base.metadata.create_all(_engine)
    return _engine
