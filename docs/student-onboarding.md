# Welcome to the Lab

Jay is sharing his home AI servers with you. They are Apple Silicon Macs in his office, running a small fleet of local large language models, reachable from anywhere through Tailscale. There is no per-request logging in this setup. Jay can see Tailscale connection events (which device of yours connected, when, to which host), but the contents of your prompts, responses, and work are not instrumented or stored. Treat the lab the way you would a shared lab bench in a small research group: useful, finite, and worth respecting.

This guide gets you from zero to your first working call in under fifteen minutes.

---

## What you will need

- A Mac, Linux, or Windows laptop you can install software on
- The ability to install Tailscale (free personal plan, takes one minute)
- A terminal you are comfortable in, or VS Code with the Remote-SSH extension

You do not need to manage SSH keys. Jay will send you the SSH command and the shared `student` password through a private channel.

---

## Step 1: Accept the Tailscale invite

Jay will email you a link that looks like:

```
https://login.tailscale.com/...
```

1. Click the link.
2. Sign in with the email Jay invited (Google or Microsoft account on that address both work).
3. Approve joining Jay's tailnet.

You are now a member of the network. The lab hosts will show up for you and only for you.

---

## Step 2: Install Tailscale on your laptop

### macOS

```
brew install --cask tailscale
```

Then launch Tailscale from Applications and sign in with the same email.

### Linux

Per-distro instructions: https://tailscale.com/download/linux. Then `sudo tailscale up` and sign in with the same email.

### Windows

Download the installer: https://tailscale.com/download/windows. Sign in with the same email.

### Verify

In a terminal:

```
tailscale status
```

You should see the lab hosts (`georges-macbook-pro`, `sophies-macbook-pro`) in the list. If not, see Troubleshooting.

---

## Step 3: SSH to the lab

```
ssh student@georges-macbook-pro
```

Type the shared `student` password Jay sent you privately. You are now in `student@georges-macbook-pro ~ %` — a shared lab account.

The same pattern works for M5 Pro:

```
ssh student@sophies-macbook-pro
```

If the hostname does not resolve, Tailscale's MagicDNS may be off. Use the host's tailnet IP from the Tailscale menu instead, e.g. `ssh student@100.83.184.88`.

---

## Step 4: Make a call

You are in `student`'s shell on the host. Ollama is on the PATH:

```
ollama list
ollama run gemma4:e4b "summarize the Treaty of Westphalia in 3 bullets"
```

For longer prompts, pipe stdin from your laptop:

```
cat my-prompt.txt | ssh student@georges-macbook-pro 'ollama run qwen3.6:35b-a3b-coding-nvfp4'
```

For programmatic API access (the Ollama HTTP API on port 11434), open a port-forward in another terminal:

```
ssh -L 11434:localhost:11434 student@georges-macbook-pro
```

Now anything on your laptop pointed at `http://localhost:11434` is talking to that host's Ollama daemon — the Ollama Python/JS SDKs, the OpenAI SDK with `base_url` overridden, Continue in VS Code, and so on.

---

## Step 5: Wire it into Claude Code

If you use Claude Code (the Anthropic CLI) or a similar AI orchestrator, Jay's recommended pattern is **orchestrator plus muscle**: Claude on your laptop is the orchestrator (planning, code review, careful reasoning), and the lab is the muscle (bulk classification, structured extraction, embeddings, code drafts, vision). You delegate the muscle work to a local model over SSH.

Drop the template into your project as `CLAUDE.md`: [claude-md-template.md](https://github.com/counselorjay/student-lab/blob/main/docs/claude-md-template.md). It encodes the pattern with four to five working SSH+ollama recipes you can copy.

---

## Bonus path: VS Code Remote-SSH

If you prefer working in an IDE on the host directly:

1. Install the Remote-SSH extension in VS Code.
2. Command palette → "Remote-SSH: Connect to Host" → enter `student@georges-macbook-pro` (or `student@sophies-macbook-pro`).
3. Type the shared password when prompted. VS Code opens a remote workspace running on the host.

Claude Code's VS Code extension can target either your local workspace or the remote workspace, depending on which window is in focus. This is clean for exploratory work without bouncing between terminals.

---

## Available models

M5 Max (`georges-macbook-pro`) hosts the heavy fleet; M5 Pro (`sophies-macbook-pro`) hosts the lighter MoE workhorses + embeddings.

| Model | Hosts | Use it for |
|---|---|---|
| `qwen3.5:35b-a3b-nvfp4` | m5-pro | **General-purpose default.** Fast MoE (35B total, 3B active). Reach for this first. Thinking model: read both `content` and `thinking` fields. |
| `qwen3.5:35b-a3b-coding-nvfp4` | m5-pro | Coding-tuned variant of the default. |
| `qwen3.5:27b-q8_0` | m5-pro | High-precision structured extraction. Specialist, slower. |
| `qwen3.6:27b-coding-mxfp8` | m5-max | Dense coder. Strong at JSON / structured extraction. |
| `qwen3.6:35b-a3b-coding-nvfp4` | m5-max | Fast MoE coder for agentic loops on heavy hardware. |
| `qwen2.5:72b-instruct-q4_K_M` | m5-max | Heavy dense reasoning. Use for second-opinion cross-checks. |
| `llama3.3:70b-instruct-q4_K_M` | m5-max | Different 70B family from qwen — use when you want a diverse cross-check. |
| `gemma4:31b` | m5-max, m5-pro | **Vision** (image input) and tricky reasoning. Slower, very capable. Thinking model. |
| `gemma4:26b` | m5-max, m5-pro | Bulk processing, multilingual, vision fallback. 256K context. Thinking model. |
| `gemma4:e4b` | m5-pro | **Fast triage and classification.** Use when you have thousands of small jobs. Thinking model. |
| `nomic-embed-text` | m5-max, m5-pro | **English embeddings.** Call via `/api/embed`. |
| `bge-m3` | m5-max | **Multilingual embeddings.** |

**Reserved (please do not call):** `qwen3.6:35b`, `qwen3.6:latest`, and `qwen3.6:35b-a3b-nvfp4` are running scheduled batch jobs — PsychRX news aggregation (daily ~7 AM cron), DentalSchool Fit synthesis runs, LSTS Vietnamese translation, and a weekly smoke-cessation digest. There's no technical block; the daemon serves any tag you ask for. But calling one of these can evict the warmed copy from VRAM, which costs the next cron 20-40 seconds of cold-load when it fires. Every use case has a non-reserved substitute in the table — pick one of those.

To see what is loaded on a host right now:

```
ssh student@georges-macbook-pro 'ollama list'
ssh student@georges-macbook-pro 'ollama ps'
```

Note on thinking models: every model in the table except `nomic-embed-text` and `bge-m3` emits a separate `thinking` field in addition to the main response. If you call the API directly, read both `message.content` and `message.thinking`. Set `"think": false` in the request body to suppress reasoning and get clean output in `response`.

---

## Etiquette

There are no enforced quotas. The trust model is simple: Jay knows you. In return:

- **No training loops.** Do not point a fine-tuning script or a synthetic-data generator at the lab.
- **No tight-loop firehoses.** If you need thousands of requests, pace them and ping Jay before starting a heavy batch.
- **Check the host before launching big jobs.** M5 Max is shared with M5 Pro and Jay's own work. Before a long batch, SSH in and run `htop`. If something heavy is already running, give it room or ping Jay.
- **Be considerate.** The lab is finite. Most days it will feel infinite, but on the days it does not, considerate people get more of it.

---

## What the lab is good at

**Strong fits:**

- Bulk classification (label thousands of items by sentiment, category, etc.)
- Structured extraction (parse PDFs, transcripts, forms into JSON)
- Embeddings for semantic search and deduplication
- Drafts, summaries, rewrites
- Code stubs, test scaffolding, refactor suggestions
- Vision (image description, document parsing) using `gemma4:31b` or `gemma4:26b`

**Weaker fits (use cloud Claude instead):**

- Novel deep reasoning that needs careful chain-of-thought
- High-stakes creative writing where nuance matters
- Anything that needs a fact newer than the model's training cutoff (the lab has no web access)

The orchestrator-plus-muscle pattern in `claude-md-template.md` is built around this split.

---

## Troubleshooting

| Symptom | What it means | What to do |
|---|---|---|
| `tailscale status` does not show the host | You are not on the tailnet, or signed in with the wrong account. | Re-launch Tailscale; confirm the email matches Jay's invite. If still missing, email Jay. |
| `Permission denied` on SSH | Wrong password, or your tailnet identity is not yet approved. | Double-check the password Jay sent. If it is right, email Jay. |
| SSH hangs even though Tailscale shows the host | A VPN on your machine (Cloudflare WARP, NordVPN, ExpressVPN, etc.) is intercepting Tailscale's routing. The connection times out silently. | Turn the VPN off and try again. (Real example: Zach hit this on his first attempt.) |
| `ollama: command not found` after SSH-ing in | Shell PATH issue on the host. | Run `export PATH=/opt/homebrew/bin:/usr/local/bin:$PATH` and try again. If still broken, report to Jay. |
| Slow responses | Someone else is on the host, or the model is loading into memory. | `htop` on the host to confirm, or be patient for thirty seconds. |
| `ollama run` hangs on first call | Model is being pulled or loaded. | Wait. First call to a fresh model is slow; subsequent calls are fast. |
| "I broke something." | Something is genuinely off. | Email Jay. Do not retry the same call in a tight loop. |

---

## Privacy and trust

Plain-English version of what Jay can and cannot see.

**Jay sees:**

- Tailscale connection events: which of your devices connected, when, and to which host
- Shell history on the shared `student` account on M5 Max and M5 Pro
- Process listings if he runs `htop` or `ps` while you are working
- Logs that Ollama itself writes (model loaded, request received), which do not include your prompt text by default

**Jay does not instrument:**

- Per-request prompt logging
- Per-request response logging
- A gateway in the request path

There is no per-request audit trail. There is also no isolation between students on the host: you all share the `student` user. In practice that means another student could theoretically see your shell history or files left under `/Users/student/`. Treat the host as a shared lab bench, not a private workspace.

The operating principle: **do not put anything in a prompt or in a file under `/Users/student/` that you would be unhappy seeing on someone else's terminal.** No medical record numbers, no someone-else's-passwords, no private journal entries. Same hygiene you would use with any third-party API. If you want isolation from other students, work out of `/tmp/<your-name>/`.

If you want your access removed, ask Jay. He revokes you from the tailnet and the door closes.

---

## Need help?

Email Jay at `jay@counselorjay.com`:

- Tailnet invite issues
- Capacity asks (heavy job, want a green light)
- Bug reports (include the command and the exact error)
- Ideas for what to build with the lab (he loves these)

Welcome aboard. Build something interesting.
