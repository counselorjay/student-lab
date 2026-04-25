# ROUTING.md: Student Lab Gateway

**Owner:** Felix
**Audience:** MacGyver (implements `gateway/app/router.py` against this spec)
**Status:** v1, locked 2026-04-24. Refines ARCHITECTURE.md §"Routing & queueing".
**Scope:** Backend selection, health checks, model availability, failover, the `qwen3.6:35b` lockout, tunnel topology, and gateway co-location risk.

**M3 Pro is deliberately excluded from the student fleet** (Jay 2026-04-24). It's Jay's daily driver and stays out of shared rotation. The fleet is M5 Max (primary) + M5 Pro (secondary). All references below reflect this two-backend topology.

---

## 1. Backends (canonical)

| Name      | Host                          | Role                                                        |
|-----------|-------------------------------|-------------------------------------------------------------|
| `m5-max`  | `100.83.184.88:11434`         | Primary. All dense + heavy work routes here by default.     |
| `m5-pro`  | `100.120.197.64:11434`        | Secondary. Also hosts the gateway and other FastAPI services. Light overflow only. |

The router holds these as a list `BACKENDS = [m5_max, m5_pro]` keyed by name. The order is the failover order.

---

## 2. Backend selection algorithm

### 2.1. Constants

```
MAX_QUEUE_DEPTH = {
    "m5-max":  2,
    "m5-pro":  1,   # lower because the gateway and fit-sites share this host
}

LOCKED_MODELS = {
    "qwen3.6:35b":     {"reason": "psychrx POC reservation", "code": 403},
    "qwen3.6:latest":  {"reason": "psychrx POC reservation", "code": 403},
    "qwen3.6:35b-a3b-nvfp4": {"reason": "psychrx POC reservation", "code": 403},
}

HEALTH_CHECK_INTERVAL_S = 15
HEALTH_CHECK_TIMEOUT_S  = 3
HEALTH_FAIL_THRESHOLD   = 3      # mark offline after N consecutive failures
TAGS_CACHE_TTL_S        = 60     # /api/tags refresh interval per backend
PROXY_REQUEST_TIMEOUT_S = 600    # 10 min for long completions
```

### 2.2. Pseudocode

```python
def select_backend(model: str) -> Backend:
    # Step 0: lockout check (cheap, cheap, cheap)
    if model in LOCKED_MODELS:
        raise GatewayError(403, LOCKED_MODELS[model]["reason"])

    # Step 1: determine which backends can serve this model
    candidates = [b for b in BACKENDS if b.online and b.serves(model)]
    if not candidates:
        raise GatewayError(503, "No backend currently serves this model")

    # Step 2: prefer in fleet order, gated by queue depth
    for b in candidates:                       # m5-max, then m5-pro
        if b.in_flight < MAX_QUEUE_DEPTH[b.name]:
            if b.has_loaded(model) or b.can_load(model):
                return b

    # Step 3: nothing under the cap. Return the least-loaded candidate
    # in fleet order with a soft cap of MAX_QUEUE_DEPTH * 2; else 503.
    relaxed = [
        b for b in candidates
        if b.in_flight < MAX_QUEUE_DEPTH[b.name] * 2
    ]
    if relaxed:
        return min(relaxed, key=lambda b: (b.in_flight, BACKENDS.index(b)))

    raise GatewayError(503, "All capable backends are saturated", retry_after=10)
```

Notes:
- `b.has_loaded(model)` reads from the cached `/api/tags` snapshot (see §4).
- `b.can_load(model)` is true iff `model` appears in the backend's `/api/tags` *available* list. We do not attempt cross-backend pulls in v1. Ollama auto-loads on first request.
- "Fleet order" means the BACKENDS list order. We deliberately do not load-balance across M5 Max and M5 Pro: M5 Max is always preferred until it hits the queue cap. Splitting traffic creates KV-cache misses on both machines.
- M3 Pro is intentionally absent from BACKENDS (Jay's daily driver, not shared). Do not add it without a fleet-policy review.

### 2.3. Why M5 Pro's cap is 1, not 2

M5 Pro hosts the gateway, essaycoach, commonapp-worksheet, resume-builder, tiffanie-games, and the fit-site FastAPI services. A second concurrent heavy inference there will starve those services. Cap of 1 keeps M5 Pro as a true overflow, not a co-primary.

---

## 3. Tracking in-flight count

### 3.1. Mechanism

Keep a per-backend integer counter behind a single `asyncio.Lock`:

```python
class Backend:
    name: str
    host: str
    in_flight: int = 0
    _lock: asyncio.Lock

async def acquire(backend):
    async with backend._lock:
        backend.in_flight += 1

async def release(backend):
    async with backend._lock:
        backend.in_flight = max(0, backend.in_flight - 1)
```

Wrap every proxied request:

```python
backend = select_backend(model)
await acquire(backend)
try:
    return await proxy_to(backend, request)
finally:
    await release(backend)
```

The `try/finally` is the contract. Any path out of the proxy call must release, including `asyncio.CancelledError` (client disconnect) and timeout exceptions.

### 3.2. Crash and restart behavior

The counter is in-memory only. On gateway restart it resets to zero, which is correct: no in-flight requests survive a restart of the gateway process. We do not persist `in_flight` to SQLite.

Edge case: if a single FastAPI worker crashes mid-request, the OS unwinds and `finally` fires. The only way to leak the counter is a hard kill (SIGKILL or power loss), which also restarts the process and resets the counter to zero. Acceptable.

We deliberately do not poll the upstream Ollama for in-flight count. Ollama 0.21 does not expose it, and inferring from `/api/ps` is racy.

### 3.3. Single-process assumption

The counter assumes a single FastAPI process. **MacGyver: run the gateway with `uvicorn --workers 1`.** If we ever need multiple workers, switch the counter to a tiny `asyncio` shared state via `multiprocessing.Manager` or move it into SQLite with `INTEGER` and row locks. Not v1.

---

## 4. Health checks and model availability

A single background task per backend, started at app startup, runs forever.

```python
async def health_loop(backend: Backend):
    fail_count = 0
    while True:
        try:
            tags = await http_get(
                f"{backend.host}/api/tags",
                timeout=HEALTH_CHECK_TIMEOUT_S,
            )
            backend.tags_cache = parse_tags(tags)        # set of model names
            backend.tags_cache_at = now()
            backend.online = True
            fail_count = 0
        except Exception as e:
            fail_count += 1
            if fail_count >= HEALTH_FAIL_THRESHOLD:
                backend.online = False
            log.warning("health %s fail %d: %s", backend.name, fail_count, e)
        await asyncio.sleep(HEALTH_CHECK_INTERVAL_S)
```

### 4.1. Model availability

`/api/tags` is the single source of truth for "what can this backend serve". We probe every 15s and cache for 60s. The 60s TTL is a soft bound: the loop refreshes every 15s normally, the TTL is the maximum staleness window if probes fail intermittently.

Loaded vs available: `/api/tags` lists *available* (pulled) models. Ollama does not expose "currently loaded in VRAM" via a stable endpoint. For routing we treat "available" as sufficient. The MAX_QUEUE_DEPTH cap is the load proxy.

If we want loaded-set awareness later, `/api/ps` returns currently resident models. We can layer it in v1.1 if cold-load latency becomes a complaint. Not now.

### 4.2. Health endpoint

The gateway's `GET /healthz` returns:

```json
{
  "ok": true,
  "backends": {
    "m5-max":  {"online": true,  "models": 12, "in_flight": 0, "last_check_s_ago": 3},
    "m5-pro":  {"online": true,  "models": 11, "in_flight": 1, "last_check_s_ago": 2}
  }
}
```

`ok` is true iff at least one backend is online.

### 4.3. Dashboard `/api/status`

Same data shape, plus a redacted in-flight queue. Polled every 3s by the dashboard. Cache the response for 1s server-side to avoid stampedes when many tabs are open.

---

## 5. M3 Pro is excluded from the student fleet

Jay's daily driver is not a shared backend. Per Jay 2026-04-24, M3 Pro stays out of student rotation entirely. The router has no `m3-pro` entry in `BACKENDS` and no allowlist for it. If load on M5 Max + M5 Pro becomes the bottleneck, the answer is to gate quotas or scale a primary, not to drag the daily driver into rotation.

---

## 6. The qwen3.6 lockout

Hard 403 at the router, before any backend selection. Three tags are locked:

- `qwen3.6:35b`
- `qwen3.6:latest`
- `qwen3.6:35b-a3b-nvfp4`

Error response:

```json
{
  "error": {
    "code": "model_locked",
    "message": "qwen3.6 is reserved for the psychrx POC. Use qwen3.5:35b-a3b-nvfp4 for general work or gemma4:31b for vision and complex reasoning."
  }
}
```

The lockout list lives in `app/config.py` as a constant. Adding/removing a lock requires a code change and a deploy, not a runtime toggle. This is intentional: model reservations are a policy decision, not a config knob.

---

## 7. Failover semantics

Failover is **retry-once-on-next-backend** for retryable errors only.

### 7.1. Retryable

- Connection error (refused, reset, DNS, TLS handshake fail)
- Timeout on the upstream request (the 600s window)
- HTTP 502 / 503 / 504 from Ollama
- HTTP 5xx with no body (network blip)

### 7.2. Not retryable (return to client immediately)

- HTTP 400: bad request, the next backend will reject identically
- HTTP 401 / 403: auth, not transport
- HTTP 404: model not found on that backend (we already filtered by `serves()`, so this is a tags cache stale; treat as retryable once with a forced tags refresh on the failing backend)
- HTTP 422: bad payload
- HTTP 429: upstream rate limit (rare for Ollama; surface to client)

### 7.3. Algorithm

```python
async def proxy_with_failover(model, request):
    primary = select_backend(model)
    try:
        return await proxy_one(primary, request)
    except RetryableError as e:
        log_failover(primary, e)
        # Pick the next eligible backend, excluding the one that just failed
        secondary = select_backend(model, exclude={primary.name})
        try:
            return await proxy_one(secondary, request)
        except Exception as e2:
            raise GatewayError(502, f"All backends failed: {e}, {e2}")
```

We never retry more than once. Two strikes and we 502 the client. This bounds tail latency.

### 7.4. Log on failover

Always write a `requests` row for the failed first attempt (with `error` populated and `status_code` from the upstream), and a second row for the successful retry. The dashboard usage view should not double-count failovers against the user's daily quota; only count the successful row. Quota counting logic: count exactly one row per client request, the final outcome row, regardless of failovers underneath. MacGyver: implement this in the rate-limit middleware, not the logger.

---

## 8. Tunnel recommendation: dedicated tunnel for `lab.counselorjay.com`

**Recommendation: stand up a new dedicated cloudflared tunnel for `lab.counselorjay.com`. Do not reuse the shared fit-sites tunnel UUID `96edec0e-918d-4ccf-b7c8-6e1c54d01858` (formerly `10ea75cb...`).**

### 8.1. Why

The shared-tunnel pattern documented in `reference_cloudflared_shared_tunnel.md` carries a known footgun: Cloudflare load-balances incoming requests across every cloudflared instance running the same UUID. This means every config file on that UUID must list the full union of ingress hostnames, or ~50% of requests 404 at random. Nate has already flagged this as a scale risk requiring cleanup.

Adding the student lab to the shared UUID would:

1. Force me to edit every existing fit-site config to include `lab.counselorjay.com` ingress, and reload every fit-site cloudflared agent. That is a footgun-multiplier change touching live, in-production fit-sites for a brand-new project.
2. Couple the lab's uptime to the fit-sites' deploy cycle. A bad fit-site config push could 502 the lab; a bad lab config push could 502 medschoolfit.
3. Mix authenticated student traffic with public unauth fit-site traffic on the same tunnel process. Logs and metrics get harder to read.

### 8.2. The dedicated-tunnel pattern

Choiceendo, johnlocke, intranet, scheduler, and tiffaniegames each run their own tunnel UUID with their own credentials file. That is the pattern to copy. Concretely:

```
cloudflared tunnel create student-lab
# yields UUID + ~/.cloudflared/<uuid>.json credentials
```

Config: `~/.cloudflared/config-student-lab.yml`

```yaml
tunnel: <new-uuid>
credentials-file: /Users/sophie/.cloudflared/<new-uuid>.json
ingress:
  - hostname: lab.counselorjay.com
    service: http://localhost:8700
  - service: http_status:404
```

DNS: CNAME `lab` → `<new-uuid>.cfargotunnel.com` in the `jay@counselorjay.com` Cloudflare account (use `cloudflare_api_jay.env`).

LaunchAgent: `~/Library/LaunchAgents/com.cloudflared.studentlab.plist`, mirroring the choiceendo pattern.

### 8.3. Tradeoffs

- One more tunnel process on M5 Pro (cheap; cloudflared is ~30 MB resident).
- One more LaunchAgent to manage (mitigated by following the existing pattern).
- Isolation worth the modest overhead: the lab is the first authenticated multi-user surface and benefits from blast-radius isolation.

If Nate later runs the cleanup pass to standardize "every site = own tunnel", the lab is already correctly configured.

---

## 9. Co-location recommendation: keep gateway on M5 Pro for v1

**Recommendation: deploy the gateway on M5 Pro:8700 as architected. Move it later only if observed latency or contention demands it.**

### 9.1. Why M5 Pro is OK for v1

- The gateway is I/O-bound. It accepts a request, forwards JSON to the chosen backend, streams the response back. CPU and memory cost is small (FastAPI + httpx + SQLite writes). Order of magnitude: <100 MB resident, single-digit % CPU steady-state.
- M5 Pro already runs essaycoach, commonapp-worksheet, resume-builder, tiffanie-games, and fit-sites. Adding one more lightweight FastAPI process does not meaningfully change the contention picture.
- The real contention risk is **inference traffic on M5 Pro**, not the gateway itself. We mitigate that by setting M5 Pro's queue cap to 1 (§2.1) so M5 Pro only serves overflow inference, not steady traffic.
- M5 Max becomes primary inference target. The gateway sits on M5 Pro and routes mostly to M5 Max. M5 Pro's local Ollama mostly idles for student traffic, leaving room for psychrx, fit-site LLM calls, and the qwen3.6 reservation.

### 9.2. When to move it

Move the gateway off M5 Pro if:

- The fit-site FastAPI services start showing p95 latency degradation correlated with student traffic spikes.
- M5 Pro's Ollama queue is saturating (depth >1) under normal student load.
- Gateway logging writes to SQLite become a bottleneck (unlikely; SQLite WAL mode handles thousands of small writes per second).

### 9.3. If we do move it

The natural target is M5 Max once fully online. M5 Max has the headroom and would then host both the gateway and primary inference, removing one network hop on the most common path. Trade-off: M5 Max becomes a single point of failure for both routing and inference. Acceptable for v1 of a small student set; revisit when scale changes.

M3 Pro is not a candidate for hosting the gateway either. Jay's daily driver should not host an authenticated multi-user service.

### 9.4. Monitoring to enable the decision

MacGyver should expose in `/healthz` (or a sibling `/metrics` if cheap):
- Gateway p50/p95 internal latency (request received to response sent, excluding upstream Ollama time)
- SQLite write latency p95
- In-flight count per backend (already there)

Felix will revisit at the 30-day mark or earlier if dashboards show contention.

---

## 10. What this doc does not cover

- TLS/cert handling: handled by Cloudflare Tunnel, not the gateway.
- Streaming token counting: MacGyver to confirm via tee-on-stream. Out of routing scope.
- Per-user GPU reservation: deferred to v2 per ARCHITECTURE.md non-goals.
- Cross-backend model pull on demand: out of v1 scope. Models must be pre-pulled on backends.

---

## Open items for MacGyver

1. Confirm `uvicorn --workers 1` is acceptable for the v1 traffic envelope. If you need workers >1 for any reason, flag it and we'll move the in-flight counter to SQLite or a shared `multiprocessing.Manager`.
2. The 404-with-tags-refresh path in §7.2 is an edge case. If it adds complexity, drop it for v1 and treat 404 as non-retryable. Document the choice.
