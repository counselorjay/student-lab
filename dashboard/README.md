# Dashboard - Counselor Jay AI Lab

Single-page admin and student dashboard for `lab.counselorjay.com/dashboard/`.

**Stack:** vanilla HTML, vanilla JS, Tailwind via CDN, one custom CSS file. No build step. No bundler. No npm. No external JS deps beyond Tailwind.

## File layout

```
dashboard/
├── index.html      # the entire UI, sectioned
├── app.js          # fetch helpers, polling, render functions, mock fixtures
├── styles.css      # custom CSS layered on Tailwind utilities
├── favicon.svg     # "lab" monogram
└── README.md       # this file
```

## Auth model

The dashboard runs identity-first. On every page load it calls
`GET /api/dashboard/whoami`, which is gated by Cloudflare Access (no Bearer
header is sent). The gateway reads the `Cf-Access-Authenticated-User-Email`
header that CF Access injects and answers with:

```jsonc
{
  "email": "you@example.com",
  "name": "Your Name",          // null if no User row exists yet
  "user_id": "u_5f3a",          // null if no User row exists yet
  "is_admin": true,             // computed from ADMIN_EMAIL match
  "has_any_active_key": false   // false until you mint your first key
}
```

The page then branches on the response:

- `is_admin === true && has_any_active_key === false` → first-admin landing
  page with a "Mint your first key" button. Posting to
  `/api/dashboard/users/me/keys` returns the plaintext key once, in a
  one-time-only modal.
- `user_id === null && is_admin === false` → "you are signed in but Jay has
  not added you to the lab yet" message. No inference UI is exposed.
- `user_id !== null` → the main app loads. Keys, quotas, usage, and recent
  requests come from `GET /api/dashboard/me`, which returns the same shape
  as `/api/me` plus a `keys` array (id, label, prefix, last_used_at,
  created_at).

`/api/status` (the backend grid) is public and unauthenticated. It runs
regardless of identity state.

### Dev affordance: paste-key fallback

For QA against a running gateway without Cloudflare Access in front, append
`?dev=1`. This exposes a small "test API key from browser" link near the
footer that opens the legacy paste-key modal. The pasted key is stored in
`localStorage` under `ewok_lab_key` and used as a `Bearer` against the
legacy `/api/me`. This path is intentionally hidden from the default UI so
real students never see it.

## Develop locally

The dashboard is a static folder. You have three workable modes.

### 1. Mock mode (no backend needed)

Open the page with `?mock=...` and the JS swaps the network layer for
hardcoded fixtures, including the `/api/dashboard/whoami` response:

```
open "/Users/jaypark/Desktop/Claude/projects/student-lab/dashboard/index.html?mock=1"
```

Mock variants:

- `?mock=1` - student view, low usage, all backends online, has 2 mock keys
- `?mock=admin` - admin view (Jay's email), has keys, full Admin panel
- `?mock=firstadmin` - admin view, no keys yet; exercises the "Mint your
  first key" prompt and the one-time-plaintext-key modal
- `?mock=high` - student view near quota, exercises the amber/red bar fills
- `?mock=degraded` - M5 Max reported offline, exercises status colors

Combine the gateway override with mock if you want to confirm same-origin
URL rewriting:

```
open "...index.html?mock=admin&gateway=http://localhost:8700"
```

### 2. Against MacGyver's local gateway (paste-key dev path)

Once the FastAPI gateway is running on `http://localhost:8700` (see
`gateway/README.md`), append `?dev=1`:

```
open "/Users/jaypark/Desktop/Claude/projects/student-lab/dashboard/index.html?dev=1"
```

The dev affordance link near the footer opens the paste-key dialog. Paste
the key Jay (or `python -m gateway.bootstrap`) minted, and the dashboard
will use it as a `Bearer` against `/api/me`.

If you want to point at a different host:

```
open "...index.html?dev=1&gateway=http://100.120.197.64:8700"
```

### 2b. Against MacGyver's local gateway (CF Access path, simulated)

The gateway's `require_cf_access_email` dependency accepts a
`Cf-Access-Authenticated-User-Email` request header in dev so you can
simulate CF Access locally. With curl that looks like:

```
curl -H "Cf-Access-Authenticated-User-Email: jay@counselorjay.com" \
     http://localhost:8700/api/dashboard/whoami
```

The browser cannot inject custom headers, so CF-Access-aware testing in
the browser requires either (a) running the dashboard behind the actual
Cloudflare Tunnel + Access stack, or (b) using `?dev=1` with the
paste-key flow.

### 3. Served by FastAPI in production

The gateway serves this directory as static files at `/dashboard/*` (per
ARCHITECTURE.md). When loaded same-origin, `app.js` uses an empty gateway
base (`""`), so all `fetch("/api/...")` calls go to the same host.
Cloudflare Tunnel + CF Access handle TLS and identity in front of the
gateway. The browser carries the CF Access session cookie automatically;
the dashboard does not store or send any Bearer in this path.

## Configuration knobs

All set via query string:

| Param | Effect |
| --- | --- |
| `mock=1`, `mock=admin`, `mock=firstadmin`, `mock=high`, `mock=degraded` | use fixtures, do not call the network |
| `dev=1` | expose the paste-key affordance for QA against a running gateway without CF Access |
| `gateway=http://host:port` | override gateway base URL |

`localStorage.ewok_lab_key` is only used by the `?dev=1` paste-key path.
The default CF Access path does not touch localStorage. The "log out" link
always redirects to `/cdn-cgi/access/logout` in real environments so users
can actually terminate the CF Access session, not just clear browser state.

## Polling

- `/api/status` every 3s (backend grid, public)
- `/api/dashboard/me` every 10s in the default CF Access path (usage, keys,
  admin gate)
- `/api/me` every 10s in the `?dev=1` paste-key path
- Both polls pause when the tab is hidden and resume immediately on focus.

## Admin gating

The Admin panel is rendered only when `me.is_admin === true` (returned by
`/api/dashboard/me` in the CF Access path or `/api/me` in dev). Minting a
new key for the signed-in admin posts to `/api/dashboard/users/me/keys`
(not the legacy `/api/admin/users/me/keys`); creating a new user still goes
through `/api/admin/users` which now also lives behind CF Access.

## Accessibility & motion

- Color is never the only signal: status dots have aria-hidden and the
  surrounding text says "online / degraded / offline".
- All animations respect `prefers-reduced-motion`.
- Focus-visible ring is consistent across buttons, links, and inputs.
- Tables are real `<table>` markup with `<thead>` and column headers.
- The two modal dialogs are native `<dialog>` elements: keyboard focus
  trap and Escape-to-close are free.

## Verification

Standard tier:

- [x] `index.html?mock=firstadmin` shows the "Mint your first key" prompt
      and the one-time plaintext key modal on click
- [x] `index.html?mock=admin` paints the full admin view with keys list
      populated from mocked `/api/dashboard/me`
- [x] `index.html?mock=1` paints the student view with mocked keys
- [x] `index.html?mock=high` triggers amber/red progress fills
- [x] `index.html?mock=degraded` shows offline dot on M5 Max
- [x] `index.html?dev=1` against a running gateway uses the paste-key flow
- [x] `index.html` (no params) hits `/api/dashboard/whoami` and renders
      identity-first; on 401 shows the "Open through lab.counselorjay.com"
      banner
- [x] No console errors in any of the above
- [x] Reduced-motion check: OS-level reduce motion disables pulses and
      shimmer
- [x] Keyboard nav: Tab cycles header, all section buttons, the modals,
      and the form fields

## Production deployment

The gateway (MacGyver's FastAPI app) mounts this folder as static at
`/dashboard/`:

```python
from fastapi.staticfiles import StaticFiles
app.mount("/dashboard", StaticFiles(directory="../dashboard", html=True), name="dashboard")
```

Cloudflare Tunnel routes `lab.counselorjay.com` to that gateway on M5 Pro
`:8700`. CF Access protects `/dashboard/*` and `/api/dashboard/*` with the
email allowlist. The `/api/status` path stays public; the legacy `/api/me`
and `/api/admin/*` Bearer-gated paths remain available for the dev
affordance and the CLI.

Rollback: there is no build artifact, just `git revert` the dashboard
commit and `launchctl kickstart` the gateway service to re-serve the prior
tree.

## Out of scope (v1)

- Streaming token counters (passthrough only per ARCHITECTURE.md)
- Per-user GPU reservation UI
- Mobile-first layout polish (graceful collapse only; students will use a
  laptop)
- Self-serve key revocation UI (admin-only revoke comes via the gateway
  API; student UX deferred to v2)
- Light/dark theme toggle (zinc palette is theme-agnostic enough for v1)
