"""Backend selection per Felix's ROUTING.md (gateway/ROUTING.md).

Selection algorithm (§2.2, two-backend topology):
  Step 0: hard 403 on locked models.
  Step 1: candidates = [b for b in BACKENDS if b.online and b.serves(model)]
  Step 2: walk candidates in fleet order; first under MAX_QUEUE_DEPTH wins.
  Step 3: relax to soft cap (MAX_QUEUE_DEPTH * 2); pick least-loaded; else 503.

M3 Pro is intentionally absent from BACKENDS per Jay 2026-04-24 (daily driver).
Failover (§7) is owned by the inference route; this module only picks.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

import httpx

from .config import Settings, get_settings


# Canonical fleet order (§1). M3 Pro deliberately excluded.
FLEET_ORDER = ("m5-max", "m5-pro")


@dataclass
class BackendState:
    name: str
    host: str
    online: bool = False
    models_loaded: list[str] = field(default_factory=list)
    queue_depth: int = 0
    last_check: Optional[datetime] = None
    fail_count: int = 0

    def serves(self, model: str) -> bool:
        if not model:
            return False
        return model in self.models_loaded


class BackendRegistry:
    """In-memory registry of backend health + queue depth.

    Counter is in-memory only by design (ROUTING.md §3.2). Single-process
    assumption (uvicorn --workers 1).
    """

    def __init__(self, settings: Settings):
        self.settings = settings
        backends_cfg = settings.backends()
        # Insert in canonical fleet order so iteration matches §2.
        self.backends: dict[str, BackendState] = {}
        for name in FLEET_ORDER:
            if name in backends_cfg:
                self.backends[name] = BackendState(name=name, host=backends_cfg[name])
        self._lock = asyncio.Lock()

    def names(self) -> list[str]:
        return list(self.backends.keys())

    def get(self, name: str) -> Optional[BackendState]:
        return self.backends.get(name)

    async def acquire(self, name: str) -> None:
        async with self._lock:
            if name in self.backends:
                self.backends[name].queue_depth += 1

    async def release(self, name: str) -> None:
        async with self._lock:
            if name in self.backends:
                self.backends[name].queue_depth = max(0, self.backends[name].queue_depth - 1)

    def snapshot(self) -> list[dict]:
        return [
            {
                "name": b.name,
                "host": b.host,
                "online": b.online,
                "models_loaded": list(b.models_loaded),
                "queue_depth": b.queue_depth,
                "last_check": b.last_check.isoformat() if b.last_check else None,
            }
            for b in self.backends.values()
        ]


async def probe_once(registry: BackendRegistry, client: httpx.AsyncClient) -> None:
    """Hit /api/tags on each backend; update tags + online flag.

    Uses HEALTH_FAIL_THRESHOLD consecutive failures before flipping online to
    False (per ROUTING.md §4).
    """
    settings = registry.settings
    for state in registry.backends.values():
        try:
            r = await client.get(
                f"{state.host}/api/tags",
                timeout=settings.health_probe_timeout,
            )
            if r.status_code == 200:
                data = r.json()
                state.models_loaded = [m.get("name", "") for m in data.get("models", [])]
                state.online = True
                state.fail_count = 0
            else:
                state.fail_count += 1
                if state.fail_count >= settings.health_fail_threshold:
                    state.online = False
        except (httpx.HTTPError, ValueError):
            state.fail_count += 1
            if state.fail_count >= settings.health_fail_threshold:
                state.online = False
        state.last_check = datetime.utcnow()


async def probe_loop(registry: BackendRegistry, interval: int) -> None:
    async with httpx.AsyncClient() as client:
        while True:
            await probe_once(registry, client)
            await asyncio.sleep(interval)


def is_locked(model: str, settings: Settings) -> bool:
    return bool(model) and model in settings.reserved_models


@dataclass
class RoutingDecision:
    backend: Optional[BackendState]
    candidates: list[BackendState]
    reason_if_none: Optional[str] = None  # one of: "no_serving_backend", "saturated", or None


def select_backend(
    model: str,
    registry: BackendRegistry,
    settings: Optional[Settings] = None,
    exclude: Optional[set[str]] = None,
) -> RoutingDecision:
    """Per ROUTING.md §2.2."""
    settings = settings or get_settings()
    exclude = exclude or set()
    caps = settings.backend_queue_caps

    # Step 1: backends that are online and serve this model.
    candidates: list[BackendState] = []
    for name in FLEET_ORDER:
        b = registry.get(name)
        if b is None or b.name in exclude:
            continue
        if not b.online:
            continue
        if not b.serves(model):
            continue
        candidates.append(b)

    if not candidates:
        return RoutingDecision(backend=None, candidates=[], reason_if_none="no_serving_backend")

    # Step 2: hard cap, fleet order.
    for b in candidates:
        if b.queue_depth < caps.get(b.name, 1):
            return RoutingDecision(backend=b, candidates=candidates)

    # Step 3: soft cap relaxation, then least-loaded by (in_flight, fleet index).
    relaxed = [b for b in candidates if b.queue_depth < caps.get(b.name, 1) * 2]
    if relaxed:
        chosen = min(relaxed, key=lambda b: (b.queue_depth, FLEET_ORDER.index(b.name)))
        return RoutingDecision(backend=chosen, candidates=candidates)

    return RoutingDecision(backend=None, candidates=candidates, reason_if_none="saturated")
