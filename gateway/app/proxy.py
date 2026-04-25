"""httpx proxy: forward to a selected Ollama backend, stream, count tokens."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import AsyncIterator, Optional

import httpx
from fastapi import Request
from fastapi.responses import JSONResponse, StreamingResponse

from .config import get_settings
from .router import BackendRegistry, BackendState


@dataclass
class ProxyResult:
    response: object  # JSONResponse or StreamingResponse
    status_code: int
    backend_name: Optional[str]
    prompt_tokens: Optional[int]
    output_tokens: Optional[int]
    error: Optional[str]


def _extract_token_counts(payload: dict) -> tuple[Optional[int], Optional[int]]:
    """Pull prompt/output token counts from an Ollama final chunk or full response."""
    prompt = payload.get("prompt_eval_count")
    output = payload.get("eval_count")
    return (
        int(prompt) if isinstance(prompt, (int, float)) else None,
        int(output) if isinstance(output, (int, float)) else None,
    )


async def _stream_and_count(
    upstream: httpx.Response,
) -> tuple[AsyncIterator[bytes], dict]:
    """Wrap an upstream streaming response: tee bytes through, capture last JSON chunk."""
    captured: dict = {}

    async def gen() -> AsyncIterator[bytes]:
        buf = b""
        async for chunk in upstream.aiter_bytes():
            yield chunk
            buf += chunk
            # Ollama emits newline-delimited JSON. The last non-empty line carries done=true with totals.
            if b"\n" in buf:
                lines = buf.split(b"\n")
                buf = lines[-1]
                for line in lines[:-1]:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line.decode("utf-8"))
                    except (UnicodeDecodeError, json.JSONDecodeError):
                        continue
                    if isinstance(obj, dict) and obj.get("done"):
                        captured.update(obj)
        # Final flush.
        if buf.strip():
            try:
                obj = json.loads(buf.decode("utf-8"))
                if isinstance(obj, dict) and obj.get("done"):
                    captured.update(obj)
            except (UnicodeDecodeError, json.JSONDecodeError):
                pass

    return gen(), captured


async def proxy_request(
    request: Request,
    backend: BackendState,
    upstream_path: str,
    body_json: Optional[dict] = None,
    method: str = "POST",
    registry: Optional[BackendRegistry] = None,
) -> tuple[ProxyResult, dict]:
    """Forward request to backend.

    Returns (ProxyResult, captured_metadata) where captured_metadata is the parsed
    final JSON chunk (for streaming) or the full response (for non-streaming),
    used by the caller to write logs.
    """
    settings = get_settings()
    url = f"{backend.host}{upstream_path}"
    timeout = httpx.Timeout(settings.proxy_timeout, connect=10.0)

    is_stream = bool(body_json and body_json.get("stream"))

    client = httpx.AsyncClient(timeout=timeout)
    if registry is not None:
        await registry.incr(backend.name)

    try:
        if method == "GET":
            req = client.build_request("GET", url, params=dict(request.query_params))
        else:
            req = client.build_request("POST", url, json=body_json)

        upstream = await client.send(req, stream=is_stream)
    except httpx.HTTPError as exc:
        if registry is not None:
            await registry.decr(backend.name)
        await client.aclose()
        return (
            ProxyResult(
                response=JSONResponse(
                    status_code=502,
                    content={"error": {"code": "backend_unreachable", "message": str(exc)}},
                ),
                status_code=502,
                backend_name=backend.name,
                prompt_tokens=None,
                output_tokens=None,
                error=str(exc),
            ),
            {},
        )

    if is_stream:
        gen, captured = await _stream_and_count(upstream)

        async def wrapped() -> AsyncIterator[bytes]:
            try:
                async for chunk in gen:
                    yield chunk
            finally:
                await upstream.aclose()
                await client.aclose()
                if registry is not None:
                    await registry.decr(backend.name)

        return (
            ProxyResult(
                response=StreamingResponse(
                    wrapped(),
                    status_code=upstream.status_code,
                    media_type=upstream.headers.get("content-type", "application/x-ndjson"),
                ),
                status_code=upstream.status_code,
                backend_name=backend.name,
                prompt_tokens=None,
                output_tokens=None,
                error=None,
            ),
            captured,
        )

    # Non-streaming.
    try:
        body_bytes = await upstream.aread()
    finally:
        await upstream.aclose()
        await client.aclose()
        if registry is not None:
            await registry.decr(backend.name)

    captured = {}
    try:
        captured = json.loads(body_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        pass

    pt, ot = _extract_token_counts(captured if isinstance(captured, dict) else {})

    return (
        ProxyResult(
            response=JSONResponse(
                status_code=upstream.status_code,
                content=captured if isinstance(captured, (dict, list)) else {"raw": body_bytes.decode("utf-8", "replace")},
            ),
            status_code=upstream.status_code,
            backend_name=backend.name,
            prompt_tokens=pt,
            output_tokens=ot,
            error=None if upstream.status_code < 400 else f"HTTP {upstream.status_code}",
        ),
        captured if isinstance(captured, dict) else {},
    )
