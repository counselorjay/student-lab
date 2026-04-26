# Welcome to the Lab

Jay is sharing his home AI servers with you. They are Apple Silicon Macs in his office, running a small fleet of local large language models, reachable from anywhere through Tailscale. There is no per-request logging in this setup. Jay can see Tailscale connection events (which device of yours connected, when, to which host), but the contents of your prompts, responses, and work are not instrumented or stored. Treat the lab the way you would a shared lab bench in a small research group: useful, finite, and worth respecting.

This guide gets you from zero to your first working call in under fifteen minutes.

---

## What you will need

- A Mac, Linux, or Windows laptop you can install software on
- The ability to install Tailscale (free personal plan, takes one minute)
- A terminal you are comfortable in, or VS Code with the Remote-SSH extension
- A few minutes

You do not need SSH keys. You do not need to manage any credentials beyond the email Jay invites you with.

---

## Step 1: Accept the Tailscale invite

Jay will send you an invite link that looks like:

```
https://login.tailscale.com/...
```

1. Click the link.
2. Sign in with the email Jay invited (a Google or Microsoft account on that address both work).
3. Approve joining Jay's tailnet.

You are now a member of the network. The lab hosts will show up for you and only for you.

---

## Step 2: Install Tailscale on your laptop

### macOS

```
brew install --cask tailscale
```

Then launch the Tailscale app from Applications and sign in with the same email Jay invited.

### Linux

Follow the per-distro instructions at:

```
https://tailscale.com/download/linux
```

Then start it:

```
sudo tailscale up
```

Sign in with the same email Jay invited.

### Windows

Download and run the installer from:

```
https://tailscale.com/download/windows
```

Sign in with the same email Jay invited.

### Verify

In a terminal:

```
tailscale status
```

Or open the Tailscale menu-bar app. You should see `m5-max` and `m5-pro` in the host list. If you do not, see Troubleshooting below.

---

## Step 3: SSH to the lab hosts

Tailscale has SSH built in, so you do not have to generate or share a key. Your Tailscale identity is the credential.

```
tailscale ssh student@m5-max
```

If Jay has set up the standard alias on your laptop's `~/.ssh/config`, you can also use the shorter form:

```
ssh m5-max
```

You will land in the shared `student` user shell on M5 Max. To see the available models:

```
ollama list
```

The same pattern works for M5 Pro:

```
tailscale ssh student@m5-pro
```

---

## Step 4: Make a one-shot call

Most of your real work will run as one-shot SSH commands from your laptop, not interactive sessions. The pattern:

```
ssh student@m5-max 'ollama run qwen3.5:35b-a3b-nvfp4 "summarize the Treaty of Westphalia in 3 bullets"'
```

For longer prompts, pipe stdin:

```
cat my-prompt.txt | ssh student@m5-max 'ollama run qwen3.5:35b-a3b-nvfp4'
```

For programmatic API access (the Ollama HTTP API on port 11434), open a port-forward in another terminal:

```
ssh -L 11434:localhost:11434 student@m5-max
```

Now anything on your laptop pointed at `http://localhost:11434` is talking to M5 Max's Ollama. That includes the Ollama Python and JS SDKs, the OpenAI SDK with `base_url` overridden, Continue in VS Code, and so on.

---

## Step 5: Wire it into Claude Code

If you use Claude Code (the Anthropic CLI), there is a recommended pattern: Claude Code on your laptop is the orchestrator (reasoning, planning, code review), and the lab is the muscle (bulk classification, structured extraction, embeddings, code drafts, vision). You delegate the muscle work to a local model over SSH and let Claude Code do the parts that need careful judgment.

Drop the template into your project as `CLAUDE.md`:

```
docs/claude-md-template.md
```

It encodes the orchestrator-plus-muscle pattern with four to five working SSH+ollama recipes you can copy. Read it before starting your first project.

---

## Bonus path: VS Code Remote-SSH

If you prefer working in an IDE on the host directly:

1. Install the Remote-SSH extension in VS Code.
2. Open the command palette, run "Remote-SSH: Connect to Host", add `m5-max` (or `student@m5-max`).
3. VS Code opens a remote workspace running on M5 Max. From there, the integrated terminal already has Ollama on PATH, and any code you run executes on the host.

Claude Code's VS Code extension can target either your local workspace or the remote workspace, depending on which window is in focus. This is a clean way to do exploratory work without bouncing between terminals.

---

## Available models

The canonical list lives in Felix's fleet doc; here is the working subset for students.

| Model | Use it for |
|---|---|
| `qwen3.5:35b-a3b-nvfp4` | **General-purpose default.** Fast MoE (35B total, 3B active). Reach for this first. Thinking model: read both `content` and `thinking` fields. |
| `qwen3.5:35b-a3b-coding-nvfp4` | Coding-tuned variant of the default. M5 Pro only. |
| `gemma4:31b` | **Vision** (image input) and tricky reasoning. Slower, very capable. Thinking model. |
| `gemma4:26b` | Bulk processing, multilingual, vision fallback. 256K context. Thinking model. |
| `gemma4:e4b` | **Fast triage and classification.** Use when you have thousands of small jobs. Thinking model. |
| `qwen3.5:27b-q8_0` | High-precision structured extraction. Specialist, slower. M5 Pro only. |
| `nomic-embed-text` | **Embeddings.** Call via `/api/embed`. |

**Reserved (please do not call):** `qwen3.6:35b` is locked for Jay's research. The cost to you of accidentally hitting it is zero, but please pick a different model.

To see what is loaded on a host right now:

```
ssh student@m5-max 'ollama list'
ssh student@m5-max 'ollama ps'
```

Note on thinking models: every model in the table above except `nomic-embed-text` emits a separate `thinking` field in addition to the main response. If you call the API directly, read both `message.content` and `message.thinking`. Budget your token limits accordingly (raise `num_predict` if you see truncation).

---

## Etiquette

There are no enforced quotas. Trust model: Jay knows you. In return, please:

- **No training loops.** Do not point a fine-tuning script or a synthetic-data generator at the lab.
- **No tight-loop firehoses.** If you need to run thousands of requests, pace them, and tell Jay before you start a heavy batch job.
- **Check the host before launching big jobs.** M5 Max is shared with M5 Pro and with Jay's own work. Before you start a long batch, SSH in and:

  ```
  htop
  ```

  If something heavy is already running, give it room or ping Jay.

- **Be considerate.** The lab is finite. Most of the time it will feel infinite, but on the days it does not, considerate people get more of it.

---

## What the lab is good at

**Strong fits:**

- Bulk classification (label thousands of items by sentiment, category, etc.)
- Structured extraction (parse PDFs, transcripts, forms into JSON)
- Embeddings for semantic search and deduplication
- Drafts, summaries, rewrites
- Code stubs, test scaffolding, refactor suggestions
- Vision (image description, document parsing) using `gemma4:31b` or `gemma4:e4b`

**Weaker fits (use cloud Claude instead):**

- Novel deep reasoning that needs careful chain-of-thought
- High-stakes creative writing where nuance matters
- Anything that needs a fact newer than the model's training cutoff (the lab has no web access)

The orchestrator-plus-muscle pattern in `claude-md-template.md` is built around this split.

---

## Troubleshooting

| Symptom | What it means | What to do |
|---|---|---|
| `tailscale status` does not show `m5-max` | You are not on the tailnet, or signed in with the wrong account. | Re-launch Tailscale, confirm you are signed in with the email Jay invited. If still missing, email Jay. |
| `Permission denied` on SSH | Your tailnet identity is not yet on the lab ACL. | Email Jay and tell him which email you signed in with. |
| SSH hangs even though Tailscale shows the host | A VPN on your machine (Cloudflare WARP, NordVPN, ExpressVPN, etc.) is intercepting Tailscale's routing. The connection times out silently. | Turn the VPN off and SSH again. (Real example: Zach hit this on first attempt.) |
| `ollama: command not found` after SSH-ing in | Shell PATH issue on the host. | Report to Jay; this is a host config bug, not yours. |
| Slow responses | Someone else is on the host, or M5 Max is loading a fresh model into memory. | `htop` on the host to confirm, or just be patient for thirty seconds. |
| Connection works, but `ollama run` hangs | Model is being pulled or loaded. | Wait. First call to a fresh model is slow; subsequent calls are fast. |
| "I broke something." | Something is genuinely off. | Email Jay. Do not retry the same call in a tight loop. |

---

## Privacy and trust

Plain-English version of what Jay can and cannot see in this v2 setup.

**Jay sees:**

- Tailscale connection events: which of your devices connected, when, and to which host
- Shell history on the shared `student` account on M5 Max and M5 Pro
- Process listings if he runs `htop` or `ps` while you are working
- Logs that Ollama itself writes (model loaded, request received), which do not include your prompt text by default

**Jay does not instrument:**

- Prompt logging
- Response logging
- A gateway in the request path

There is no per-request audit trail in v2. There is also no isolation between students on the host: you all share the `student` user. In practice that means another student could theoretically see your shell history or files left under `/Users/student/`. Treat the host as a shared lab bench, not a private workspace.

The operating principle: **do not put anything in a prompt or in a file under `/Users/student/` that you would be unhappy seeing on someone else's terminal.** No medical record numbers, no someone-else's-passwords, no private journal entries. Same hygiene you would use with any third-party API.

If you want your access removed, ask Jay. He revokes you from the tailnet and the door closes.

---

## Need help?

Email Jay at `jay@counselorjay.com`:

- ACL or invite issues
- Capacity asks (you have a heavy job and want a green light)
- Bug reports (include the command you ran and the error)
- Ideas for what to build with the lab (he loves these)

Welcome aboard. Build something interesting.
