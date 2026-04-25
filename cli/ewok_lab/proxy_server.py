"""Localhost Ollama-compatible proxy.

Tools that already speak Ollama (Continue, Claude Code custom commands) point at
http://localhost:11435 and the gateway's auth + TLS happen transparently.
"""

from __future__ import annotations

from typing import Optional

import httpx
import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

from .config import Config


def make_app(cfg: Config) -> FastAPI:
    app = FastAPI(title="ewok-lab local proxy", version="0.1.0")
    headers = {"Authorization": f"Bearer {cfg.api_key}"}
    timeout = httpx.Timeout(600.0, connect=10.0)

    async def _passthrough_post(request: Request, path: str):
        try:
            body = await request.json()
        except (ValueError, UnicodeDecodeError):
            raise HTTPException(status_code=400, detail="invalid JSON")
        url = f"{cfg.gateway}{path}"
        is_stream = bool(body.get("stream"))

        if is_stream:
            client = httpx.AsyncClient(timeout=timeout)
            req = client.build_request("POST", url, json=body, headers=headers)
            try:
                upstream = await client.send(req, stream=True)
            except httpx.HTTPError as exc:
                await client.aclose()
                raise HTTPException(status_code=502, detail=str(exc))

            async def gen():
                try:
                    async for chunk in upstream.aiter_bytes():
                        yield chunk
                finally:
                    await upstream.aclose()
                    await client.aclose()

            return StreamingResponse(
                gen(),
                status_code=upstream.status_code,
                media_type=upstream.headers.get("content-type", "application/x-ndjson"),
            )

        async with httpx.AsyncClient(timeout=timeout) as c:
            try:
                r = await c.post(url, json=body, headers=headers)
            except httpx.HTTPError as exc:
                raise HTTPException(status_code=502, detail=str(exc))
        try:
            return JSONResponse(status_code=r.status_code, content=r.json())
        except ValueError:
            return JSONResponse(status_code=r.status_code, content={"raw": r.text})

    @app.post("/api/chat")
    async def chat(request: Request):
        return await _passthrough_post(request, "/api/chat")

    @app.post("/api/generate")
    async def generate(request: Request):
        return await _passthrough_post(request, "/api/generate")

    @app.post("/api/embed")
    async def embed(request: Request):
        return await _passthrough_post(request, "/api/embed")

    @app.get("/api/tags")
    async def tags():
        async with httpx.AsyncClient(timeout=15.0) as c:
            r = await c.get(f"{cfg.gateway}/api/tags", headers=headers)
        return JSONResponse(status_code=r.status_code, content=r.json())

    @app.post("/api/show")
    async def show(request: Request):
        body = await request.json()
        name = body.get("name") or body.get("model")
        if not name:
            raise HTTPException(status_code=400, detail="name required")
        async with httpx.AsyncClient(timeout=15.0) as c:
            r = await c.get(
                f"{cfg.gateway}/api/show",
                params={"name": name},
                headers=headers,
            )
        try:
            return JSONResponse(status_code=r.status_code, content=r.json())
        except ValueError:
            return JSONResponse(status_code=r.status_code, content={"raw": r.text})

    return app


def serve(cfg: Config, host: str = "127.0.0.1", port: int = 11435) -> None:
    app = make_app(cfg)
    uvicorn.run(app, host=host, port=port, log_level="info")
