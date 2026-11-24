"""Settings loaded from the environment, plus the execution boot guard."""

from __future__ import annotations

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app import heuristics


class Settings(BaseSettings):
    """Application settings. Field names mirror .env.example, lowercased."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Several keys are supported because the free tier's per-day quota is per
    # project, not per caller: one key runs out long before a working session
    # does. GOOGLE_API_KEY stays the single-key name so existing setups keep
    # working; the numbered ones are additive.
    google_api_key: str = ""
    google_api_key1: str = ""
    google_api_key2: str = ""
    google_api_key3: str = ""
    llm_model: str = "gemini-3.1-flash-lite"
    llm_timeout_s: int = 60

    deployment_env: str = "local"

    # Stage 6 / MVP-1.5. Read by execution.py and the /execute route. Off by
    # default, and refused at boot outside DEPLOYMENT_ENV=local (see the guard
    # at the bottom of this file). scikit-learn is deliberately not a backend
    # dependency: generated code runs under RUNNER_PYTHON, a separate venv,
    # which is what makes a later container boundary a swap rather than a
    # rewrite.
    enable_local_execution: bool = False
    execution_timeout_s: int = 60
    execution_sample_rows: int = 500
    # POSIX venv layout. On Windows, execution.resolve_runner_python also
    # tries the Scripts\python.exe equivalent, so one .env works on both.
    runner_python: str = ".venv-runner/bin/python"
    # Which Sandbox runs the code. "subprocess" uses RUNNER_PYTHON directly;
    # "docker" runs the same script in a locked-down container built from
    # backend/runner.Dockerfile. Only "docker" may run outside DEPLOYMENT_ENV=local.
    execution_backend: str = "subprocess"
    execution_docker_image: str = "autonexus-runner:latest"

    upload_dir: str = "./data/uploads"
    db_path: str = "./data/app.db"
    dataset_ttl_hours: int = 24
    max_file_mb: int = 50
    max_cols: int = 1000

    cors_origins: str = Field(
        default="http://localhost:5173",
        description="Comma-separated list of allowed origins.",
    )

    # Comma-separated bearer tokens. Empty means no authentication, which is
    # permitted only for DEPLOYMENT_ENV=local (see the guard at the bottom).
    # Several are allowed so one can be rotated out without locking everyone.
    api_tokens: str = ""

    # Requests per window per client. Defaults are the defended constants in
    # heuristics.py; these exist so an operator can tighten them per
    # deployment without a code change.
    rate_limit_generations_per_hour: int = heuristics.RATE_LIMIT_GENERATIONS_PER_HOUR
    rate_limit_uploads_per_hour: int = heuristics.RATE_LIMIT_UPLOADS_PER_HOUR
    rate_limit_executions_per_hour: int = heuristics.RATE_LIMIT_EXECUTIONS_PER_HOUR
    rate_limit_requests_per_minute: int = heuristics.RATE_LIMIT_REQUESTS_PER_MINUTE

    @field_validator("deployment_env")
    @classmethod
    def _known_environment(cls, value: str) -> str:
        if value not in {"local", "hosted"}:
            raise ValueError("DEPLOYMENT_ENV must be 'local' or 'hosted'")
        return value

    @field_validator("execution_backend")
    @classmethod
    def _known_backend(cls, value: str) -> str:
        if value not in {"subprocess", "docker"}:
            raise ValueError("EXECUTION_BACKEND must be 'subprocess' or 'docker'")
        return value

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def api_token_list(self) -> list[str]:
        return [token.strip() for token in self.api_tokens.split(",") if token.strip()]

    @property
    def google_api_key_list(self) -> list[str]:
        """Every configured key, in declaration order, deduplicated.

        Order is stable so the rotation cursor in llm.py means the same thing
        across a restart. Duplicates are dropped because two entries holding
        the same key would look like two quotas and are one - the rotation
        would "fail over" onto the key that just returned 429.
        """
        candidates = [
            self.google_api_key,
            self.google_api_key1,
            self.google_api_key2,
            self.google_api_key3,
        ]
        seen: set[str] = set()
        keys: list[str] = []
        for candidate in candidates:
            key = candidate.strip()
            if key and key not in seen:
                seen.add(key)
                keys.append(key)
        return keys


settings = Settings()

# Boot guard, not a convention. The subprocess sandbox runs generated code with
# no container boundary around it, which is acceptable on a developer's own
# machine and is not acceptable anywhere else. Failing at import time makes a
# misconfigured deployment impossible to start rather than quietly dangerous.
#
# The Docker sandbox is the boundary ADR 0002 named as the precondition for
# running anywhere but localhost, so with EXECUTION_BACKEND=docker a hosted
# deployment may execute - and the guard below still demands API_TOKENS there.
if (
    settings.enable_local_execution
    and settings.deployment_env != "local"
    and settings.execution_backend != "docker"
):
    raise RuntimeError(
        "ENABLE_LOCAL_EXECUTION outside DEPLOYMENT_ENV=local requires EXECUTION_BACKEND=docker"
    )

# Same principle for access control. A hosted deployment with no tokens would
# let anyone who can reach it upload files and spend the model quota, so it is
# made impossible to start rather than documented as a bad idea.
if settings.deployment_env == "hosted" and not settings.api_token_list:
    raise RuntimeError("DEPLOYMENT_ENV=hosted requires API_TOKENS to be set")
