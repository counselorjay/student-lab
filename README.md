# Student Lab

Authenticated gateway giving a small set of trusted students access to a local Ollama fleet, without Tailscale and without shell access. Lives at [lab.counselorjay.com](https://lab.counselorjay.com).

## What's inside

| Folder | What it does |
|---|---|
| `gateway/` | FastAPI app on M5 Pro `:8700`. API-key auth, per-user quotas, request logging, model-aware routing, qwen3.6 lockout. |
| `cli/` | `ewok-lab` Python CLI. `login`, `status`, `models`, `chat`, and `serve` (a localhost Ollama-compatible proxy). |
| `dashboard/` | Vanilla HTML + JS dashboard at `/dashboard/`. Cloudflare Access-gated. |
| `docs/` | Student onboarding (`student-onboarding.md`) and the orchestrator-plus-muscle CLAUDE.md template (`claude-md-template.md`). |
| `infra/` | launchd plists and the cloudflared tunnel template. Run-from-M5-Pro deploy scripts. |
| `ARCHITECTURE.md` | Source of truth for the design contract. Read before changing routes, schema, or auth. |
| `gateway/ROUTING.md` | Routing and queueing spec. Read before changing `app/router.py`. |

## Getting started (students)

Read [`docs/student-onboarding.md`](docs/student-onboarding.md). Five-minute walkthrough from accepting the email invite to your first inference call.

For the orchestrator-plus-muscle Claude Code pattern, drop [`docs/claude-md-template.md`](docs/claude-md-template.md) into your project as `CLAUDE.md`.

## Running the gateway locally (admin)

```bash
cd gateway
python3.11 -m venv .venv && source .venv/bin/activate
pip install -e '.[dev]'
cp .env.example .env
python -m app.bootstrap admin jay@counselorjay.com --name "Jay"
uvicorn app.main:app --port 8700
```

Tests: `cd gateway && pytest -q`.

## Production deploy

See [`infra/README.md`](infra/README.md) for the full M5 Pro install + Cloudflare cutover runbook.

## Fleet

Two backends in the student rotation:
- **M5 Max** (primary) — `100.83.184.88:11434`
- **M5 Pro** (secondary, also hosts the gateway) — `100.120.197.64:11434`

M3 Pro is the daily driver and is deliberately excluded from shared rotation.

`qwen3.6:35b` family is reserved for the psychrx POC and returns 403 with a redirect message.

## License

Internal tool. Not for redistribution.
