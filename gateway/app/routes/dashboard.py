"""Serve the dashboard static files at /dashboard/*."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse

from ..config import get_settings


router = APIRouter(tags=["dashboard"])


def _resolve_dashboard_root() -> Path:
    settings = get_settings()
    base = Path(settings.dashboard_dir)
    if not base.is_absolute():
        base = (settings.gateway_root / base).resolve()
    dist = base / "dist"
    if dist.is_dir():
        return dist
    return base


def _safe_join(root: Path, rel: str) -> Path:
    candidate = (root / rel.lstrip("/")).resolve()
    if root not in candidate.parents and candidate != root:
        raise HTTPException(status_code=404)
    return candidate


@router.get("/dashboard", include_in_schema=False)
async def dashboard_redirect():
    return await dashboard_root()


@router.get("/dashboard/", include_in_schema=False)
async def dashboard_root():
    root = _resolve_dashboard_root()
    index = root / "index.html"
    if index.is_file():
        return FileResponse(index)
    return HTMLResponse(
        "<html><body><h1>Dashboard not built yet.</h1>"
        "<p>Juno owns the dashboard at <code>../dashboard/</code>. "
        "Drop an <code>index.html</code> there or build to <code>dist/</code>.</p></body></html>",
        status_code=200,
    )


@router.get("/dashboard/{path:path}", include_in_schema=False)
async def dashboard_asset(path: str, request: Request):
    root = _resolve_dashboard_root()
    target = _safe_join(root, path)
    if target.is_file():
        return FileResponse(target)
    # SPA-style fallback to index.html.
    index = root / "index.html"
    if index.is_file():
        return FileResponse(index)
    raise HTTPException(status_code=404)
