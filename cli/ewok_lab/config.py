"""Read/write ~/.ewok-lab/config.toml with mode 0600."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

if sys.version_info >= (3, 11):
    import tomllib  # type: ignore[import-not-found]
else:  # pragma: no cover
    import tomli as tomllib  # type: ignore[no-redef]

import tomli_w


CONFIG_DIR = Path.home() / ".ewok-lab"
CONFIG_PATH = CONFIG_DIR / "config.toml"
DEFAULT_GATEWAY = "https://lab.counselorjay.com"


@dataclass
class Config:
    gateway: str
    api_key: str

    def to_dict(self) -> dict:
        return {"gateway": self.gateway, "api_key": self.api_key}


def load() -> Optional[Config]:
    if not CONFIG_PATH.is_file():
        return None
    with CONFIG_PATH.open("rb") as f:
        data = tomllib.load(f)
    if "api_key" not in data or "gateway" not in data:
        return None
    return Config(gateway=data["gateway"], api_key=data["api_key"])


def save(cfg: Config) -> Path:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    tmp = CONFIG_PATH.with_suffix(".toml.tmp")
    with tmp.open("wb") as f:
        tomli_w.dump(cfg.to_dict(), f)
    tmp.replace(CONFIG_PATH)
    os.chmod(CONFIG_PATH, 0o600)
    return CONFIG_PATH


def require() -> Config:
    cfg = load()
    if cfg is None:
        raise SystemExit(
            "Not logged in. Run `ewok-lab login` first to save your API key."
        )
    return cfg
