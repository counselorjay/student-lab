# Infra

Files in this directory are templates and references for the cutover. Ewok runs the deploy; these files exist so the deploy is reproducible.

## Files

- `cloudflare-tunnel.yml.template` — cloudflared ingress config. Becomes `~/.cloudflared/config-student-lab.yml` on M5 Pro after the tunnel UUID is known.
- `launchd/com.studentlab.gateway.plist` — launchd job for `uvicorn app.main:app --port 8700 --workers 1`. Drops into `~/Library/LaunchAgents/`.
- `launchd/com.cloudflared.studentlab.plist` — launchd job for the cloudflared tunnel. Drops into `~/Library/LaunchAgents/`.

## Deploy sequence (run from M5 Pro)

1. Clone repo to `/Users/sophie/student-lab/`
2. `cd gateway && python3.11 -m venv .venv && source .venv/bin/activate && pip install -e '.[dev]'`
3. `cp .env.example .env`
4. `python -m app.bootstrap admin jay@counselorjay.com --name "Jay"` — capture the printed key once, save to a password manager
5. Run gateway plist: `cp infra/launchd/com.studentlab.gateway.plist ~/Library/LaunchAgents/ && launchctl load ~/Library/LaunchAgents/com.studentlab.gateway.plist`
6. Smoke: `curl http://localhost:8700/healthz` returns 200
7. `cloudflared tunnel create student-lab` → captures UUID + creds
8. Render `cloudflare-tunnel.yml.template` with the UUID, save to `~/.cloudflared/config-student-lab.yml`
9. `cloudflared tunnel route dns student-lab lab.counselorjay.com` (creates the CNAME on `jay@counselorjay.com` Cloudflare account)
10. Run cloudflared plist: `cp infra/launchd/com.cloudflared.studentlab.plist ~/Library/LaunchAgents/ && launchctl load ~/Library/LaunchAgents/com.cloudflared.studentlab.plist`
11. Configure Cloudflare Access in the dashboard (or via API) — see "Access policies" below
12. Smoke: `curl https://lab.counselorjay.com/healthz` returns 200 from off-Tailnet

## Access policies

Self-hosted Application: `lab.counselorjay.com`. Three policies:

| Path glob | Decision | Identity rule |
|---|---|---|
| `/api/admin/*`, `/api/dashboard/users/me/keys` | Allow | Email is `jay@counselorjay.com` |
| `/dashboard/*`, `/api/dashboard/*` | Allow | Email is in student allowlist |
| `/healthz`, `/api/*` (everything else) | Bypass | Public (gateway uses API key bearer) |

Identity provider: Cloudflare One-Time-PIN (email magic link).
Session TTL: 24h.

## Rollback

- Gateway: `launchctl unload ~/Library/LaunchAgents/com.studentlab.gateway.plist`
- Tunnel: `launchctl unload ~/Library/LaunchAgents/com.cloudflared.studentlab.plist`
- DNS: delete the `lab` CNAME in Cloudflare dashboard or via API
- Repo: `gh repo delete Counselor-Sophie/student-lab` (one-way, careful)
