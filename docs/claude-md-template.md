# CLAUDE.md (Student Lab template)

Drop this file at the root of your Claude Code project. Edit anything in **angle brackets** to match your project. Everything else is a starting point you can keep, trim, or expand.

---

## What this project is

<One paragraph: what you're building, who it's for, what "done" looks like.>

## How I work with Claude Code

I treat Claude Code as my **orchestrator**, not my only worker. The orchestrator plans, reviews, and writes the prose I care about. For bulk or structured work, the orchestrator delegates to **the lab** (Jay's local LLM cluster on `m5-max` and `m5-pro`), which runs open models on Apple Silicon. Two roles, two different strengths.

- **Cloud Claude (this session) is the orchestrator.** Think hard, write well, review carefully, ask good questions.
- **The lab is the muscle.** Cheap, fast, runs locally, never trains on my data, has plenty of headroom for repetitive jobs.

When in doubt, I keep reasoning and prose in cloud, push everything else to the lab.

## When to use cloud Claude vs the lab

| Use cloud Claude when... | Use the lab when... |
|---|---|
| The task needs deep, novel reasoning across an unfamiliar domain | The task is bulk classification, tagging, or extraction over many items |
| The output needs voice or nuance (essays, emails, design rationale) | I need structured output (JSON) from messy input (PDFs, transcripts, forms) |
| I'm making code architecture decisions or chasing a hairy bug | I want a first-draft function body, test scaffold, or regex |
| I'd be embarrassed to read the result aloud if it came out wrong | I want embeddings for semantic search or deduplication |
| One careful answer is worth more than ten cheap ones | I'd run this 100 times if it were free, and on the lab it basically is |

A useful test: if I'd hesitate to run something 100 times on cloud Claude because of cost, run it on the lab instead.

## How the lab is reachable

Jay added me to his Tailscale tailnet. That's the only network path to the hosts. There's no public URL, no API key, no gateway. I SSH in as the shared `student` user with the shared password Jay sent me on Discord.

Two hosts (canonical Tailscale hostnames):

- **`georges-macbook-pro`** (M5 Max, 128 GB). Carries everything in the student-facing fleet plus M5 Max-only heavy models (qwen3.6 coders, qwen2.5:72b, llama3.3:70b, bge-m3).
- **`sophies-macbook-pro`** (M5 Pro, 48 GB). Carries the same student-facing models, lighter and a good fallback when M5 Max is busy.

Most models live on both hosts so I can route around contention — same `ollama run <model> "..."` call works against either alias. M5 Max is the better default for the heaviest jobs; M5 Pro is the better default when I just want the call to land fast and someone else has M5 Max warm.

I keep an alias in my SSH config so the recipes are short:

```
# ~/.ssh/config
Host m5-max
    HostName georges-macbook-pro
    User student

Host m5-pro
    HostName sophies-macbook-pro
    User student
```

Auth is **classic SSH with the shared password Jay DM'd me**. The first connection asks me to accept the host key fingerprint; type `yes` once and it's saved to `~/.ssh/known_hosts`. From then on it just prompts for the password. I can cache the password in macOS Keychain via `ssh-copy-id` if I want, but the simple flow works fine.

## Two ways to drive the lab from Claude Code

### Way 1: standalone SSH (what the recipes below assume)

I run `ssh m5-max '...'` from my laptop. Works in any terminal. Works inside Claude Code's Bash tool. This is the default.

### Way 2: VS Code Remote-SSH

If I open VS Code's Remote-SSH extension and connect to `m5-max`, my whole workspace lives on the Mac. Files I edit are on M5 Max, terminals open on M5 Max, and `ollama` is just `ollama` (no SSH wrapper). Claude Code running inside that Remote-SSH window treats the Mac as localhost.

Use Remote-SSH when I'm doing a lot of file manipulation on the Mac (parsing a folder of PDFs that already lives there, building an index in place). Use standalone SSH when files live on my laptop and I just need a model call.

## Recipes

Concrete bash patterns I lean on. Pick the host that has the model — `qwen3.5:35b-a3b-nvfp4` (general default) lives on `m5-pro`; the heavy qwen3.6 / qwen2.5 / llama3.3 fleet lives on `m5-max`. `gemma4:31b` and `gemma4:26b` are on both. See the model table below for full hosting.

### Recipe 1: one-shot inference

The simplest call: pipe a prompt over SSH, get a response back.

```bash
# Quick sanity check (general default lives on m5-pro)
echo "Summarize the Treaty of Westphalia in 3 bullets." \
  | ssh m5-pro 'ollama run qwen3.5:35b-a3b-nvfp4'

# With a system prompt and a real input file
cat input.txt | ssh m5-pro 'ollama run qwen3.5:35b-a3b-nvfp4 \
  "You are a careful editor. Tighten the prose. Output only the rewrite."'

# Heavier reasoning / cross-check on m5-max
cat input.txt | ssh m5-max 'ollama run qwen2.5:72b-instruct-q4_K_M \
  "Give me a careful second opinion on the argument in this draft."'
```

The remote `ollama run` reads stdin until EOF, then prints the response on stdout. The pipe across SSH is transparent.

When to escalate to cloud Claude: if the output is technically right but flat, or if I want a different voice. Cloud Claude is better at "make this sound like a real person."

### Recipe 2: bulk classification over a CSV

Loop locally, call the model remotely. One row at a time keeps memory tame and lets me checkpoint mid-run.

```bash
# items.csv has one item per line, header "text"
# Goal: add a "category" column with a label from a fixed taxonomy.

tail -n +2 items.csv | while IFS= read -r line; do
  category=$(printf '%s' "$line" \
    | ssh m5-pro 'ollama run gemma4:e4b \
        "Classify into one of: news, opinion, research, ad. Output only the label, nothing else."')
  printf '%s,%s\n' "$line" "$category"
done > items_classified.csv
```

For larger batches I'd switch to a small Python script that opens one SSH session and streams many prompts through it (avoids per-call SSH handshake overhead). For a few hundred rows this loop is fine.

When to escalate: if I see misclassifications in the obvious cases, I show 5 examples to cloud Claude and ask it to rewrite the system prompt. Then I rerun the cheap loop.

### Recipe 3: structured extraction from PDFs

`gemma4` and `qwen3.5` both support `format json` mode in Ollama, which constrains output to valid JSON. Combine that with `pdftotext` and I get a folder of structured records from a folder of papers.

```bash
# Goal: pull {title, author, year, abstract} out of a folder of academic PDFs.
# Run from my laptop. PDFs live in ./papers/.

mkdir -p extracted/

for pdf in papers/*.pdf; do
  name=$(basename "$pdf" .pdf)
  text=$(pdftotext "$pdf" -)

  printf '%s' "$text" | ssh m5-max \
    'ollama run --format json qwen3.6:27b-coding-mxfp8 \
      "Extract title, author, year, abstract as JSON. Use null for missing fields. Output only JSON."' \
    > "extracted/${name}.json"
done
```

Two things to know:
- `--format json` is an Ollama flag that turns on JSON-mode decoding. The model will refuse to emit anything outside a valid JSON object. `qwen3.6:27b-coding-mxfp8` is the dense coder on m5-max and is the best at structured JSON output. Set `"think": false` in the request body if calling via the API to suppress the thinking field; `qwen3.5:35b-a3b-nvfp4` on m5-pro also handles JSON well if you want the lighter MoE.
- For 100+ PDFs, copy the folder to the Mac first (`rsync -av papers/ m5-max:~/papers/`) and run the loop over SSH so the data isn't crossing the wire per-file.

When to escalate: I have cloud Claude review 3 sample JSONs against the source PDFs to catch systematic extraction bugs before I trust the rest.

### Recipe 4: embeddings via local port-forward

Ollama exposes embeddings at `/api/embed`. The cleanest way to use it from a local Python script is to forward port 11434 over SSH. From my script's perspective, Ollama is running on localhost.

```bash
# In one terminal, leave running:
ssh -L 11434:localhost:11434 m5-max

# In another terminal:
curl http://localhost:11434/api/embed \
  -d '{"model":"nomic-embed-text","input":"hello world"}'
```

Or in Python:

```python
import requests

resp = requests.post(
    "http://localhost:11434/api/embed",
    json={"model": "nomic-embed-text", "input": ["text one", "text two"]},
)
vectors = resp.json()["embeddings"]  # list of 768-dim float lists
```

Most embedding-aware tools (LlamaIndex, LangChain, custom RAG scripts) accept an Ollama base URL as a config option. Point them at `http://localhost:11434` and they'll work as if Ollama is local.

`nomic-embed-text` produces 768-dim vectors with an 8K context window. Plenty for paragraph-level chunks.

If port 11434 is already in use on my laptop (because I have local Ollama installed too), forward to a different local port:

```bash
ssh -L 11500:localhost:11434 m5-max
# then point my script at http://localhost:11500
```

## Models I reach for

| Model | Hosts | Use it for |
|-------|-------|------------|
| `qwen3.5:35b-a3b-nvfp4` | m5-max, m5-pro | General default. Prose, code drafts, structured extraction. Fast (MoE). |
| `qwen3.5:35b-a3b-coding-nvfp4` | m5-max, m5-pro | Coding-tuned variant of the default. |
| `qwen3.5:27b-q8_0` | m5-max, m5-pro | High-precision dense Q8 for structured extraction. Specialist, slower. |
| `qwen3.6:27b-coding-mxfp8` | m5-max | Dense coder. Strong at JSON / structured output. |
| `qwen3.6:35b-a3b-coding-nvfp4` | m5-max | Fast MoE coder for agentic loops on heavy hardware. |
| `qwen2.5:72b-instruct-q4_K_M` | m5-max | Heavy dense reasoning. Use for second-opinion cross-checks. |
| `llama3.3:70b-instruct-q4_K_M` | m5-max | Different 70B family from qwen — diverse cross-check when qwen output looks suspicious. |
| `gemma4:31b` | m5-max, m5-pro | Vision (image input) and the trickiest reasoning. Slower, denser. |
| `gemma4:26b` | m5-max, m5-pro | Bulk processing, multilingual, long context (256K). |
| `gemma4:e4b` | m5-max, m5-pro | Fast triage, classification at scale, anything where latency matters more than depth. |
| `nomic-embed-text` | m5-max, m5-pro | English embeddings. 768-dim, 8K context. Use via `/api/embed`. |
| `bge-m3` | m5-max | Multilingual embeddings. |

Most student-facing models live on both hosts — if `m5-max` is busy I switch the same call to `m5-pro` (or the reverse) without changing the model name. `qwen3.5:35b-a3b-nvfp4` is the right answer 80% of the time; reach for the M5 Max-only heavy fleet (`qwen2.5:72b`, `llama3.3:70b`, `qwen3.6:27b-coding-mxfp8`, `qwen3.6:35b-a3b-coding-nvfp4`) when the task wants more horsepower or a non-qwen voice for cross-checking.

**MLX-accelerated gemma4 (faster on Apple Silicon):** for every gemma4 size, there's an `-nvfp4` MLX-format companion tag — same weights, same disk cost, but routed through Apple's MLX framework. Use these for new code:

```bash
# Faster (MLX) on Apple Silicon
ssh m5-max 'ollama run gemma4:31b-nvfp4 "..."'
ssh m5-pro 'ollama run gemma4:e4b-nvfp4 "..."'
```

The plain `gemma4:31b` / `gemma4:26b` / `gemma4:e4b` tags stay available for compatibility, but the `-nvfp4` variants give better TTFT and tokens/sec. The qwen3.5 family is already MLX-routed via its canonical `-nvfp4` quantization — no separate variant to chase. The 70B+ heavy models (qwen2.5:72b, llama3.3:70b) and qwen3.6:27b-coding-mxfp8 are GGUF-only on the public Ollama hub for now.

A note on thinking models: every model in the table except the embedders emits a `thinking` field alongside the main response. When I use `ollama run` interactively, that's already handled. When I call the API directly, I either set `"think": false` in the request body (cleanest) or read both `message.content` and `message.thinking`.

## Heads-up: scheduled cron jobs

Jay runs two scheduled jobs against the lab. They use qwen3.6 family tags:

- `qwen3.6:35b` and its alias `qwen3.6:latest` — same weights.
- `qwen3.6:35b-a3b-nvfp4`.

Schedule:

- **PsychRX news aggregation** — daily, around 7 AM PT.
- **Weekly smoking-cessation digest** — once a week.

Nothing's reserved; I can call any of these tags. The only thing to know is that if a cron fires while my call is in flight, my call and the cron share the daemon's parallel slot (queues briefly); and if I've loaded other large models recently and evicted these from VRAM, the cron pays a 20-40 second cold-load on first run. Neither is a failure mode — just FYI so I can avoid the cron windows if I'm running something latency-sensitive.

## Etiquette

There's no queue gate, no rate limit, no quota. Just shared hardware. So:

- Before kicking off a heavy job (anything that'll run more than 10 minutes, or fire more than a few hundred requests), SSH in and check `htop` or `ps aux | grep ollama` to see what else is running. If a teammate or Jay is mid-job, wait or use the other host.
- A quick `tailscale ping m5-max` confirms the host is reachable before I assume something's broken.
- No training loops, no fine-tuning runs, no sustained scrapers feeding the model in a tight loop. The lab is for inference.
- If I'm not sure whether my job is too much, ask Jay first. He'd much rather say "go ahead" than discover at midnight that someone pinned the GPU.
- I treat anything I send to the lab the way I'd treat anything I send to a third-party API. No medical record numbers, no someone-else's-passwords, no private journal entries.

## When something goes wrong

- **`ssh m5-max` fails.** First check `tailscale status`. Am I connected to the tailnet? If yes, try the full hostname (`georges-macbook-pro` for m5-max, `sophies-macbook-pro` for m5-pro) instead of the alias. If `Permission denied`, double-check the password Jay sent — capitalization and exclamation matter.
- **SSH hangs even with Tailscale connected.** A VPN on my laptop (Cloudflare WARP, NordVPN, ExpressVPN, etc.) is intercepting Tailscale's routing. Turn the VPN off and try again.
- **`ollama run` says "model not found".** The host may not have the tag I asked for — `qwen3.5` family is m5-pro only, `qwen3.6` heavy / `qwen2.5:72b` / `llama3.3:70b` / `bge-m3` are m5-max only. Check `ollama list` on the host I'm hitting.
- **A call hangs.** The model may be loading from disk (first call after idle), or another job is holding the GPU. Check `ssh m5-max 'ps aux | grep ollama'` and give it a minute.
- **Port 11434 in use locally.** Forward to a different port (see Recipe 4).

## House rules

- I escalate to cloud Claude when the lab's output feels off, not when I'm bored.
- I keep `CLAUDE.md` updated as my project evolves so future me, and Claude Code, can pick up where I left off.
- I assume every other student on the tailnet is also a real person doing real work. Be a good neighbor.
