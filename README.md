# Student Lab

A small set of trusted students get authenticated access to Jay's home AI servers (Apple Silicon Macs running Ollama) by joining his Tailscale network and SSHing directly to the hosts.

**Current architecture (v2, 2026-04-25):** Tailscale + SSH + a CLAUDE.md template. No gateway, no API keys, no dashboard.

## Getting started (students)

Read [`docs/student-onboarding.md`](docs/student-onboarding.md) for the full walkthrough. Five-minute path: accept Jay's Tailscale invite, install Tailscale, SSH to `m5-max`, run `ollama`.

For the orchestrator-plus-muscle Claude Code pattern, drop [`docs/claude-md-template.md`](docs/claude-md-template.md) into your project as `CLAUDE.md`.

## Setting up the hosts (Jay)

[`docs/lab-host-setup.md`](docs/lab-host-setup.md) is the runbook for provisioning M5 Max + M5 Pro with the shared `student` account and enabling Tailscale SSH.

[`docs/tailscale-acl.md`](docs/tailscale-acl.md) has the ACL JSON to paste into `login.tailscale.com/admin/acls`. It allows tagged students to SSH only to the lab hosts as the `student` user.

## Fleet

Two Macs in the student rotation:
- **M5 Max** (primary, 128GB) — Tailscale name `m5-max`. Heavy work, dense models, vision.
- **M5 Pro** (secondary, 48GB) — Tailscale name `m5-pro`. Overflow, also hosts other FastAPI services.

M3 Pro is Jay's daily driver and is **not** in the student rotation. The Tailscale ACL prevents student access to it.

`qwen3.6:35b` is reserved for Jay's psychrx POC. Students see it in `ollama list` but should not call it. There's no enforcement layer in v2 (trust model).

## v1 archive

The `gateway/`, `cli/`, and `dashboard/` directories are an archived v1 architecture (FastAPI + API keys + CF Access + custom dashboard). They were built and tested but never deployed. Kept in the repo as a reference for if the lab outgrows the simple Tailscale model later, or as a starting point for adding logging, quotas, and queue gates if needed in the future.

`gateway/ROUTING.md` and `ARCHITECTURE.md` document that earlier design and are accurate for what's in `gateway/`. They do not describe v2.

## License

Internal tool. Not for redistribution.
