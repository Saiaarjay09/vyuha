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

    # --- retrieval ---
    # Retrieval adds ~10s and can make forecasts WORSE if unfiltered: a model
    # given fifty articles attends to them less carefully than one given
    # three. Kept deliberately small, and easy to turn off.
    retrieval_enabled: bool = True
    retrieval_keep: int = 5
    retrieval_max_age_hours: float = 72.0

    # --- access control ---
    # When set, the expensive routes require this token. Empty means open,
    # which is the right default for a laptop and the wrong one for a public
    # URL. Set VYUHA_ACCESS_TOKEN in the environment; never commit it.
    access_token: str = ""
    # Even with a token, cap how often inference can be triggered. A leaked
    # link should cost you a slow afternoon, not an unbounded compute bill.
    rate_limit_per_hour: int = 60

    # --- council / inference ---
    # "auto" prefers a local Ollama and falls back to a hosted endpoint, which
    # is what lets the same code run on a laptop and on a 512MB cloud dyno.
    llm_provider: str = "auto"           # auto | ollama | hosted | echo
    llm_base_url: str = ""               # any OpenAI-compatible endpoint
    llm_api_key: str = ""                # set via env/secret, never committed
    llm_model: str = ""                  # override model selection entirely
    ollama_host: str = "http://localhost:11434"
    # A single hung member must never block a whole council run, so every
    # request is bounded. Generous enough to cover a cold model load, short
    # enough that a stuck one is reported rather than waited on forever.
    llm_timeout: float = 120.0
    # Context window. Prompts here run ~1,500 tokens; letting Ollama reserve a
    # 32k KV cache per model is what exhausts memory once several families are
    # in play.
    llm_num_ctx: int = 8192
    # How many distinct model families may be held in memory at once. Running
    # members of different models in parallel forces simultaneous loads, which
    # on a machine with finite RAM causes thrashing or an outright stall.
    max_resident_models: int = 2
    # When several installed models could serve, prefer the smaller ones.
    # Generation time is essentially all of a council run's latency and scales
    # with parameter count, so on a ten-member panel the choice between an 8B
    # and a 14B model is the difference between waiting and giving up. Set
    # false to honour each persona's stated preference regardless of cost.
    prefer_fast_models: bool = True
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
