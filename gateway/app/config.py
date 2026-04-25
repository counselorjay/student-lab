"""Gateway configuration loaded from environment / .env."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


_GATEWAY_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_GATEWAY_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    admin_email: str = "jay@counselorjay.com"

    backend_m5_max: Optional[str] = "http://100.83.184.88:11434"
    backend_m5_pro: Optional[str] = "http://100.120.197.64:11434"
    # M3 Pro is deliberately excluded from the student fleet (Jay 2026-04-24).
    # It is the daily driver and stays out of shared rotation.

    db_path: str = "data/lab.db"
    health_probe_interval: int = 15
    health_probe_timeout: int = 3
    health_fail_threshold: int = 3

    default_daily_request_limit: int = 200
    default_daily_token_limit: int = 500000

    proxy_timeout: int = 600

    dashboard_dir: str = "../dashboard"

    # Reserved models per Felix ROUTING.md §6 — hard 403 at router level.
    reserved_models: tuple[str, ...] = (
        "qwen3.6:35b",
        "qwen3.6:latest",
        "qwen3.6:35b-a3b-nvfp4",
    )

    # Per-backend in-flight cap per Felix ROUTING.md §2.1.
    backend_queue_caps: dict[str, int] = {
        "m5-max": 2,
        "m5-pro": 1,
    }

    @property
    def gateway_root(self) -> Path:
        return _GATEWAY_ROOT

    @property
    def db_full_path(self) -> Path:
        p = Path(self.db_path)
        if not p.is_absolute():
            p = _GATEWAY_ROOT / p
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    def backends(self) -> dict[str, str]:
        """Return mapping of backend name to URL for non-empty backends."""
        out: dict[str, str] = {}
        if self.backend_m5_max:
            out["m5-max"] = self.backend_m5_max.rstrip("/")
        if self.backend_m5_pro:
            out["m5-pro"] = self.backend_m5_pro.rstrip("/")
        return out


_settings: Optional[Settings] = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def set_settings_for_test(s: Settings) -> None:
    """Test hook: install a Settings instance instead of reading env."""
    global _settings
    _settings = s
