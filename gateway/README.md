# Student Lab Gateway

FastAPI in front of Jay's student-accessible Ollama fleet (M5 Max + M5 Pro). Authenticated by API key on `/api/*`, by Cloudflare Access on `/dashboard/*` and `/api/admin/*`. Logs every request, enforces per-user daily quotas, and routes by model + load. M3 Pro is Jay's daily driver and is deliberately excluded from the shared rotation.

## Run locally

```bash
cd gateway
python -m venv .venv && source .venv/bin/activate
pip install -e '.[dev]'
cp .env.example .env
# edit .env if you want non-default backend URLs

uvicorn app.main:app --port 8700 --reload
```

Smoke check:

```bash
curl http://localhost:8700/healthz
```

## Bootstrap the first admin user

```bash
python -m app.bootstrap admin jay@counselorjay.com --name "Jay"
```

That prints an API key once. Save it. The user the bootstrap CLI creates will only pass `require_admin` if their email matches `ADMIN_EMAIL` in `.env` (default `jay@counselorjay.com`).

To mint a key for an existing user:

```bash
python -m app.bootstrap mintkey <user_id> --label laptop
```

To revoke every key sharing a prefix:

```bash
python -m app.bootstrap revoke slk_abcd
```

## Smoke a real student flow

```bash
# Mint Jay's admin user + key (once).
python -m app.bootstrap admin jay@counselorjay.com

# Use that key to call /api/me.
curl -H "Authorization: Bearer slk_..." http://localhost:8700/api/me

# Create a student via the admin API (CF Access header simulated).
curl -X POST http://localhost:8700/api/admin/users \
  -H "Cf-Access-Authenticated-User-Email: jay@counselorjay.com" \
  -H "Content-Type: application/json" \
  -d '{"email": "alice@example.com", "name": "Alice"}'

# Mint Alice a key.
curl -X POST http://localhost:8700/api/admin/users/<id>/keys \
  -H "Cf-Access-Authenticated-User-Email: jay@counselorjay.com" \
  -H "Content-Type: application/json" \
  -d '{"label": "laptop"}'
```

## Tests

```bash
cd gateway
pytest -q
```

## Environment variables

| Var | Default | Notes |
|---|---|---|
| `ADMIN_EMAIL` | `jay@counselorjay.com` | Email that passes `require_admin` |
| `BACKEND_M5_MAX` | `http://100.83.184.88:11434` | Empty disables this backend |
| `BACKEND_M5_PRO` | `http://100.120.197.64:11434` | Empty disables this backend |
| `DB_PATH` | `data/lab.db` | Relative to `gateway/` |
| `HEALTH_PROBE_INTERVAL` | `5` | Seconds between probes |
| `DEFAULT_DAILY_REQUEST_LIMIT` | `200` | Applied at user creation |
| `DEFAULT_DAILY_TOKEN_LIMIT` | `500000` | Applied at user creation |
| `PROXY_TIMEOUT` | `600` | Per-request seconds when forwarding to a backend |
| `DASHBOARD_DIR` | `../dashboard` | Path to Juno's dashboard; `dist/` preferred, then root |

## Endpoints

| Method | Path | Auth | Notes |
|---|---|---|---|
| GET | `/healthz` | none | Liveness + per-backend online flag |
| GET | `/api/status` | none | Backend snapshot, queue depth |
| GET | `/api/me` | API key | User info + today's usage |
| POST | `/api/chat` | API key | Proxies Ollama `/api/chat`, logs, counts tokens |
| POST | `/api/generate` | API key | Same shape as chat |
| POST | `/api/embed` | API key | Same |
| GET | `/api/tags` | API key | Merges all online backends, dedupes by name |
| GET | `/api/show?name=` | API key | First backend that returns 200 wins |
| POST | `/api/admin/users` | CF Access (admin email) | Create user |
| GET | `/api/admin/users` | CF Access (admin email) | List users |
| POST | `/api/admin/users/{id}/keys` | CF Access (admin email) | Returns plaintext key once |
| DELETE | `/api/admin/keys/{id}` | CF Access (admin email) | Revoke |
| GET | `/api/admin/usage` | CF Access (admin email) | `?fmt=csv` for CSV, else JSON |
| GET | `/dashboard/*` | CF Access (allowlist) | Static files; SPA fallback to `index.html` |

## Routing

Per ARCHITECTURE.md `§Routing & queueing`. When Felix's `gateway/ROUTING.md` lands, revisit `app/router.py`.

Reserved models (`qwen3.6:35b`, `qwen3.6`) are hard-blocked: requests get a 403 with `code: model_reserved`. They are also filtered from `/api/tags` so students never see them.
