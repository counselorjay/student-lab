"""Inference endpoints — passthrough to selected Ollama backend, with logging.

Routing per Felix ROUTING.md (gateway/ROUTING.md). Failover is retry-once on
retryable errors only (§7); we log a row for each attempt but only the final
outcome counts toward the user's quota (the route checks the quota up front).
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from ..auth import AuthedUser, require_api_key
from ..config import get_settings
from ..db import get_db
from ..logging_mw import write_request_log
from ..proxy import proxy_request
from ..quota import check_quota
from ..router import BackendRegistry, BackendState, is_locked, select_backend


router = APIRouter(prefix="/api", tags=["inference"])


# Status codes treated as retryable per ROUTING.md §7.1.
_RETRYABLE_STATUS = {502, 503, 504}


def _err(code: str, message: str, http: int) -> HTTPException:
    return HTTPException(status_code=http, detail={"error": {"code": code, "message": message}})


def _get_registry(request: Request) -> BackendRegistry:
    return request.app.state.registry


def _locked_response() -> JSONResponse:
    return JSONResponse(
        status_code=403,
        content={
            "error": {
                "code": "model_locked",
                "message": (
                    "qwen3.6 is reserved for the psychrx POC. "
                    "Use qwen3.5:35b-a3b-nvfp4 for general work or gemma4:31b "
                    "for vision and complex reasoning."
                ),
            }
        },
    )


async def _proxy_inference(
    request: Request,
    upstream_path: str,
    db: Session,
    authed: AuthedUser,
):
    settings = get_settings()
    registry: BackendRegistry = _get_registry(request)

    try:
        body = await request.json()
    except (ValueError, UnicodeDecodeError):
        raise _err("bad_json", "Request body must be valid JSON.", 400)
    if not isinstance(body, dict):
        raise _err("bad_json", "Request body must be a JSON object.", 400)

    model = str(body.get("model") or "").strip()

    # Step 0: lockout (ROUTING.md §6).
    if is_locked(model, settings):
        return _locked_response()

    # Quota gate.
    qc = check_quota(db, authed.user)
    if not qc.ok:
        return JSONResponse(
            status_code=429,
            content={
                "error": {
                    "code": qc.reason or "quota_exceeded",
                    "message": "Daily limit exceeded. Try again tomorrow.",
                }
            },
            headers={"Retry-After": str(qc.retry_after_seconds or 3600)},
        )

    primary_decision = select_backend(model, registry, settings)
    if primary_decision.backend is None:
        reason = primary_decision.reason_if_none or "no_backend_available"
        http = 503
        msg = {
            "no_serving_backend": "No backend currently serves this model.",
            "not_on_capable_backend": "Model not available on capable backends.",
            "saturated": "All capable backends are saturated.",
        }.get(reason, "No backend available.")
        return JSONResponse(
            status_code=http,
            content={"error": {"code": reason, "message": msg}},
            headers={"Retry-After": "10" if reason == "saturated" else "30"},
        )

    primary = primary_decision.backend
    started = datetime.utcnow()

    await registry.acquire(primary.name)
    try:
        result, _captured = await proxy_request(
            request=request,
            backend=primary,
            upstream_path=upstream_path,
            body_json=body,
            method="POST",
            registry=None,  # we manage acquire/release here
        )
    finally:
        await registry.release(primary.name)
    ended = datetime.utcnow()

    retryable = (
        result.status_code in _RETRYABLE_STATUS
        or result.error is not None
        and result.status_code >= 500
    )

    if retryable:
        # Log the failed attempt.
        write_request_log(
            db,
            user_id=authed.user.id,
            api_key_id=authed.api_key.id,
            endpoint=upstream_path,
            model=model or None,
            backend=primary.name,
            status_code=result.status_code,
            prompt_tokens=result.prompt_tokens,
            output_tokens=result.output_tokens,
            started_at=started,
            ended_at=ended,
            error=result.error or f"HTTP {result.status_code}",
        )

        secondary_decision = select_backend(
            model, registry, settings, exclude={primary.name}
        )
        if secondary_decision.backend is not None:
            secondary = secondary_decision.backend
            started2 = datetime.utcnow()
            await registry.acquire(secondary.name)
            try:
                result, _captured = await proxy_request(
                    request=request,
                    backend=secondary,
                    upstream_path=upstream_path,
                    body_json=body,
                    method="POST",
                    registry=None,
                )
            finally:
                await registry.release(secondary.name)
            ended2 = datetime.utcnow()
            write_request_log(
                db,
                user_id=authed.user.id,
                api_key_id=authed.api_key.id,
                endpoint=upstream_path,
                model=model or None,
                backend=secondary.name,
                status_code=result.status_code,
                prompt_tokens=result.prompt_tokens,
                output_tokens=result.output_tokens,
                started_at=started2,
                ended_at=ended2,
                error=result.error,
            )
            return result.response
        # No secondary available; first attempt already logged. Return that.
        return result.response

    # Happy path: log once, return.
    write_request_log(
        db,
        user_id=authed.user.id,
        api_key_id=authed.api_key.id,
        endpoint=upstream_path,
        model=model or None,
        backend=primary.name,
        status_code=result.status_code,
        prompt_tokens=result.prompt_tokens,
        output_tokens=result.output_tokens,
        started_at=started,
        ended_at=ended,
        error=result.error,
    )
    return result.response


@router.post("/chat")
async def chat(
    request: Request,
    db: Session = Depends(get_db),
    authed: AuthedUser = Depends(require_api_key),
):
    return await _proxy_inference(request, "/api/chat", db, authed)


@router.post("/generate")
async def generate(
    request: Request,
    db: Session = Depends(get_db),
    authed: AuthedUser = Depends(require_api_key),
):
    return await _proxy_inference(request, "/api/generate", db, authed)


@router.post("/embed")
async def embed(
    request: Request,
    db: Session = Depends(get_db),
    authed: AuthedUser = Depends(require_api_key),
):
    return await _proxy_inference(request, "/api/embed", db, authed)


@router.get("/tags")
async def tags(
    request: Request,
    db: Session = Depends(get_db),
    authed: AuthedUser = Depends(require_api_key),
):
    """Merge /api/tags from each online backend, deduped by model name. Locked
    models are filtered out of the response."""
    registry: BackendRegistry = _get_registry(request)
    settings = get_settings()
    merged: dict[str, dict] = {}

    started = datetime.utcnow()
    async with httpx.AsyncClient(timeout=10.0) as client:
        for backend in registry.backends.values():
            if not backend.online:
                continue
            try:
                r = await client.get(f"{backend.host}/api/tags")
                if r.status_code != 200:
                    continue
                for m in r.json().get("models", []):
                    name = m.get("name")
                    if not name or name in settings.reserved_models:
                        continue
                    if name not in merged:
                        merged[name] = m
            except (httpx.HTTPError, ValueError):
                continue
    ended = datetime.utcnow()

    write_request_log(
        db,
        user_id=authed.user.id,
        api_key_id=authed.api_key.id,
        endpoint="/api/tags",
        model=None,
        backend=None,
        status_code=200,
        prompt_tokens=None,
        output_tokens=None,
        started_at=started,
        ended_at=ended,
    )
    return {"models": list(merged.values())}


@router.get("/show")
async def show(
    request: Request,
    db: Session = Depends(get_db),
    authed: AuthedUser = Depends(require_api_key),
    name: Optional[str] = None,
):
    if not name:
        raise _err("missing_name", "Query parameter `name` is required.", 400)
    registry: BackendRegistry = _get_registry(request)
    settings = get_settings()
    if is_locked(name, settings):
        return _locked_response()
    started = datetime.utcnow()
    async with httpx.AsyncClient(timeout=10.0) as client:
        for backend in registry.backends.values():
            if not backend.online:
                continue
            try:
                r = await client.post(f"{backend.host}/api/show", json={"name": name})
                if r.status_code == 200:
                    ended = datetime.utcnow()
                    write_request_log(
                        db,
                        user_id=authed.user.id,
                        api_key_id=authed.api_key.id,
                        endpoint="/api/show",
                        model=name,
                        backend=backend.name,
                        status_code=200,
                        prompt_tokens=None,
                        output_tokens=None,
                        started_at=started,
                        ended_at=ended,
                    )
                    return r.json()
            except (httpx.HTTPError, ValueError):
                continue
    ended = datetime.utcnow()
    write_request_log(
        db,
        user_id=authed.user.id,
        api_key_id=authed.api_key.id,
        endpoint="/api/show",
        model=name,
        backend=None,
        status_code=404,
        prompt_tokens=None,
        output_tokens=None,
        started_at=started,
        ended_at=ended,
        error="not_found",
    )
    raise _err("not_found", f"Model {name} not found on any backend.", 404)
