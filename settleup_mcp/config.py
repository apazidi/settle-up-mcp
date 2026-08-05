"""Read the server configuration from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache

SANDBOX_BASE_URL = "https://settle-up-sandbox.firebaseio.com"
LIVE_BASE_URL = "https://settle-up-live.firebaseio.com"

SIGN_IN_URL = "https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword"
REFRESH_URL = "https://securetoken.googleapis.com/v1/token"


class ConfigError(RuntimeError):
    """The configuration is not complete or not valid."""


def _required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ConfigError(
            f"The environment variable {name} is empty. "
            f"Set {name} before you start the server."
        )
    return value


def _int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError as error:
        raise ConfigError(
            f"The environment variable {name} must be a whole number. "
            f"The current value is {raw!r}."
        ) from error


@dataclass(frozen=True)
class Settings:
    """All values that the server needs at run time."""

    email: str
    password: str
    firebase_api_key: str
    base_url: str
    request_timeout_seconds: float
    token_refresh_margin_seconds: int
    host: str
    port: int
    path: str
    log_level: str
    auth_token: str | None

    @property
    def is_sandbox(self) -> bool:
        return "sandbox" in self.base_url


def load_settings() -> Settings:
    """Read each value from the environment. Raise ConfigError on a problem."""
    base_url = os.environ.get("SETTLEUP_BASE_URL", SANDBOX_BASE_URL).strip()
    base_url = base_url.rstrip("/")
    if not base_url.startswith("https://"):
        raise ConfigError(
            "SETTLEUP_BASE_URL must start with https://. "
            f"The current value is {base_url!r}."
        )

    token = os.environ.get("MCP_AUTH_TOKEN", "").strip() or None

    return Settings(
        email=_required("SETTLEUP_EMAIL"),
        password=_required("SETTLEUP_PASSWORD"),
        firebase_api_key=_required("SETTLEUP_FIREBASE_API_KEY"),
        base_url=base_url,
        request_timeout_seconds=float(_int("SETTLEUP_TIMEOUT_SECONDS", 30)),
        token_refresh_margin_seconds=_int("SETTLEUP_TOKEN_REFRESH_MARGIN", 300),
        host=os.environ.get("MCP_HOST", "0.0.0.0").strip(),
        port=_int("MCP_PORT", 8000),
        path=os.environ.get("MCP_PATH", "/mcp").strip(),
        log_level=os.environ.get("LOG_LEVEL", "INFO").strip().upper(),
        auth_token=token,
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Give the settings. Read the environment one time only."""
    return load_settings()
