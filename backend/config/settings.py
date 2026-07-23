"""Typed application configuration.

Every external credential is optional. The system boots with none of them set,
records which capabilities are consequently degraded, and falls back to local
inference. `Settings.capability_report()` is what the /health endpoint and the
startup log both read, so the degradation story is stated in exactly one place.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml
from pydantic import Field, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = Path(__file__).resolve().parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=REPO_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ---- application -------------------------------------------------------
    app_env: Literal["development", "staging", "production"] = "development"
    log_level: str = "INFO"
    cors_origins: str = "http://localhost:3000"

    # ---- agent behaviour (§5.3) -------------------------------------------
    max_replan_cycles: int = Field(default=3, ge=1, le=5)
    grader_threshold: float = Field(default=0.7, ge=0.0, le=1.0)

    # ---- Dubai Pulse legacy gateway (optional) ----------------------------
    dubai_pulse_api_key: str | None = None
    dubai_pulse_api_secret: str | None = None

    # ---- LLM providers (all optional) -------------------------------------
    groq_api_key: str | None = None
    gemini_api_key: str | None = None
    cerebras_api_key: str | None = None

    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "qwen2.5:7b"

    # ---- datastores --------------------------------------------------------
    postgres_user: str = "masar"
    postgres_password: str = "masar_dev_password"
    postgres_db: str = "masar"
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_ro_user: str = "masar_ro"
    postgres_ro_password: str = "masar_ro_dev_password"

    redis_url: str = "redis://localhost:6379/0"

    # ---- tracing (optional) ------------------------------------------------
    langsmith_api_key: str | None = None
    langsmith_project: str = "masar-ai"
    langsmith_tracing: bool = False

    # ---- derived paths -----------------------------------------------------
    @computed_field  # type: ignore[prop-decorator]
    @property
    def repo_root(self) -> Path:
        return REPO_ROOT

    @property
    def bronze_dir(self) -> Path:
        return REPO_ROOT / "data" / "bronze"

    @property
    def silver_dir(self) -> Path:
        return REPO_ROOT / "data" / "silver"

    @property
    def gold_dir(self) -> Path:
        return REPO_ROOT / "data" / "gold"

    @property
    def corpus_dir(self) -> Path:
        return REPO_ROOT / "data" / "corpus"

    @property
    def dq_report_dir(self) -> Path:
        return REPO_ROOT / "reports" / "dq"

    @property
    def eval_report_dir(self) -> Path:
        return REPO_ROOT / "reports" / "eval"

    @property
    def trace_dir(self) -> Path:
        return REPO_ROOT / "traces"

    # ---- connection strings ------------------------------------------------
    @property
    def pg_dsn(self) -> str:
        """Read-write DSN — used by the ETL and the application."""
        return (
            f"postgresql://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def pg_dsn_readonly(self) -> str:
        """Read-only DSN — the ONLY connection the Text-to-SQL agent may use (§5.3 A8)."""
        return (
            f"postgresql://{self.postgres_ro_user}:{self.postgres_ro_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    # ---- capability reporting ---------------------------------------------
    @property
    def available_providers(self) -> list[str]:
        """Cloud providers with a usable key, plus Ollama which never needs one."""
        present = [
            name
            for name, key in (
                ("groq", self.groq_api_key),
                ("gemini", self.gemini_api_key),
                ("cerebras", self.cerebras_api_key),
            )
            if key
        ]
        return [*present, "ollama"]

    def capability_report(self) -> dict[str, object]:
        """Named degradations, for the startup log and /health.

        Missing keys are reported as degraded capabilities, never as errors —
        the system is designed to run without any of them.
        """
        degraded: list[str] = []

        if not self.groq_api_key:
            degraded.append(
                "GROQ_API_KEY absent — fast routing and grading fall back to Cerebras/Ollama"
            )
        if not self.gemini_api_key:
            degraded.append(
                "GEMINI_API_KEY absent — planning, Text-to-SQL and Arabic synthesis lose their strongest model"
            )
        if not self.cerebras_api_key:
            degraded.append("CEREBRAS_API_KEY absent — one fallback tier removed from every chain")
        if not (self.dubai_pulse_api_key and self.dubai_pulse_api_secret):
            degraded.append(
                "DUBAI_PULSE credentials absent — A9 serves archived snapshots only (expected default)"
            )
        if not self.langsmith_api_key:
            degraded.append("LANGSMITH_API_KEY absent — tracing writes to local JSONL instead")

        cloud = [p for p in self.available_providers if p != "ollama"]
        return {
            "providers_available": self.available_providers,
            "cloud_providers": len(cloud),
            "degraded_mode": len(cloud) == 0,
            "degradations": degraded,
        }


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


@lru_cache(maxsize=1)
def get_model_config() -> dict:
    """Parsed models.yaml — the routing policy from §4.2."""
    with (CONFIG_DIR / "models.yaml").open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)
