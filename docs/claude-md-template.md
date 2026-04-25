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

Jay added me to his Tailscale tailnet. That's the only network path to the hosts. There's no public URL, no API key, no gateway. I SSH in as the shared `student` user and use `ollama` natively, the same way I'd use it on my own machine.

Two hosts:

- **`m5-max`** (primary). M5 Max, 128GB. Default destination for everything.
- **`m5-pro`** (secondary). M5 Pro, 48GB. Use when M5 Max is busy, or when I'm pulling embeddings while a teammate has a long job on M5 Max.

Tailscale gives the hosts longer machine names by default (something like `georges-macbook-pro` and `sophies-mbp`). The recipes below assume I've aliased them to `m5-max` and `m5-pro` in my SSH config:

```
# ~/.ssh/config
Host m5-max
    HostName georges-macbook-pro
    User student

Host m5-pro
    HostName sophies-mbp
    User student
```

(Replace the `HostName` values with whatever `tailscale status` shows on my machine. Tailscale MagicDNS resolves them automatically.)

Auth is handled by **Tailscale SSH**. No SSH keys to manage, no passwords. If `ssh m5-max` works, I'm in.

## Two ways to drive the lab from Claude Code

### Way 1: standalone SSH (what the recipes below assume)

I run `ssh m5-max '...'` from my laptop. Works in any terminal. Works inside Claude Code's Bash tool. This is the default.

### Way 2: VS Code Remote-SSH

If I open VS Code's Remote-SSH extension and connect to `m5-max`, my whole workspace lives on the Mac. Files I edit are on M5 Max, terminals open on M5 Max, and `ollama` is just `ollama` (no SSH wrapper). Claude Code running inside that Remote-SSH window treats the Mac as localhost.

Use Remote-SSH when I'm doing a lot of file manipulation on the Mac (parsing a folder of PDFs that already lives there, building an index in place). Use standalone SSH when files live on my laptop and I just need a model call.

## Recipes

Concrete bash patterns I lean on. Adjust models per task. `qwen3.5:35b-a3b-nvfp4` is the safe default for prose and code. `gemma4:31b` is stronger for vision and gnarly reasoning. `gemma4:e4b` is the fast triage option. `nomic-embed-text` is for embeddings.

### Recipe 1: one-shot inference

The simplest call: pipe a prompt over SSH, get a response back.

```bash
# Quick sanity check
echo "Summarize the Treaty of Westphalia in 3 bullets." \
  | ssh m5-max 'ollama run qwen3.5:35b-a3b-nvfp4'

# With a system prompt and a real input file
cat input.txt | ssh m5-max 'ollama run qwen3.5:35b-a3b-nvfp4 \
  "You are a careful editor. Tighten the prose. Output only the rewrite."'
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
    | ssh m5-max 'ollama run gemma4:e4b \
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
    'ollama run --format json qwen3.5:35b-a3b-nvfp4 \
      "Extract title, author, year, abstract as JSON. Use null for missing fields. Output only JSON."' \
    > "extracted/${name}.json"
done
```

Two things to know:
- `--format json` is an Ollama flag that turns on JSON-mode decoding. The model will refuse to emit anything outside a valid JSON object.
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

| Model | Use it for |
|-------|------------|
| `qwen3.5:35b-a3b-nvfp4` | General default. Prose, code drafts, structured extraction. Fast (MoE). |
| `qwen3.5:35b-a3b-coding-nvfp4` | Coding-tuned variant. Reach for when the task is mostly code. |
| `gemma4:31b` | Vision tasks, the trickiest reasoning, code I want to be sure about. Slower, denser. |
| `gemma4:26b` | Bulk processing, multilingual content, long context (256K). |
| `gemma4:e4b` | Fast triage, classification at scale, anything where latency matters more than depth. |
| `nomic-embed-text` | Embeddings only. Use via `/api/embed` or any Ollama-compatible client. |

`qwen3.5:35b-a3b-nvfp4` is the right answer 80% of the time. Reach for the others when I have a specific reason.

A note on thinking models: `qwen3.5:35b-a3b-nvfp4`, `gemma4:31b`, `gemma4:26b`, and `gemma4:e4b` all emit a `thinking` field alongside the main response. When I use `ollama run` interactively, that's already handled. When I call the API directly (via the port-forward), I read both `message.content` and `message.thinking` if I want the full picture; usually `message.content` is enough.

**Reserved:** `qwen3.6:35b` is for Jay's psychrx research. It will appear in `ollama list`. Please don't call it. There's no enforcement layer here, just trust.

## Etiquette

There's no queue gate, no rate limit, no quota. Just shared hardware. So:

- Before kicking off a heavy job (anything that'll run more than 10 minutes, or fire more than a few hundred requests), SSH in and check `htop` or `ps aux | grep ollama` to see what else is running. If a teammate or Jay is mid-job, wait or use the other host.
- A quick `tailscale ping m5-max` confirms the host is reachable before I assume something's broken.
- No training loops, no fine-tuning runs, no sustained scrapers feeding the model in a tight loop. The lab is for inference.
- If I'm not sure whether my job is too much, ask Jay first. He'd much rather say "go ahead" than discover at midnight that someone pinned the GPU.
- I treat anything I send to the lab the way I'd treat anything I send to a third-party API. No medical record numbers, no someone-else's-passwords, no private journal entries.

## When something goes wrong

- **`ssh m5-max` fails.** First check `tailscale status`. Am I connected to the tailnet? If yes, try the full Tailscale name (whatever shows in `tailscale status` for that host) instead of the alias.
- **`ollama run` says "model not found".** The host may not have the model pulled yet. Run `ssh m5-max 'ollama list'` to see what's there. Ask Jay to pull it if it's missing.
- **A call hangs.** The model may be loading from disk (first call after idle), or another job is holding the GPU. Check `ssh m5-max 'ps aux | grep ollama'` and give it a minute.
- **Port 11434 in use locally.** Forward to a different port (see Recipe 4).

## House rules

- I escalate to cloud Claude when the lab's output feels off, not when I'm bored.
- I keep `CLAUDE.md` updated as my project evolves so future me, and Claude Code, can pick up where I left off.
- I assume every other student on the tailnet is also a real person doing real work. Be a good neighbor.
