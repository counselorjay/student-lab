"""ewok-lab CLI entry point."""

from __future__ import annotations

import asyncio
import json
import sys
from getpass import getpass
from typing import Optional

import httpx
import typer
from rich.console import Console
from rich.table import Table

from . import config as cfg_mod
from .client import GatewayClient, validate_key


app = typer.Typer(add_completion=False, no_args_is_help=True, help="Talk to Jay's student-lab gateway.")
console = Console()


@app.command()
def login(
    gateway: str = typer.Option(cfg_mod.DEFAULT_GATEWAY, "--gateway", help="Gateway URL"),
    api_key: Optional[str] = typer.Option(None, "--api-key", help="API key (otherwise prompted)"),
):
    """Save an API key to ~/.ewok-lab/config.toml."""
    if not api_key:
        api_key = getpass("API key: ").strip()
    if not api_key.startswith("slk_"):
        console.print("[red]Keys start with 'slk_'. Did you paste the right thing?[/red]")
        raise typer.Exit(code=1)

    me = validate_key(gateway, api_key)
    if me is None:
        console.print("[red]Gateway rejected that key (401/403). Not saved.[/red]")
        raise typer.Exit(code=1)

    path = cfg_mod.save(cfg_mod.Config(gateway=gateway, api_key=api_key))
    console.print(f"[green]Saved[/green] -> {path}")
    console.print(f"Logged in as [bold]{me['email']}[/bold] ({me['user_id']}).")


@app.command()
def status():
    """Show backend health and your usage."""
    cfg = cfg_mod.require()
    client = GatewayClient(cfg)
    try:
        s = client.status()
        me = client.me()
    except httpx.HTTPError as exc:
        console.print(f"[red]Could not reach {cfg.gateway}: {exc}[/red]")
        raise typer.Exit(code=1)

    backends = Table(title="Backends")
    backends.add_column("name")
    backends.add_column("online")
    backends.add_column("queue")
    backends.add_column("models")
    for b in s["backends"]:
        backends.add_row(
            b["name"],
            "yes" if b["online"] else "no",
            str(b["queue_depth"]),
            ", ".join(b["models_loaded"][:5]) + ("..." if len(b["models_loaded"]) > 5 else ""),
        )
    console.print(backends)

    usage = Table(title=f"Today's usage for {me['email']}")
    usage.add_column("metric")
    usage.add_column("used")
    usage.add_column("limit")
    usage.add_row(
        "requests",
        str(me["used"]["requests_today"]),
        str(me["quotas"]["requests_per_day"]),
    )
    usage.add_row(
        "tokens",
        str(me["used"]["tokens_today"]),
        str(me["quotas"]["tokens_per_day"]),
    )
    console.print(usage)


@app.command()
def models():
    """List available models on the gateway."""
    cfg = cfg_mod.require()
    client = GatewayClient(cfg)
    try:
        data = client.tags()
    except httpx.HTTPError as exc:
        console.print(f"[red]Could not reach {cfg.gateway}: {exc}[/red]")
        raise typer.Exit(code=1)
    t = Table(title="Available models")
    t.add_column("name")
    t.add_column("size")
    for m in data.get("models", []):
        size = m.get("size")
        size_str = f"{size / 1e9:.1f} GB" if isinstance(size, (int, float)) else ""
        t.add_row(m.get("name", "?"), size_str)
    console.print(t)


@app.command()
def chat(
    model: str = typer.Argument(..., help="Model name, e.g. qwen3.5:35b-a3b-nvfp4"),
    once: bool = typer.Option(False, "--once", help="Read one prompt from stdin and exit"),
    system: Optional[str] = typer.Option(
        None,
        "--system",
        help="System prompt prepended to the chat history (REPL and --once modes).",
    ),
    no_stream: bool = typer.Option(
        False,
        "--no-stream",
        help="Send a non-streaming request and print the response in one shot.",
    ),
    fmt: Optional[str] = typer.Option(
        None,
        "--format",
        help="Pass through to Ollama (e.g. 'json' to force JSON output).",
    ),
):
    """REPL chat. With --once, reads stdin and prints the response."""
    cfg = cfg_mod.require()
    client = GatewayClient(cfg)

    if once or not sys.stdin.isatty():
        prompt = sys.stdin.read()
        if not prompt.strip():
            console.print("[red]Empty stdin.[/red]")
            raise typer.Exit(code=1)
        msgs: list[dict] = []
        if system:
            msgs.append({"role": "system", "content": system})
        msgs.append({"role": "user", "content": prompt})
        if no_stream:
            _run_oneshot_blocking(client, model, msgs, fmt)
        else:
            asyncio.run(_run_one(client, model, msgs, fmt))
        return

    console.print(f"[bold]chat[/bold] -> {model}. Type a message; Ctrl+D to send. Ctrl+C to exit.")
    history: list[dict] = []
    if system:
        history.append({"role": "system", "content": system})
    while True:
        console.print("[cyan]you>[/cyan] ", end="")
        try:
            lines: list[str] = []
            while True:
                line = sys.stdin.readline()
                if line == "":
                    break
                lines.append(line)
            prompt = "".join(lines).strip()
        except KeyboardInterrupt:
            console.print()
            return
        if not prompt:
            continue
        history.append({"role": "user", "content": prompt})
        if no_stream:
            reply = _run_oneshot_blocking(client, model, history, fmt)
        else:
            reply = asyncio.run(_run_chat(client, model, history, fmt))
        history.append({"role": "assistant", "content": reply})


async def _run_one(
    client: GatewayClient,
    model: str,
    messages: list[dict],
    fmt: Optional[str] = None,
) -> None:
    async for chunk in client.chat_stream(model, messages, format=fmt):
        msg = chunk.get("message", {})
        sys.stdout.write(msg.get("content", ""))
        sys.stdout.flush()
        if chunk.get("done"):
            sys.stdout.write("\n")


async def _run_chat(
    client: GatewayClient,
    model: str,
    messages: list[dict],
    fmt: Optional[str] = None,
) -> str:
    out: list[str] = []
    console.print("[green]bot>[/green] ", end="")
    async for chunk in client.chat_stream(model, messages, format=fmt):
        msg = chunk.get("message", {})
        piece = msg.get("content", "")
        out.append(piece)
        sys.stdout.write(piece)
        sys.stdout.flush()
        if chunk.get("done"):
            sys.stdout.write("\n")
            sys.stdout.flush()
    return "".join(out)


def _run_oneshot_blocking(
    client: GatewayClient,
    model: str,
    messages: list[dict],
    fmt: Optional[str] = None,
) -> str:
    """Non-streaming POST. Prints the assistant content and returns it."""
    resp = client.chat_oneshot(model, messages, format=fmt)
    content = resp.get("message", {}).get("content", "")
    sys.stdout.write(content)
    if not content.endswith("\n"):
        sys.stdout.write("\n")
    sys.stdout.flush()
    return content


@app.command()
def serve(
    port: int = typer.Option(11435, "--port", help="Local port to bind"),
    host: str = typer.Option("127.0.0.1", "--host", help="Bind host"),
):
    """Start a localhost Ollama-compatible proxy backed by the gateway."""
    from . import proxy_server

    cfg = cfg_mod.require()
    console.print(
        f"Listening on [bold]http://{host}:{port}[/bold] -> {cfg.gateway}. "
        "Point any Ollama-aware tool at this URL."
    )
    proxy_server.serve(cfg, host=host, port=port)


if __name__ == "__main__":
    app()
