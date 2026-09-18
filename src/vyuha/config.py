"""Central configuration. Everything is overridable via env vars prefixed VYUHA_."""

from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="VYUHA_", env_file=".env", extra="ignore")

    # --- storage ---
    data_dir: Path = REPO_ROOT / "data"
    cache_dir: Path = REPO_ROOT / "data" / "cache"
    db_path: Path = REPO_ROOT / "data" / "vyuha.duckdb"

    # --- ingest behaviour ---
    http_timeout: float = 30.0
    http_retries: int = 3
    cache_ttl_seconds: int = 3600
    user_agent: str = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )
    # Some endpoints (FRED's CDN) time out on a browser User-Agent while
    # serving a plain client fine; others (NSE) refuse anything that is NOT a
    # browser. There is no single UA that works everywhere, so sources pick.
    api_user_agent: str = "vyuha/0.1 (+https://github.com/vyuha-risk/vyuha)"

    # Politeness: minimum seconds between requests to the same host.
    min_request_interval: float = 0.6

    # --- optional API keys (all sources work without them; these unlock extras) ---
    data_gov_in_key: str | None = None
    fred_api_key: str | None = None

    # --- council ---
    ollama_host: str = "http://localhost:11434"
    council_log_dir: Path = REPO_ROOT / "council_runs"
    council_rounds: int = 2
    council_temperature: float = 0.3

    # --- risk defaults ---
    trading_days_per_year: int = 252
    default_var_horizon_days: int = 1
    default_var_confidence: float = 0.99
    ewma_lambda: float = 0.94  # RiskMetrics

    calendar: str = "XNSE"
    base_currency: str = "INR"

    extra_paths: dict[str, str] = Field(default_factory=dict)

    def ensure_dirs(self) -> None:
        for p in (self.data_dir, self.cache_dir, self.council_log_dir):
            p.mkdir(parents=True, exist_ok=True)


settings = Settings()
