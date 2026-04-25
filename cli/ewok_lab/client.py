"""Thin httpx wrapper around the gateway."""

from __future__ import annotations

from typing import Any, AsyncIterator, Optional

import httpx

from .config import Config


class GatewayClient:
    def __init__(self, cfg: Config, timeout: float = 600.0):
        self.cfg = cfg
        self.timeout = timeout

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.cfg.api_key}"}

    def me(self) -> dict[str, Any]:
        with httpx.Client(timeout=10.0) as c:
            r = c.get(f"{self.cfg.gateway}/api/me", headers=self._headers())
            r.raise_for_status()
            return r.json()

    def status(self) -> dict[str, Any]:
        with httpx.Client(timeout=10.0) as c:
            r = c.get(f"{self.cfg.gateway}/api/status")
            r.raise_for_status()
            return r.json()

    def tags(self) -> dict[str, Any]:
        with httpx.Client(timeout=15.0) as c:
            r = c.get(f"{self.cfg.gateway}/api/tags", headers=self._headers())
            r.raise_for_status()
            return r.json()

    async def chat_stream(
        self,
        model: str,
        messages: list[dict],
        format: Optional[str] = None,
    ) -> AsyncIterator[dict]:
        body: dict[str, Any] = {"model": model, "messages": messages, "stream": True}
        if format:
            body["format"] = format
        async with httpx.AsyncClient(timeout=self.timeout) as c:
            async with c.stream(
                "POST",
                f"{self.cfg.gateway}/api/chat",
                json=body,
                headers=self._headers(),
            ) as r:
                r.raise_for_status()
                async for line in r.aiter_lines():
                    if not line.strip():
                        continue
                    import json as _json
                    try:
                        yield _json.loads(line)
                    except _json.JSONDecodeError:
                        continue

    def chat_oneshot(
        self,
        model: str,
        messages: list[dict],
        format: Optional[str] = None,
    ) -> dict[str, Any]:
        """Non-streaming chat. Returns the full Ollama response dict."""
        body: dict[str, Any] = {"model": model, "messages": messages, "stream": False}
        if format:
            body["format"] = format
        with httpx.Client(timeout=self.timeout) as c:
            r = c.post(
                f"{self.cfg.gateway}/api/chat",
                json=body,
                headers=self._headers(),
            )
            r.raise_for_status()
            return r.json()


def validate_key(gateway: str, api_key: str) -> Optional[dict]:
    """Hit /api/me with a candidate key. Return user dict on success, None on auth failure."""
    with httpx.Client(timeout=10.0) as c:
        try:
            r = c.get(
                f"{gateway}/api/me",
                headers={"Authorization": f"Bearer {api_key}"},
            )
        except httpx.HTTPError as exc:
            raise SystemExit(f"Could not reach {gateway}: {exc}")
    if r.status_code == 200:
        return r.json()
    if r.status_code in (401, 403):
        return None
    raise SystemExit(f"Unexpected {r.status_code} from gateway: {r.text[:200]}")
