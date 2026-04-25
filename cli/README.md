# ewok-lab CLI

Thin client for Jay's student-lab gateway at `lab.counselorjay.com`. Login once, then use any of:

- `ewok-lab status` — backend health + your usage today
- `ewok-lab models` — what's loadable
- `ewok-lab chat <model>` — interactive or piped chat
- `ewok-lab serve` — runs a localhost Ollama-compatible proxy on `:11435` so any Ollama-aware tool (Continue, Claude Code custom commands, etc.) just works

## Install

```bash
pip install git+https://github.com/sophieclawjay/student-lab#subdirectory=cli
```

Or, while developing locally:

```bash
cd cli
pip install -e .
```

## Login

```bash
ewok-lab login
# Paste your API key (starts with slk_). Stored at ~/.ewok-lab/config.toml (mode 0600).
```

To point at a non-default gateway (e.g. local dev):

```bash
ewok-lab login --gateway http://localhost:8700
```

## Quickstart

```bash
ewok-lab status
ewok-lab models
echo "Summarize Plato's Republic in 50 words." | ewok-lab chat qwen3.5:35b-a3b-nvfp4 --once
```

## Use with any Ollama-aware tool

```bash
ewok-lab serve
# In another terminal: point your tool at http://localhost:11435
```

The proxy faithfully reproduces Ollama's `/api/chat`, `/api/generate`, `/api/embed`, `/api/tags`, and `/api/show`.

## Config file

Lives at `~/.ewok-lab/config.toml`:

```toml
gateway = "https://lab.counselorjay.com"
api_key = "slk_..."
```

Mode `0600`. Don't commit it.
