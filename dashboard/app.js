/* ---------------------------------------------------------------------------
   Counselor Jay AI Lab : dashboard logic
   No build, no bundler, no framework. Vanilla ES2022 + fetch + setInterval.
   Pairs with index.html and styles.css.

   Auth model (post-CF-Access rewire):
     Default path: identity comes from Cloudflare Access via the
       Cf-Access-Authenticated-User-Email header. The dashboard hits
       /api/dashboard/whoami (no Bearer) on boot, branches on the response,
       then polls /api/dashboard/me for keys + usage + admin gate.
     Dev path (?dev=1): the legacy paste-key flow is exposed as a secondary
       affordance so QA can smoke-test against a running gateway without CF
       Access in the loop.
     Mock path (?mock=*): network is bypassed entirely; whoami and
       dashboard/me are answered from in-memory fixtures.
   --------------------------------------------------------------------------- */

(() => {
  "use strict";

  // -------------------------------------------------------------------------
  // Config
  // -------------------------------------------------------------------------
  const PARAMS = new URLSearchParams(location.search);
  const MOCK_RAW = PARAMS.get("mock");
  const MOCK = PARAMS.has("mock");
  const ADMIN_VIEW = MOCK_RAW === "admin";        // ?mock=admin forces admin fixture
  const FIRST_ADMIN = MOCK_RAW === "firstadmin";  // ?mock=firstadmin: admin, no keys yet
  const HIGH_USE = MOCK_RAW === "high";           // ?mock=high forces near-quota fixture
  const DEGRADED = MOCK_RAW === "degraded";       // ?mock=degraded forces a downed backend
  const DEV_MODE = PARAMS.get("dev") === "1";     // ?dev=1 exposes the paste-key affordance

  // Gateway base URL. Override with ?gateway=http://host:port. Defaults to
  // same-origin when served by FastAPI in production, localhost in dev.
  const DEFAULT_GATEWAY = location.origin.startsWith("http")
    && !location.origin.startsWith("file://")
      ? "" // same-origin: gateway serves the dashboard
      : "http://localhost:8700";
  const GATEWAY = PARAMS.get("gateway") ?? DEFAULT_GATEWAY;

  const KEY_STORAGE = "ewok_lab_key";
  const POLL_STATUS_MS = 3000;
  const POLL_ME_MS = 10000;

  // -------------------------------------------------------------------------
  // Identity state, set by whoami on boot, refreshed when policy demands it.
  // -------------------------------------------------------------------------
  const identity = {
    email: null,
    name: null,
    user_id: null,
    is_admin: false,
    has_any_active_key: false,
    resolved: false,    // whoami completed at least once
    cf_access_ok: true, // false if /api/dashboard/whoami returned 401
  };

  // -------------------------------------------------------------------------
  // Mock fixtures
  // -------------------------------------------------------------------------
  function mockWhoami() {
    if (FIRST_ADMIN) {
      return {
        email: "jay@counselorjay.com",
        name: null,
        user_id: null,
        is_admin: true,
        has_any_active_key: false,
      };
    }
    if (ADMIN_VIEW) {
      return {
        email: "jay@counselorjay.com",
        name: "Jay Park",
        user_id: "u_jay",
        is_admin: true,
        has_any_active_key: true,
      };
    }
    // ?mock=1, ?mock=high, ?mock=degraded all default to a normal student
    return {
      email: "tanvi@example.edu",
      name: "Tanvi Pyla",
      user_id: "u_5f3a",
      is_admin: false,
      has_any_active_key: true,
    };
  }

  const MOCK_DATA = {
    me: () => ({
      user_id: ADMIN_VIEW ? "u_jay" : "u_5f3a",
      email: ADMIN_VIEW ? "jay@counselorjay.com" : "tanvi@example.edu",
      name: ADMIN_VIEW ? "Jay Park" : "Tanvi Pyla",
      is_admin: ADMIN_VIEW,
      quotas: { requests_per_day: 200, tokens_per_day: 500000 },
      used: HIGH_USE
        ? { requests_today: 184, tokens_today: 472310 }
        : { requests_today: 23, tokens_today: 41280 },
      keys: [
        { id: "k_a1", label: "laptop", prefix: "slk_a1b2c3d4",
          last_used_at: minutesAgo(4), created_at: daysAgo(12), expires_at: null },
        { id: "k_a2", label: "claude-code", prefix: "slk_9f8e7d6c",
          last_used_at: hoursAgo(2), created_at: daysAgo(3), expires_at: null },
      ],
      recent_requests: buildMockRequests(10),
    }),
    status: () => ({
      backends: [
        {
          name: "M5 Max", host: "100.83.184.88:11434",
          online: !DEGRADED,
          models_loaded: ["qwen3.5:35b-a3b-nvfp4", "gemma4:31b"],
          queue_depth: DEGRADED ? 0 : 1,
          last_check: nowIso(),
        },
        {
          name: "M5 Pro", host: "100.120.197.64:11434",
          online: true,
          models_loaded: ["qwen3.5:35b-a3b-nvfp4", "nomic-embed-text"],
          queue_depth: 0,
          last_check: nowIso(),
        },
      ],
      queue: DEGRADED ? [] : [
        { user_email_redacted: "t***@example.edu", model: "qwen3.5:35b-a3b-nvfp4", started_at: secondsAgo(8), est_tokens: 1200 },
      ],
    }),
    adminUsers: () => [
      { id: "u_5f3a", email: "tanvi@example.edu", name: "Tanvi Pyla",
        requests_today: 23, tokens_today: 41280, last_seen_at: minutesAgo(4) },
      { id: "u_2c9b", email: "marcus@example.edu", name: "Marcus Lin",
        requests_today: 7, tokens_today: 12440, last_seen_at: hoursAgo(1) },
      { id: "u_8e1d", email: "priya@example.edu", name: "Priya Nair",
        requests_today: 0, tokens_today: 0, last_seen_at: daysAgo(2) },
    ],
    adminFeed: () => buildMockRequests(15, true),
  };

  function nowIso() { return new Date().toISOString(); }
  function secondsAgo(s) { return new Date(Date.now() - s * 1000).toISOString(); }
  function minutesAgo(m) { return new Date(Date.now() - m * 60_000).toISOString(); }
  function hoursAgo(h) { return new Date(Date.now() - h * 3_600_000).toISOString(); }
  function daysAgo(d) { return new Date(Date.now() - d * 86_400_000).toISOString(); }

  function buildMockRequests(n, withUser = false) {
    const models = ["qwen3.5:35b-a3b-nvfp4", "gemma4:31b", "gemma4:e4b", "nomic-embed-text"];
    const backends = ["m5-max", "m5-pro"];
    const users = ["tanvi@example.edu", "marcus@example.edu", "priya@example.edu"];
    const out = [];
    for (let i = 0; i < n; i++) {
      out.push({
        id: `r_${i}`,
        user_email: withUser ? users[i % users.length] : undefined,
        model: models[i % models.length],
        backend: backends[i % backends.length],
        status_code: i === 4 ? 429 : 200,
        prompt_tokens: 200 + i * 30,
        output_tokens: 400 + i * 80,
        latency_ms: 800 + i * 220,
        started_at: minutesAgo(i * 7 + 1),
      });
    }
    return out;
  }

  // -------------------------------------------------------------------------
  // Tiny DOM helpers (no library)
  // -------------------------------------------------------------------------
  const $ = (sel) => document.querySelector(sel);

  function el(tag, attrs = {}, ...children) {
    const node = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) {
      if (k === "class") node.className = v;
      else if (k === "html") node.innerHTML = v;
      else if (k.startsWith("on") && typeof v === "function") {
        node.addEventListener(k.slice(2), v);
      } else if (v !== false && v != null) {
        node.setAttribute(k, v);
      }
    }
    for (const c of children) {
      if (c == null) continue;
      node.append(c.nodeType ? c : document.createTextNode(String(c)));
    }
    return node;
  }

  function relTime(iso) {
    if (!iso) return "never";
    const ms = Date.now() - new Date(iso).getTime();
    if (ms < 0) return "just now";
    const s = Math.floor(ms / 1000);
    if (s < 60) return `${s}s ago`;
    const m = Math.floor(s / 60);
    if (m < 60) return `${m}m ago`;
    const h = Math.floor(m / 60);
    if (h < 24) return `${h}h ago`;
    const d = Math.floor(h / 24);
    return `${d}d ago`;
  }

  function fmtNum(n) {
    if (n == null || Number.isNaN(n)) return "-";
    return n.toLocaleString("en-US");
  }

  function pctClass(p) {
    if (p < 0.6) return "low";
    if (p < 0.85) return "mid";
    return "high";
  }

  // -------------------------------------------------------------------------
  // Fetch helpers
  //
  // Two flavors:
  //   fetchCF(path, opts)   : CF-Access-gated endpoints. No Bearer header.
  //                            The browser carries the CF Access cookie;
  //                            the gateway reads Cf-Access-Authenticated-User-Email.
  //   fetchBearer(path)     : legacy Bearer-gated endpoints. Used only in the
  //                            ?dev=1 paste-key affordance.
  //   fetchPublic(path)     : public endpoints (e.g. /api/status).
  // -------------------------------------------------------------------------
  async function fetchCF(path, opts = {}) {
    if (MOCK) return mockFetch(path, opts);
    const headers = new Headers(opts.headers || {});
    if (opts.body && !headers.has("Content-Type")) {
      headers.set("Content-Type", "application/json");
    }
    const url = path.startsWith("http") ? path : `${GATEWAY}${path}`;
    // credentials: "include" so the CF Access session cookie is sent on
    // cross-origin dev (file:// / localhost) as well as same-origin prod.
    const res = await fetch(url, { ...opts, headers, credentials: "include" });
    if (res.status === 401) {
      const err = new Error("cf_access_required");
      err.code = 401;
      throw err;
    }
    if (res.status === 403) {
      const err = new Error("forbidden");
      err.code = 403;
      throw err;
    }
    if (res.status === 404) {
      const err = new Error("not_found");
      err.code = 404;
      throw err;
    }
    if (!res.ok) {
      let detail = "";
      try { detail = (await res.json()).error?.message || ""; } catch {}
      throw new Error(`HTTP ${res.status}${detail ? `: ${detail}` : ""}`);
    }
    if (res.status === 204) return null;
    return res.json();
  }

  async function fetchPublic(path, opts = {}) {
    if (MOCK) return mockFetch(path, opts);
    const url = path.startsWith("http") ? path : `${GATEWAY}${path}`;
    const res = await fetch(url, opts);
    if (!res.ok) {
      throw new Error(`HTTP ${res.status}`);
    }
    return res.json();
  }

  async function fetchBearer(path, opts = {}) {
    if (MOCK) return mockFetch(path, opts);
    const key = localStorage.getItem(KEY_STORAGE);
    const headers = new Headers(opts.headers || {});
    if (key) headers.set("Authorization", `Bearer ${key}`);
    if (opts.body && !headers.has("Content-Type")) {
      headers.set("Content-Type", "application/json");
    }
    const url = path.startsWith("http") ? path : `${GATEWAY}${path}`;
    const res = await fetch(url, { ...opts, headers });
    if (res.status === 401) {
      localStorage.removeItem(KEY_STORAGE);
      promptForKey();
      throw new Error("unauthorized");
    }
    if (!res.ok) {
      let detail = "";
      try { detail = (await res.json()).error?.message || ""; } catch {}
      throw new Error(`HTTP ${res.status}${detail ? `: ${detail}` : ""}`);
    }
    if (res.status === 204) return null;
    return res.json();
  }

  function mockFetch(path, opts = {}) {
    return new Promise((resolve, reject) => {
      setTimeout(() => {
        if (path === "/api/dashboard/whoami") return resolve(mockWhoami());
        if (path === "/api/dashboard/me") {
          if (FIRST_ADMIN) {
            // No User row exists yet: real backend returns 404. Simulate.
            const err = new Error("not_found");
            err.code = 404;
            return reject(err);
          }
          return resolve(MOCK_DATA.me());
        }
        if (path === "/api/dashboard/users/me/keys" && opts.method === "POST") {
          return resolve({
            id: "k_new",
            user_id: ADMIN_VIEW || FIRST_ADMIN ? "u_jay" : "u_5f3a",
            label: (() => {
              try { return JSON.parse(opts.body || "{}").label || "first-key"; }
              catch { return "first-key"; }
            })(),
            key_prefix: "slk_" + cryptoHex(8),
            api_key: "slk_" + cryptoHex(32),
            expires_at: null,
          });
        }
        if (path === "/api/me") return resolve(MOCK_DATA.me());
        if (path === "/api/status") return resolve(MOCK_DATA.status());
        if (path === "/api/admin/users") {
          if (opts.method === "POST") {
            return resolve({ ok: true, id: "u_new", api_key: "slk_" + cryptoHex(32) });
          }
          return resolve({ users: MOCK_DATA.adminUsers() });
        }
        if (path.startsWith("/api/admin/usage")) {
          return resolve({ requests: MOCK_DATA.adminFeed() });
        }
        resolve({});
      }, 120);
    });
  }

  function cryptoHex(n) {
    const buf = new Uint8Array(n / 2);
    crypto.getRandomValues(buf);
    return Array.from(buf, (b) => b.toString(16).padStart(2, "0")).join("");
  }

  // -------------------------------------------------------------------------
  // API key dialog (dev-mode paste-key affordance only)
  // -------------------------------------------------------------------------
  function promptForKey() {
    const dlg = $("#key-dialog");
    const err = $("#key-error");
    err.classList.add("hidden");
    if (!dlg.open) dlg.showModal();
  }

  function wireKeyDialog() {
    const dlg = $("#key-dialog");
    const form = $("#key-form");
    const input = $("#key-input");
    const err = $("#key-error");

    form.addEventListener("submit", (e) => {
      e.preventDefault();
      const v = input.value.trim();
      if (!v.startsWith("slk_") || v.length < 16) {
        err.textContent = "Key should start with slk_ and be at least 16 characters.";
        err.classList.remove("hidden");
        return;
      }
      localStorage.setItem(KEY_STORAGE, v);
      input.value = "";
      dlg.close();
      // immediate re-poll via the dev path
      pollMeDev(true);
    });

    $("#key-cancel").addEventListener("click", () => dlg.close());

    // Wire the dev-mode trigger link.
    const devLink = $("#dev-paste-key-link");
    if (devLink) {
      devLink.addEventListener("click", (e) => {
        e.preventDefault();
        promptForKey();
      });
    }
  }

  // -------------------------------------------------------------------------
  // Renderers
  // -------------------------------------------------------------------------
  function renderHeaderEmail(email) {
    $("#user-email").textContent = email || "(no identity)";
  }

  function setOverallHealth(status) {
    const dot = $("#overall-dot");
    const label = $("#overall-label");
    const onlineCount = status.backends.filter((b) => b.online).length;
    const total = status.backends.length;
    dot.classList.remove("online", "degraded", "offline", "unknown");
    if (onlineCount === total) {
      dot.classList.add("online");
      label.textContent = "all systems online";
    } else if (onlineCount === 0) {
      dot.classList.add("offline");
      label.textContent = "all backends offline";
    } else {
      dot.classList.add("degraded");
      label.textContent = `${onlineCount}/${total} online`;
    }
  }

  function renderBackends(status) {
    const grid = $("#backend-grid");
    grid.innerHTML = "";
    for (const b of status.backends) {
      const card = el("div", { class: "rounded-lg border border-zinc-200 bg-white p-4 shadow-sm" },
        el("div", { class: "flex items-center justify-between mb-2" },
          el("div", { class: "flex items-center gap-2" },
            el("span", { class: `dot ${b.online ? "online" : "offline"}`, "aria-hidden": "true" }),
            el("span", { class: "text-sm font-semibold tracking-tight" }, b.name),
          ),
          el("span", { class: "text-[11px] mono text-zinc-500" }, b.online ? "online" : "offline"),
        ),
        el("div", { class: "mono text-[11px] text-zinc-500 mb-3 truncate" }, b.host),
        el("div", { class: "flex items-baseline justify-between mb-1" },
          el("span", { class: "text-[11px] uppercase tracking-wider text-zinc-500" }, "In flight"),
          el("span", { class: "mono text-sm font-semibold" }, String(b.queue_depth ?? 0)),
        ),
        el("div", { class: "mt-3" },
          el("div", { class: "text-[11px] uppercase tracking-wider text-zinc-500 mb-1" }, "Loaded"),
          el("div", { class: "flex flex-wrap gap-1" },
            ...(b.models_loaded?.length
              ? b.models_loaded.map((m) =>
                  el("span", { class: "mono text-[11px] px-1.5 py-0.5 rounded bg-zinc-100 text-zinc-700" }, m))
              : [el("span", { class: "text-[11px] text-zinc-400" }, "none")]),
          ),
        ),
      );
      grid.append(card);
    }

    const q = status.queue ?? [];
    $("#queue-summary").textContent = q.length === 0
      ? "Queue idle."
      : `${q.length} request${q.length === 1 ? "" : "s"} in flight across the fleet.`;
  }

  function flashIfChanged(elNode, newValue) {
    const prev = elNode.dataset.value;
    elNode.textContent = fmtNum(newValue);
    elNode.dataset.value = String(newValue);
    if (prev != null && prev !== String(newValue)) {
      elNode.classList.add("flashed");
      setTimeout(() => elNode.classList.remove("flashed"), 600);
    }
  }

  function renderUsage(me) {
    const reqUsed = me.used?.requests_today ?? 0;
    const reqLimit = me.quotas?.requests_per_day ?? 0;
    const tokUsed = me.used?.tokens_today ?? 0;
    const tokLimit = me.quotas?.tokens_per_day ?? 0;

    flashIfChanged($("#req-used"), reqUsed);
    $("#req-limit").textContent = fmtNum(reqLimit);
    flashIfChanged($("#tok-used"), tokUsed);
    $("#tok-limit").textContent = fmtNum(tokLimit);

    const reqPct = reqLimit > 0 ? Math.min(1, reqUsed / reqLimit) : 0;
    const tokPct = tokLimit > 0 ? Math.min(1, tokUsed / tokLimit) : 0;

    const reqBar = $("#req-bar");
    reqBar.style.width = `${(reqPct * 100).toFixed(1)}%`;
    reqBar.className = `bar-fill ${pctClass(reqPct)}`;

    const tokBar = $("#tok-bar");
    tokBar.style.width = `${(tokPct * 100).toFixed(1)}%`;
    tokBar.className = `bar-fill ${pctClass(tokPct)}`;
  }

  function renderRequests(me) {
    const tbody = $("#req-rows");
    tbody.innerHTML = "";
    const rows = me.recent_requests ?? [];
    if (rows.length === 0) {
      tbody.append(el("tr", {},
        el("td", { colspan: 5, class: "py-4 text-center text-zinc-400" },
          "No requests yet today.")));
      return;
    }
    for (const r of rows.slice(0, 10)) {
      const errored = r.status_code && r.status_code >= 400;
      const tokens = (r.prompt_tokens ?? 0) + (r.output_tokens ?? 0);
      tbody.append(el("tr", { class: "border-b border-zinc-100" },
        el("td", { class: "py-2 pr-3 text-zinc-500", title: r.started_at }, relTime(r.started_at)),
        el("td", { class: "py-2 pr-3" }, r.model || "-"),
        el("td", { class: "py-2 pr-3 text-zinc-600" }, r.backend || "-"),
        el("td", { class: `py-2 pr-3 text-right ${errored ? "text-rose-600" : ""}` },
          errored ? `${r.status_code}` : `${fmtNum(r.latency_ms)} ms`),
        el("td", { class: "py-2 pl-3 text-right" }, fmtNum(tokens)),
      ));
    }
  }

  function renderKeys(me) {
    const list = $("#keys-list");
    list.innerHTML = "";
    const keys = me.keys ?? [];
    if (keys.length === 0) {
      list.append(el("div", { class: "py-3 text-sm text-zinc-500" },
        "No API keys yet."));
    } else {
      for (const k of keys) {
        list.append(el("div", { class: "py-3 flex items-center justify-between gap-3" },
          el("div", { class: "min-w-0" },
            el("div", { class: "flex items-center gap-2 mb-0.5" },
              el("span", { class: "text-sm font-medium" }, k.label || "(unlabeled)"),
              k.revoked_at
                ? el("span", { class: "text-[10px] uppercase tracking-wider text-rose-600" }, "revoked")
                : null,
              k.expires_at
                ? el("span", { class: "text-[10px] uppercase tracking-wider text-zinc-400" }, "expires " + relTime(k.expires_at))
                : null,
            ),
            el("div", { class: "mono text-[12px] text-zinc-500" }, (k.prefix || k.key_prefix || "") + "…"),
          ),
          el("div", { class: "text-[11px] text-zinc-500 mono whitespace-nowrap", title: k.last_used_at || "" },
            "last used " + relTime(k.last_used_at)),
        ));
      }
    }

    const help = $("#keys-help");
    const mintBtn = $("#mint-key-btn");
    if (me.is_admin) {
      help.classList.add("hidden");
      mintBtn.classList.remove("hidden");
    } else {
      help.classList.remove("hidden");
      mintBtn.classList.add("hidden");
    }
  }

  // -------------------------------------------------------------------------
  // Identity-driven UI states
  // -------------------------------------------------------------------------
  function showCfAccessRequired() {
    // Hide identity-bearing sections; show the "open through lab.counselorjay.com"
    // banner so the user knows what's going on.
    $("#identity-state-cf").classList.remove("hidden");
    $("#identity-state-pending").classList.add("hidden");
    $("#identity-state-mint").classList.add("hidden");
    $("#main-app").classList.add("hidden");
  }

  function showPendingMembership(email) {
    $("#identity-state-cf").classList.add("hidden");
    $("#identity-state-pending").classList.remove("hidden");
    $("#identity-state-mint").classList.add("hidden");
    $("#main-app").classList.add("hidden");
    $("#pending-email").textContent = email || "you";
  }

  function showMintFirstKey(email) {
    $("#identity-state-cf").classList.add("hidden");
    $("#identity-state-pending").classList.add("hidden");
    $("#identity-state-mint").classList.remove("hidden");
    $("#main-app").classList.add("hidden");
    $("#mint-first-email").textContent = email || "your account";
  }

  function showMainApp() {
    $("#identity-state-cf").classList.add("hidden");
    $("#identity-state-pending").classList.add("hidden");
    $("#identity-state-mint").classList.add("hidden");
    $("#main-app").classList.remove("hidden");
  }

  // -------------------------------------------------------------------------
  // Admin
  // -------------------------------------------------------------------------
  function showAdmin(me) {
    if (!me.is_admin) {
      $("#admin-section").classList.add("hidden");
      return;
    }
    $("#admin-section").classList.remove("hidden");
    pollAdmin();
  }

  async function pollAdmin() {
    try {
      const [users, feed] = await Promise.all([
        fetchCF("/api/admin/users"),
        fetchCF("/api/admin/usage?from=" + encodeURIComponent(secondsAgo(3600))),
      ]);
      renderAdminUsers(users.users ?? []);
      renderAdminFeed(feed.requests ?? []);
    } catch (e) {
      // Soft-fail in mock or when admin endpoints aren't ready
      console.warn("admin poll failed:", e.message);
    }
  }

  function renderAdminUsers(users) {
    const tbody = $("#admin-users");
    tbody.innerHTML = "";
    if (!users.length) {
      tbody.append(el("tr", {},
        el("td", { colspan: 5, class: "py-4 text-center text-zinc-400" }, "No users yet.")));
      return;
    }
    for (const u of users) {
      tbody.append(el("tr", { class: "border-b border-zinc-100" },
        el("td", { class: "py-2 pr-3" }, u.email),
        el("td", { class: "py-2 pr-3 text-zinc-600" }, u.name || ""),
        el("td", { class: "py-2 pr-3 text-right" }, fmtNum(u.requests_today)),
        el("td", { class: "py-2 pr-3 text-right" }, fmtNum(u.tokens_today)),
        el("td", { class: "py-2 pl-3 text-zinc-500" }, relTime(u.last_seen_at)),
      ));
    }
  }

  function renderAdminFeed(rows) {
    const tbody = $("#admin-feed");
    tbody.innerHTML = "";
    if (!rows.length) {
      tbody.append(el("tr", {},
        el("td", { colspan: 6, class: "py-4 text-center text-zinc-400" }, "No recent activity.")));
      return;
    }
    for (const r of rows.slice(0, 15)) {
      const errored = r.status_code && r.status_code >= 400;
      const tokens = (r.prompt_tokens ?? 0) + (r.output_tokens ?? 0);
      tbody.append(el("tr", { class: "border-b border-zinc-100" },
        el("td", { class: "py-2 pr-3 text-zinc-500", title: r.started_at }, relTime(r.started_at)),
        el("td", { class: "py-2 pr-3" }, r.user_email || "-"),
        el("td", { class: "py-2 pr-3" }, r.model || "-"),
        el("td", { class: "py-2 pr-3 text-zinc-600" }, r.backend || "-"),
        el("td", { class: `py-2 pr-3 text-right ${errored ? "text-rose-600" : ""}` },
          errored ? `${r.status_code}` : `${fmtNum(r.latency_ms)} ms`),
        el("td", { class: "py-2 pl-3 text-right" }, fmtNum(tokens)),
      ));
    }
  }

  function wireAdminForms() {
    $("#create-user-form").addEventListener("submit", async (e) => {
      e.preventDefault();
      const fd = new FormData(e.target);
      const body = {
        email: fd.get("email"),
        name: fd.get("name"),
        daily_request_limit: Number(fd.get("daily_request_limit")),
        daily_token_limit: Number(fd.get("daily_token_limit")),
      };
      const status = $("#create-user-status");
      status.textContent = "Creating...";
      try {
        const res = await fetchCF("/api/admin/users", {
          method: "POST", body: JSON.stringify(body),
        });
        status.textContent = `Created ${body.email}.`;
        e.target.reset();
        if (res?.api_key) showMintedKey(res.api_key, "Saved. Share with the new user.");
        pollAdmin();
      } catch (err) {
        status.textContent = `Error: ${err.message}`;
      }
    });

    $("#mint-key-btn").addEventListener("click", async () => {
      try {
        const res = await fetchCF("/api/dashboard/users/me/keys", {
          method: "POST", body: JSON.stringify({ label: "dashboard-mint" }),
        });
        if (res?.api_key) showMintedKey(res.api_key);
        // refresh keys list
        pollMeCF();
      } catch (err) {
        alert("Could not mint key: " + err.message);
      }
    });

    // First-admin "Mint your first key" button (lives in the identity-state-mint block).
    const firstMintBtn = $("#mint-first-key-btn");
    if (firstMintBtn) {
      firstMintBtn.addEventListener("click", async () => {
        firstMintBtn.disabled = true;
        firstMintBtn.textContent = "Minting...";
        try {
          const res = await fetchCF("/api/dashboard/users/me/keys", {
            method: "POST", body: JSON.stringify({ label: "first-admin" }),
          });
          if (res?.api_key) {
            showMintedKey(res.api_key);
          }
          // After mint, re-run whoami so identity state advances.
          await bootIdentity();
        } catch (err) {
          alert("Could not mint key: " + err.message);
        } finally {
          // Always reset the button: in production the next bootIdentity()
          // hides this block, but in mock-firstadmin the block stays and the
          // user may want to mint again to re-trigger the modal.
          firstMintBtn.disabled = false;
          firstMintBtn.textContent = "Mint your first key";
        }
      });
    }
  }

  function showMintedKey(value, leadOverride) {
    const dlg = $("#minted-dialog");
    $("#minted-value").value = value;
    if (leadOverride) {
      $("#minted-lead").textContent = leadOverride;
    } else {
      $("#minted-lead").textContent =
        "Copy this now. It is shown only once and cannot be retrieved later.";
    }
    dlg.showModal();
  }

  function wireMintedDialog() {
    $("#minted-close").addEventListener("click", () => $("#minted-dialog").close());
    $("#minted-copy").addEventListener("click", async () => {
      const v = $("#minted-value").value;
      try {
        await navigator.clipboard.writeText(v);
        $("#minted-copy").textContent = "Copied";
        setTimeout(() => $("#minted-copy").textContent = "Copy", 1500);
      } catch {
        $("#minted-value").select();
      }
    });
  }

  // -------------------------------------------------------------------------
  // Polling loop
  // -------------------------------------------------------------------------
  let statusTimer = null;
  let meTimer = null;

  async function pollStatus() {
    try {
      const s = await fetchPublic("/api/status");
      setOverallHealth(s);
      renderBackends(s);
    } catch (e) {
      // Don't spam dialogs from a status failure; just dim the dot
      const dot = $("#overall-dot");
      dot.classList.remove("online", "degraded", "offline");
      dot.classList.add("unknown");
      $("#overall-label").textContent = "no signal";
    }
  }

  // Default (CF Access) path: GET /api/dashboard/me, no Bearer.
  async function pollMeCF() {
    if (!identity.resolved || !identity.user_id) return;
    try {
      const me = await fetchCF("/api/dashboard/me");
      renderHeaderEmail(me.email);
      renderUsage(me);
      renderRequests(me);
      renderKeys(me);
      showAdmin(me);
    } catch (e) {
      if (e.code === 404) {
        // User row was deleted out from under us. Re-run identity.
        await bootIdentity();
        return;
      }
      if (e.code === 401) {
        // CF Access session expired mid-session.
        showCfAccessRequired();
        return;
      }
      console.warn("dashboard/me poll failed:", e.message);
    }
  }

  // Dev path: paste-key Bearer flow against /api/me.
  async function pollMeDev(_immediate = false) {
    if (!MOCK && !localStorage.getItem(KEY_STORAGE)) {
      promptForKey();
      return;
    }
    try {
      const me = await fetchBearer("/api/me");
      renderHeaderEmail(me.email);
      renderUsage(me);
      renderRequests(me);
      renderKeys(me);
      showAdmin(me);
      showMainApp();
    } catch (e) {
      if (e.message !== "unauthorized") console.warn("me poll failed:", e.message);
    }
  }

  function startPolling() {
    pollStatus();
    statusTimer = setInterval(() => {
      if (document.visibilityState === "visible") pollStatus();
    }, POLL_STATUS_MS);

    if (DEV_MODE && !MOCK) {
      // Dev path: paste-key Bearer flow drives the user-facing data.
      pollMeDev(true);
      meTimer = setInterval(() => {
        if (document.visibilityState === "visible") pollMeDev();
      }, POLL_ME_MS);
    } else {
      // Default path: CF Access. The me-poll only fires once identity resolves.
      meTimer = setInterval(() => {
        if (document.visibilityState === "visible") pollMeCF();
      }, POLL_ME_MS);
    }
  }

  // -------------------------------------------------------------------------
  // Identity boot: hit /api/dashboard/whoami and branch.
  // -------------------------------------------------------------------------
  async function bootIdentity() {
    if (DEV_MODE && !MOCK) {
      // Dev mode skips whoami: paste-key flow drives identity.
      identity.resolved = true;
      identity.cf_access_ok = true;
      // pollMeDev will showMainApp() once a key is present.
      showMainApp();
      return;
    }
    try {
      const w = await fetchCF("/api/dashboard/whoami");
      identity.email = w.email ?? null;
      identity.name = w.name ?? null;
      identity.user_id = w.user_id ?? null;
      identity.is_admin = !!w.is_admin;
      identity.has_any_active_key = !!w.has_any_active_key;
      identity.resolved = true;
      identity.cf_access_ok = true;

      renderHeaderEmail(identity.email);

      if (identity.is_admin && !identity.has_any_active_key) {
        showMintFirstKey(identity.email);
        return;
      }
      if (!identity.user_id && !identity.is_admin) {
        showPendingMembership(identity.email);
        return;
      }
      // Normal authenticated user with a User row: load the main app.
      showMainApp();
      pollMeCF();
    } catch (e) {
      if (e.code === 401) {
        identity.cf_access_ok = false;
        showCfAccessRequired();
        return;
      }
      console.warn("whoami failed:", e.message);
      // Soft fall-through: surface CF Access banner so the user has a path forward.
      showCfAccessRequired();
    }
  }

  // -------------------------------------------------------------------------
  // Logout
  // -------------------------------------------------------------------------
  function wireLogout() {
    $("#logout-btn").addEventListener("click", () => {
      // Always clear any stale dev-mode key.
      localStorage.removeItem(KEY_STORAGE);
      if (MOCK) {
        // In mock, just bounce to ?mock=1 so the page reloads cleanly.
        location.href = "?mock=1";
        return;
      }
      // Production and dev-against-real-gateway: terminate the CF Access session.
      location.href = "/cdn-cgi/access/logout";
    });
  }

  // -------------------------------------------------------------------------
  // Dev affordance toggle
  // -------------------------------------------------------------------------
  function wireDevAffordance() {
    if (DEV_MODE) {
      $("#dev-affordance").classList.remove("hidden");
    }
  }

  // -------------------------------------------------------------------------
  // Init
  // -------------------------------------------------------------------------
  function init() {
    $("#gateway-target").textContent = MOCK
      ? "mock fixtures"
      : (GATEWAY || "same-origin");

    wireKeyDialog();
    wireMintedDialog();
    wireAdminForms();
    wireLogout();
    wireDevAffordance();

    document.addEventListener("visibilitychange", () => {
      if (document.visibilityState === "visible") {
        // Catch up immediately when the tab regains focus
        pollStatus();
        if (DEV_MODE && !MOCK) pollMeDev();
        else if (identity.resolved && identity.user_id) pollMeCF();
      }
    });

    startPolling();
    bootIdentity();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
