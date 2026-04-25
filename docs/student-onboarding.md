# Welcome to the Lab

Jay is sharing his home AI servers with you. You get authenticated access to a small fleet of local large language models (LLMs) running on Apple Silicon hardware in his office, reachable from anywhere through `lab.counselorjay.com`. The lab logs metadata about every request (who you are, when you called, which model, how long it took, how many tokens) so Jay can keep the lights on and spot abuse. Your prompts and the model's responses are not stored. Treat the lab the way you would a shared lab bench: useful, finite, and worth respecting.

This guide gets you from zero to your first working call in about ten minutes.

---

## Step 1: Accept the email invite

Jay will send a Cloudflare Access invite to the email address he has on file for you.

1. Open the email.
2. Click the magic link.
3. You will land on a Cloudflare login page that emails you a one-time PIN. Paste it.

That is it for auth on the dashboard side. You do not need to install Cloudflare anything.

---

## Step 2: Get your API key

Visit:

```
https://lab.counselorjay.com/dashboard/
```

Cloudflare Access will email you a magic link if your session has expired. Once you are in, you will see your dashboard with a section called "My API keys."

1. Find your key (or click "Mint new key" if your account is set up for self-serve).
2. Copy it. It starts with `slk_` followed by 32 hex characters.
3. Save it somewhere safe (a password manager is ideal).

**Treat this key like a password.** Anyone with it can spend your daily quota and the requests will be attributed to you. If it leaks, come back to the dashboard and revoke it.

---

## Step 3: Install the CLI

The `ewok-lab` CLI is a small Python package. You need Python 3.10 or newer.

```bash
pip install git+https://github.com/Counselor-Sophie/student-lab.git#subdirectory=cli
```

Verify the install:

```bash
ewok-lab --help
```

---

## Step 4: Login

Run:

```bash
ewok-lab login
```

Paste your API key when prompted. The CLI saves it to `~/.ewok-lab/config.toml` with restrictive file permissions. You only need to do this once per machine.

To confirm everything is wired up:

```bash
ewok-lab status
```

You should see a list of backends (M5 Max, M5 Pro) with online dots and your remaining daily quota.

---

## Step 5: Start using it

There are two ways to use the lab. Pick the one that matches what you are trying to do.

### Quick path: one-off chats

For interactive chat:

```bash
ewok-lab chat qwen3.5:35b-a3b-nvfp4
```

For piping a prompt in (great for scripts and one-shot tasks):

```bash
echo "Summarize the Treaty of Westphalia in 3 bullets." | ewok-lab chat qwen3.5:35b-a3b-nvfp4
```

You can swap in any model from the table below.

### Power path: run a local proxy

This is the killer feature. The CLI can stand up a localhost server that speaks the Ollama API:

```bash
ewok-lab serve
```

Leave it running in a terminal. Now any tool that knows how to talk to Ollama can talk to the lab by pointing at:

```
http://localhost:11435
```

That includes:
- Continue (the VS Code extension)
- Claude Code via custom commands
- The OpenAI Python SDK with `base_url` overridden
- Anything else that speaks the Ollama or OpenAI-compatible API

The CLI handles the auth and TLS to the gateway transparently. From your tool's perspective, it is just a local Ollama install.

---

## Step 6: Wire it into Claude Code

If you use Claude Code (the Anthropic CLI), there is a recommended pattern: **Claude Code on your laptop is the orchestrator, the lab is the muscle.** Claude Code does the planning, code editing, and tool use. The lab handles bulk LLM jobs (classify 500 PDFs, summarize a transcript, generate embeddings) where you do not need cloud-grade reasoning.

Felix (Jay's local AI architect) maintains a CLAUDE.md template that encodes this pattern with sample bash recipes. Drop it into your project as `CLAUDE.md` (or append it to an existing one):

```
https://github.com/Counselor-Sophie/student-lab/blob/main/docs/claude-md-template.md
```

Read it before starting your first project.

---

## Available models

These are the models you can call. Use the model name in the `model` field of any API call or as the argument to `ewok-lab chat`.

| Model | Use it for |
|---|---|
| `qwen3.5:35b-a3b-nvfp4` | **General-purpose default.** Fast, capable, what you should reach for first. |
| `gemma4:31b` | **Vision** (image input) and complex reasoning. Slower, but smart. |
| `gemma4:e4b` | Fast triage and classification. Use when you have thousands of small jobs. |
| `qwen3.5:35b-a3b-coding-nvfp4` | Coding-tuned variant of the default. |
| `gemma4:26b` | Bulk processing, multilingual, vision fallback. 256K context. |
| `qwen3.5:27b-q8_0` | High-precision structured extraction (specialist model, slower). |
| `nomic-embed-text` | **Embeddings** for semantic search and RAG. Call via `/api/embed`. |

**Reserved (do not use):** `qwen3.6:35b` is locked for Jay's research. The gateway will return 403 if you try to call it.

To see the live list and check what is loaded right now:

```bash
ewok-lab models
```

Note: `qwen3.5:35b-a3b-nvfp4`, `gemma4:31b`, and `qwen3.5:27b-q8_0` are all "thinking" models. They produce a `thinking` field in addition to the main response. The CLI handles this for you. If you call the API directly, read both `message.content` and `message.thinking`.

---

## Quotas and etiquette

**Default limits (per day, per user):**
- 200 requests
- 500,000 tokens

You can see your current usage on the dashboard. If you legitimately need more for a project, ask Jay. He will bump your limits.

**House rules:**
- No training loops. Do not point a fine-tuning script or a synthetic-data generator at the lab.
- No scraping pipelines firing thousands of requests in a tight loop. If you need bulk work, talk to Jay first about how to pace it.
- The lab is shared with other students and with Jay's own work. Be considerate. If a job can wait, let it wait.
- The gateway routes around busy backends automatically. If things feel slow, the dashboard's status grid shows you why (which boxes are saturated, which models are loaded, who is in queue).

---

## What the lab is good at

**Strong fits:**
- Bulk classification (label 1,000 emails by sentiment)
- Structured extraction (parse PDFs, transcripts, forms into JSON)
- Embeddings for semantic search and deduplication
- Drafts, summaries, and rewrites
- Code stubs, test scaffolding, refactor suggestions
- Vision tasks (image description, document parsing) using `gemma4:31b` or `gemma4:e4b`

**Weaker fits (use cloud Claude instead):**
- Novel deep reasoning that needs careful chain-of-thought
- High-stakes creative writing where nuance matters
- Anything where you need a fact that is newer than the model's training cutoff (the lab has no web access)

The orchestrator-plus-muscle pattern in `claude-md-template.md` is built around this split.

---

## Troubleshooting

| Symptom | What it means | What to do |
|---|---|---|
| `401 Unauthorized` | Your API key is wrong, expired, or revoked. | Re-run `ewok-lab login` and paste your key again. If that fails, check the dashboard. |
| `403 Forbidden` | Either your email is not on the allowlist, or you tried to call `qwen3.6:35b` (reserved). | Pick a different model. If the issue is allowlist, email Jay. |
| `429 Too Many Requests` | You hit your daily limit. | Wait until the daily window resets, or ask Jay to bump your quota. |
| `502 Bad Gateway` / `503 Service Unavailable` | All backends are busy or one of them crashed. | Check the dashboard's backend status grid. Retry in a minute. |
| Responses feel slow | A backend is queued or M5 Max is loading a fresh model. | Check the dashboard. The grid shows queue depth per backend. |
| "I broke something." | Something is genuinely off. | Email Jay. Do not retry the same call in a tight loop. |

---

## Privacy and trust

Plain English version of what Jay can and cannot see.

**Jay sees:**
- Your email (he added you, so this is not news)
- A timestamp for each request
- Which model you called and which backend served it
- How long the request took
- How many tokens went in and came out
- The HTTP status code (did it succeed, error, get rate-limited)

**Jay does not store:**
- Your prompts
- The model's responses
- Anything resembling the actual content of your conversations

The request log row tracks metadata only. No body is persisted. That said, the request necessarily passes through the gateway in plaintext on its way to Ollama, so the operating principle is: **do not put anything in a prompt that you would be unhappy seeing transiently on Jay's hardware.** No medical record numbers, no someone-else's-passwords, no private journal entries. Same hygiene you would use with any third-party API.

If you ever want your account fully removed, ask Jay. He will revoke the key and delete the user row.

---

## Need help?

For anything beyond this doc, email Jay at `jay@counselorjay.com`:
- API key issues, quota requests, allowlist problems
- Bug reports about the CLI or gateway (include the command you ran and the error)
- Ideas for what to build with the lab (he loves these)

Welcome aboard. Build something interesting.
