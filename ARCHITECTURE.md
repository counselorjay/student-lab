# Student Lab — Architecture

**Status:** v1 scope locked 2026-04-24. This doc is the contract between Felix, MacGyver, Juno, and Nate. If you disagree with anything here, write back to Ewok via `team-inbox/[agent]-ewok-arch-question.md` BEFORE diverging.

## Goal
Give a small set of trusted students authenticated, logged, queue-aware access to Jay's local LLM fleet (M5 Max + M5 Pro) without ever giving them shell access or requiring Tailscale on their end. M3 Pro is Jay's daily driver and is deliberately excluded from the student-accessible fleet.

## Non-goals (v1)
- SSH or web-terminal access for students (deferred to v2)
- Per-user GPU reservations
- Streaming responses (deferred unless trivial)
- Billing
- Self-serve registration (Jay manually adds students)

## Topology

```
Student (browser or CLI, anywhere)
        │  HTTPS
        ▼
lab.counselorjay.com  ─── Cloudflare Tunnel
        │
        ├─/dashboard/*  → CF Access (email magic-link allowlist)
        ├─/api/*        → public path, API-key-gated by gateway
        └─/healthz      → public, no auth
        │
        ▼
FastAPI gateway on M5 Pro :8700
   ├── auth (API key → user)
   ├── rate-limit + quota (per user)
   ├── router (M5 Max → M5 Pro per Felix policy)
   ├── proxy to Ollama (passthrough JSON, no rewrites)
   └── logger (request, tokens, latency, route → SQLite)
        │
        ▼
Ollama backends
   • M5 Max  100.83.184.88:11434  (primary)
   • M5 Pro  100.120.197.64:11434 (secondary; this host runs the gateway too)
   (M3 Pro deliberately excluded: it's Jay's daily driver, not a shared backend.)
```

## Auth model

Two layers, separated by URL path.

### Dashboard — `lab.counselorjay.com/dashboard/*`
- Cloudflare Access "Self-hosted Application" policy
- Identity provider: Cloudflare One-Time-PIN (email magic link)
- Allowlist: explicit email addresses (Jay manages in CF dashboard)
- Sessions: 24h
- The FastAPI app reads `Cf-Access-Authenticated-User-Email` header to know who's looking at the dashboard

### API — `lab.counselorjay.com/api/*`
- **Bypassed** in CF Access (public path)
- Auth via `Authorization: Bearer <api_key>` header
- API key format: `slk_` prefix + 32 hex chars (e.g. `slk_a1b2...`)
- Keys stored as `bcrypt` hash + `key_prefix` (first 8 chars) for lookup
- Bound to a `user_id`; revocable; can have an expiry

### Healthz — `lab.counselorjay.com/healthz`
- Public, returns 200 + JSON `{"ok": true, "backends": {...}}`
- No PII, used for monitoring

## API contract

All endpoints return JSON. Errors follow `{"error": {"code": "...", "message": "..."}}`.

### Auth & Identity
- `GET /api/me` → `{user_id, email, quotas: {requests_per_day, tokens_per_day}, used: {...}}`

### Inference (passthrough to Ollama, with logging)
The gateway proxies these Ollama endpoints **as-is** so students can use any Ollama-compatible client. Request body is forwarded; gateway selects backend based on model name + load.

- `POST /api/chat` → Ollama `/api/chat`
- `POST /api/generate` → Ollama `/api/generate`
- `POST /api/embed` → Ollama `/api/embed`
- `GET  /api/tags` → Ollama `/api/tags` (merged across backends, deduped by model name)
- `GET  /api/show?name=<model>` → Ollama `/api/show`

Streaming (`"stream": true`) is **passthrough**. Logging happens after stream completes via cumulative token count.

### Status
- `GET /api/status` → `{backends: [{name, host, online, models_loaded, queue_depth, last_check}], queue: [{user_email_redacted, model, started_at, est_tokens}]}`
- The dashboard polls this every 3s.

### Admin (Jay only — CF Access "admin" policy on `/api/admin/*`)
- `POST /api/admin/users` → create user `{email, name, daily_request_limit, daily_token_limit}`
- `POST /api/admin/users/{id}/keys` → mint API key, returned ONCE in plaintext
- `DELETE /api/admin/keys/{id}` → revoke
- `GET /api/admin/usage?from=&to=` → CSV/JSON of all requests

## Database (SQLite at `gateway/data/lab.db`)

```sql
CREATE TABLE users (
  id           TEXT PRIMARY KEY,           -- uuid
  email        TEXT UNIQUE NOT NULL,
  name         TEXT NOT NULL,
  created_at   TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  active       INTEGER NOT NULL DEFAULT 1,
  daily_request_limit INTEGER NOT NULL DEFAULT 200,
  daily_token_limit   INTEGER NOT NULL DEFAULT 500000,
  notes        TEXT
);

CREATE TABLE api_keys (
  id           TEXT PRIMARY KEY,           -- uuid
  user_id      TEXT NOT NULL REFERENCES users(id),
  key_prefix   TEXT NOT NULL,              -- first 8 chars of the secret, indexed
  key_hash     TEXT NOT NULL,              -- bcrypt
  label        TEXT,                       -- "laptop", "claude-code", etc.
  created_at   TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  last_used_at TIMESTAMP,
  expires_at   TIMESTAMP,
  revoked_at   TIMESTAMP
);
CREATE INDEX idx_api_keys_prefix ON api_keys(key_prefix);

CREATE TABLE requests (
  id            TEXT PRIMARY KEY,          -- uuid
  user_id       TEXT NOT NULL REFERENCES users(id),
  api_key_id    TEXT NOT NULL REFERENCES api_keys(id),
  endpoint      TEXT NOT NULL,             -- /api/chat etc
  model         TEXT,
  backend       TEXT,                      -- m5-max | m5-pro
  status_code   INTEGER NOT NULL,
  prompt_tokens INTEGER,
  output_tokens INTEGER,
  latency_ms    INTEGER NOT NULL,
  started_at    TIMESTAMP NOT NULL,
  ended_at      TIMESTAMP NOT NULL,
  error         TEXT
);
CREATE INDEX idx_requests_user_started ON requests(user_id, started_at);
CREATE INDEX idx_requests_started ON requests(started_at);

CREATE TABLE dashboard_sessions (
  id           TEXT PRIMARY KEY,
  email        TEXT NOT NULL,              -- from Cf-Access header
  first_seen   TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  last_seen    TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
```

## Routing & queueing (Felix owns refinement)

- Backend selection per request:
  1. If model is in M5 Max's `loaded_models` set and M5 Max queue depth < 2 → M5 Max
  2. Elif M5 Max can pull/load the model AND M5 Max queue depth < 2 → M5 Max
  3. Elif M5 Pro available → M5 Pro
  4. Else 503 with retry-after
- "Queue depth" = number of in-flight gateway requests bound to that backend (we track this in-memory; no per-server probe needed — Ollama doesn't expose it directly)
- Failover on backend HTTP error: retry once on the next backend, then 502
- **Locked off-limits:** `qwen3.6:35b` on M5 Pro — psychrx POC reservation. Reject student requests for this model with 403.

## Rate limiting

Sliding window per user:
- `daily_request_limit` (default 200)
- `daily_token_limit` (default 500k)
- 429 with `Retry-After` header when exceeded

## Dashboard (Juno owns)

Single page at `/dashboard/`. Astro static output OR vanilla HTML + HTMX — whichever is simpler. **No build step preferred.**

Sections:
1. **Header** — logged-in email, "log out" link (CF Access logout URL)
2. **Backend status grid** — two cards (M5 Max / M5 Pro): online dot, models loaded, in-flight count. Polls `/api/status` every 3s.
3. **My usage today** — requests today / limit, tokens today / limit, last 10 requests
4. **My API keys** — list (label, prefix, last-used). "Mint new key" button (calls `/api/admin/users/me/keys` if admin, or shows "ask Jay" otherwise).
5. **Quickstart** — link to onboarding doc
6. **Admin panel** (only visible if email matches `ADMIN_EMAIL` env var) — user list, create user, view all-user usage

Style: clean, data-dense, monospace for technical bits. Match the visual tone of fit-sites (warm, professional, not clinical).

## CLI (MacGyver owns)

Lightweight Python package `ewok_lab` published to GitHub (not PyPI for v1 — install via `pip install git+https://...`).

```
ewok-lab login              # prompts for API key, saves to ~/.ewok-lab/config.toml
ewok-lab status             # shows backend health
ewok-lab models             # lists available models
ewok-lab chat <model>       # interactive chat
ewok-lab serve              # starts a localhost:11435 OpenAI/Ollama-compatible proxy
                            # so any tool that speaks Ollama (Continue, Claude Code via custom command, etc) just works
```

The `serve` subcommand is the killer feature: students point any Ollama-aware tool at `http://localhost:11435` and the CLI handles the auth+TLS to the gateway transparently.

## Student CLAUDE.md template (Felix owns)

A drop-in file students place at the top of their Claude Code project. Encodes the orchestrator-plus-muscle pattern:
- Claude Code on the student's laptop = orchestrator
- The gateway = "muscle" (heavy LLM compute)
- Students invoke local muscle via `ewok-lab chat <model> < prompt.txt` or via `ewok-lab serve` + an Ollama-aware tool
- Sample bash recipes
- Cost/quota awareness ("you have 200 requests/day")
- When to use cloud Claude vs lab muscle (deep reasoning vs bulk/structured work)

Template lives at `docs/claude-md-template.md`. Student copies to their project root as `CLAUDE.md` (or appends to existing).

## Onboarding doc (Nate owns)

Lives at `docs/student-onboarding.md`. Sections:
1. What this is (one paragraph)
2. Step 1: I'll send you a CF Access email invite — accept it
3. Step 2: Visit `lab.counselorjay.com/dashboard/`, get your API key
4. Step 3: `pip install git+https://github.com/sophieclawjay/student-lab#subdirectory=cli`
5. Step 4: `ewok-lab login` — paste key
6. Step 5: `ewok-lab serve` — leave it running, then point your tool at `http://localhost:11435`
7. Plus: how to use with Claude Code (link to CLAUDE.md template)
8. Plus: rate limits, etiquette ("don't run training loops"), how to ask for more
9. Troubleshooting

Tone: warm, mentor-style, not corporate. Jay reviews before publishing.

## Cloudflare setup (Ewok handles last, after gateway runs locally)

1. DNS: CNAME `lab.counselorjay.com` → tunnel UUID's `cfargotunnel.com` host
2. Tunnel: add `lab.counselorjay.com` to existing M5 Pro tunnel (or new tunnel — TBD by Felix based on whether reusing the shared tunnel UUID `10ea75cb...` is appropriate or if isolation is preferred). Token: `cloudflare_api_jay.env`.
3. Access: Self-hosted application
   - Path `/dashboard/*` → policy "Student email allowlist"
   - Path `/api/admin/*` → policy "Jay only" (`jay@counselorjay.com`)
   - Everything else → bypass

## File / repo layout (this project root)

```
student-lab/
├── ARCHITECTURE.md             ← this doc
├── SESSION.md
├── MEMORY.md
├── README.md                   ← Nate writes after v1 ships
├── output/                     ← only verified deliverables
├── .tmp/                       ← scratch, agent intermediate
├── team-inbox/                 ← agent ↔ ewok handoffs
├── gateway/                    ← MacGyver
│   ├── pyproject.toml
│   ├── app/
│   │   ├── main.py             ← FastAPI
│   │   ├── auth.py
│   │   ├── router.py           ← backend selection + queue
│   │   ├── proxy.py            ← Ollama passthrough
│   │   ├── db.py
│   │   ├── models.py
│   │   ├── admin.py
│   │   └── config.py
│   ├── data/                   ← SQLite, gitignored
│   ├── tests/
│   └── README.md
├── dashboard/                  ← Juno
│   ├── index.html              ← if vanilla
│   │   OR
│   ├── package.json + src/     ← if Astro
│   └── README.md
├── cli/                        ← MacGyver
│   ├── pyproject.toml
│   ├── ewok_lab/
│   │   ├── __init__.py
│   │   ├── cli.py
│   │   ├── config.py
│   │   └── proxy_server.py     ← localhost:11435
│   └── README.md
├── docs/
│   ├── student-onboarding.md   ← Nate
│   └── claude-md-template.md   ← Felix
└── infra/
    ├── cloudflare-tunnel.yml   ← Ewok writes during cutover
    └── launchd/
        └── com.studentlab.gateway.plist
```

## Verification gates

- **Light:** unit tests pass + curl localhost works
- **Standard:** dashboard loads, API key auth works, log row written
- **Full (required for output/):** end-to-end through `lab.counselorjay.com` from a non-Tailscale network, CF Access email login works, API key auth works, request shows up in admin usage view

## Risks & open questions

- M5 Pro hosting both the gateway AND general-purpose Ollama load may cause contention. Felix to weigh in.
- M3 Pro is excluded from the student fleet (Jay 2026-04-24). It's the daily driver and stays out of the shared rotation. Two-backend topology: M5 Max + M5 Pro only.
- Streaming passthrough through Cloudflare Tunnel works but token counting requires teeing the stream. MacGyver to confirm.
- Should we expire dashboard API keys by default? Default `expires_at = NULL` for v1; revisit.
