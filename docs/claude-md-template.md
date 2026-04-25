# CLAUDE.md (Student Lab template)

Drop this file at the root of your Claude Code project. Edit anything in **angle brackets** to match your project. Everything else is a starting point you can keep, trim, or expand.

---

## What this project is

<One paragraph: what you're building, who it's for, what "done" looks like.>

## How I work with Claude Code

I treat Claude Code as my **orchestrator**, not my only worker. The orchestrator plans, reviews, and writes the prose I care about. For bulk or structured work, the orchestrator delegates to **the lab gateway** (Jay's local LLM cluster on `lab.counselorjay.com`), which runs open models on Apple Silicon. Two roles, two different strengths.

- **Cloud Claude (this session) is the orchestrator.** Think hard, write well, review carefully, ask good questions.
- **The lab is the muscle.** Cheap, fast, runs locally, never trains on my data, has plenty of context for repetitive jobs.

When in doubt, I keep reasoning and prose in cloud, push everything else to the lab.

## When to use cloud Claude vs the lab

**Cloud Claude**, when the work needs:
- Deep reasoning across an unfamiliar domain
- Creative writing, voice, or nuance (essays, emails, design rationale)
- Code architecture decisions or hairy debugging
- Something I'd be embarrassed to read aloud if it came out wrong

**The lab**, when the work is:
- Bulk classification, tagging, or extraction over many items
- Structured output from messy input (forms, PDFs, transcripts)
- Embeddings for semantic search or deduplication
- First-draft code (function bodies, test scaffolds, regex)
- Summarization of long content I'll review by hand
- Anything I'd run hundreds of times if it were free, because here it basically is

A useful test: if I'd hesitate to run this 100 times on cloud Claude because of cost, run it on the lab.

## My budget

The lab gives me **200 requests per day and 500,000 tokens per day** by default. That's a lot for code and structured work, not a lot for chatty back-and-forth. I keep an eye on usage at `lab.counselorjay.com/dashboard/` and ask Jay if I need a temporary bump.

## How to invoke the lab

Two ways. Pick whichever fits the task.

### Way 1: one-shot via `ewok-lab chat`

Best for scripted runs, batch jobs, and things I want to capture in a Bash tool call.

```bash
# Plain chat: pipe a prompt in, get a response out
ewok-lab chat qwen3.5:35b-a3b-nvfp4 < prompt.txt > response.txt

# With a system prompt
ewok-lab chat qwen3.5:35b-a3b-nvfp4 \
  --system "You are a strict JSON extractor. Output only valid JSON." \
  < input.txt
```

### Way 2: long-running proxy via `ewok-lab serve`

Best for tools that already speak Ollama (Continue, custom scripts that call `http://localhost:11434`, anything OpenAI-compatible).

```bash
# In a dedicated terminal, leave running:
ewok-lab serve

# Now any tool pointed at http://localhost:11435 routes through the lab.
# Auth is handled for me; I don't need to think about API keys after this.
```

I usually start `ewok-lab serve` at the beginning of a working session and forget about it.

## Recipes

Concrete bash patterns I lean on. Adjust models per task. `qwen3.5:35b-a3b-nvfp4` is the safe default for prose and code; `gemma4:31b` is stronger for vision and gnarly reasoning; `gemma4:e4b` is the fast triage option; `nomic-embed-text` is for embeddings.

### Recipe 1: classify a CSV of items

```bash
# items.csv has one item per line, header "text"
# Goal: add a "category" column with a label from a fixed taxonomy.

tail -n +2 items.csv | while IFS= read -r line; do
  category=$(echo "$line" | ewok-lab chat gemma4:e4b \
    --system "Classify the input into one of: news, opinion, research, ad. Output only the label." \
    --no-stream)
  echo "${line},${category}"
done > items_classified.csv
```

When to escalate to cloud Claude: if I see misclassifications in the obvious cases, I show 5 examples to cloud Claude and ask it to rewrite the system prompt. Then I rerun the cheap loop.

### Recipe 2: extract structured data from PDFs

```bash
# Goal: pull {title, author, year, abstract} out of a folder of academic PDFs.

for pdf in papers/*.pdf; do
  text=$(pdftotext "$pdf" -)
  echo "$text" | ewok-lab chat qwen3.5:35b-a3b-nvfp4 \
    --system 'Extract title, author, year, abstract as JSON. If a field is missing, use null. Output only JSON.' \
    --format json \
    > "${pdf%.pdf}.json"
done
```

When to escalate: I have cloud Claude review 3 sample JSONs against the source PDFs to catch systematic extraction bugs before I trust the rest.

### Recipe 3: embed a corpus for semantic search

```bash
# Goal: build a queryable index of notes/.

# Start the local proxy so I can use any Ollama-compatible embedding client.
ewok-lab serve &

# Embed each file. Most embedding tools take Ollama as a backend trivially.
python3 build_index.py --embedding-host http://localhost:11435 \
  --model nomic-embed-text \
  --input notes/ \
  --output index.parquet
```

`nomic-embed-text` produces 768-dim vectors with an 8K context window. Plenty for paragraph-level chunks.

### Recipe 4: draft a function then have cloud Claude review it

```bash
# Step 1: lab drafts the function from a spec.
cat spec.md | ewok-lab chat qwen3.5:35b-a3b-nvfp4 \
  --system "You are a careful Python engineer. Write the function, no commentary. Match PEP 8." \
  > draft.py

# Step 2: I paste draft.py into this Claude Code session and ask:
# "Review draft.py against spec.md. Find correctness bugs and edge cases I missed."
```

This is the orchestrator pattern in two lines: lab drafts, cloud reviews. The lab is fast and cheap enough that I can iterate on the draft 5 times before cloud Claude even sees it.

## Models I reach for

| Model | Use it for |
|-------|------------|
| `qwen3.5:35b-a3b-nvfp4` | General default. Prose, code drafts, structured extraction. Fast (MoE). |
| `gemma4:31b`            | Vision tasks, the trickiest reasoning, code I want to be sure about. Slower, denser. |
| `gemma4:26b`            | Bulk processing, multilingual content, long context (256K). |
| `gemma4:e4b`            | Fast triage, classification at scale, anything where latency matters more than depth. |
| `nomic-embed-text`      | Embeddings only. Use via `/api/embed` or any Ollama-compatible client. |

`qwen3.5:35b-a3b-nvfp4` is the right answer 80% of the time. Reach for the others when you have a specific reason.

A few tags are reserved for Jay's research and will return a 403 if I try to use them. The error message tells me what to use instead. I trust the error and move on.

## Etiquette

- I don't run training loops or sustained high-rate scrapers through the lab. If I have a job that needs more than 200 requests a day, I ping Jay first.
- I check `lab.counselorjay.com/dashboard/` if responses get slow. A backend may be down or saturated; the dashboard tells me which.
- I treat my API key like a password. It lives in `~/.ewok-lab/config.toml` and never in a repo.

## When something goes wrong

- **`ewok-lab chat` hangs**: the lab might be saturated. Check the dashboard. The gateway returns 503 with a `Retry-After` header when all backends are full; the CLI surfaces that.
- **403 on a model name**: the model is reserved. The error message says what to use instead.
- **429**: I hit my daily quota. Wait until midnight Pacific or ask Jay.
- **My code works locally but not via `ewok-lab serve`**: confirm the tool is pointed at `http://localhost:11435`, not 11434. 11434 is the local Ollama port; 11435 is the lab proxy.

## House rules

- I read the lab dashboard before assuming anything is broken.
- I escalate to cloud Claude when the lab's output feels off, not when I'm bored.
- I keep `CLAUDE.md` updated as my project evolves so future me, and Claude Code, can pick up where I left off.
