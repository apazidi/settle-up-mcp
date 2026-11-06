"""Read and validate server configuration without exposing credentials."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from urllib.parse import urlsplit

SANDBOX_BASE_URL = "https://settle-up-sandbox.firebaseio.com"
LIVE_BASE_URL = "https://settle-up-live.firebaseio.com"
SIGN_IN_URL = "https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword"
REFRESH_URL = "https://securetoken.googleapis.com/v1/token"


class ConfigError(RuntimeError):
    """The configuration is incomplete or invalid."""


def _required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ConfigError(f"Set {name} before starting the server.")
    return value


def _int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError as error:
        raise ConfigError(f"{name} must be a whole number.") from error


@dataclass(frozen=True)
class GoogleOAuthSettings:
    """One allowed Google identity protects one configured Settle Up account."""

    client_id: str
    client_secret: str = field(repr=False)
    base_url: str
    allowed_email: str
    signing_key: str = field(repr=False)
    client_redirect_uris: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.client_id or not self.client_secret:
            raise ConfigError("Google OAuth requires a client ID and client secret.")
        if not self.allowed_email or "@" not in self.allowed_email:
            raise ConfigError("Set MCP_GOOGLE_ALLOWED_EMAIL to the account owner.")
        if len(self.signing_key) < 32:
            raise ConfigError("MCP_OAUTH_SIGNING_KEY must contain at least 32 characters.")
        _validate_public_origin(self.base_url)
        if not self.client_redirect_uris:
            raise ConfigError("Set MCP_OAUTH_CLIENT_REDIRECT_URIS to exact client callbacks.")
        for uri in self.client_redirect_uris:
            parsed = urlsplit(uri)
            if (parsed.scheme != "https" or not parsed.hostname
                    or parsed.username or parsed.password or parsed.fragment
                    or any(char in uri for char in "*?[]")):
                raise ConfigError("MCP_OAUTH_CLIENT_REDIRECT_URIS requires exact HTTPS URLs.")


def _validate_public_origin(value: str) -> None:
    parsed = urlsplit(value)
    if (parsed.scheme != "https" or not parsed.hostname
            or parsed.username or parsed.password or parsed.query or parsed.fragment
            or parsed.path not in ("", "/")):
        raise ConfigError("MCP_PUBLIC_URL must be an HTTPS origin without a path or query.")


@dataclass(frozen=True)
class Settings:
    """Runtime settings. Secret values are omitted from repr()."""

    email: str
    password: str = field(repr=False)
    firebase_api_key: str = field(repr=False)
    base_url: str
    request_timeout_seconds: float
    token_refresh_margin_seconds: int
    host: str
    port: int
    path: str
    log_level: str
    auth_token: str | None = field(repr=False)
    refresh_token: str | None = field(default=None, repr=False)
    auth_mode: str = "token"
    google_oauth: GoogleOAuthSettings | None = None

    @property
    def is_sandbox(self) -> bool:
        return self.base_url == SANDBOX_BASE_URL

    def validate_auth(self) -> None:
        if self.auth_mode == "token":
            if not self.auth_token:
                raise ConfigError("MCP_AUTH_MODE=token requires MCP_AUTH_TOKEN.")
            if self.google_oauth:
                raise ConfigError("Choose either token or Google OAuth authentication.")
        elif self.auth_mode == "google":
            if self.google_oauth is None:
                raise ConfigError("MCP_AUTH_MODE=google requires Google OAuth settings.")
            if self.auth_token:
                raise ConfigError("Unset MCP_AUTH_TOKEN when using Google OAuth.")
        elif self.auth_mode == "none":
            if self.host not in ("127.0.0.1", "::1", "localhost"):
                raise ConfigError("MCP_AUTH_MODE=none is restricted to a loopback listener.")
            if self.auth_token or self.google_oauth:
                raise ConfigError("Remove authentication settings before selecting none.")
        else:
            raise ConfigError("MCP_AUTH_MODE must be token, google, or none.")


def load_settings() -> Settings:
    base_url = os.environ.get("SETTLEUP_BASE_URL", SANDBOX_BASE_URL).strip().rstrip("/")
    if base_url not in (SANDBOX_BASE_URL, LIVE_BASE_URL):
        raise ConfigError("SETTLEUP_BASE_URL must be the Settle Up sandbox or live URL.")

    refresh_token = os.environ.get("SETTLEUP_REFRESH_TOKEN", "").strip() or None
    email = os.environ.get("SETTLEUP_EMAIL", "").strip()
    password = os.environ.get("SETTLEUP_PASSWORD", "")
    if not refresh_token and not (email and password):
        raise ConfigError("Set SETTLEUP_REFRESH_TOKEN or both SETTLEUP_EMAIL and SETTLEUP_PASSWORD.")

    mode = os.environ.get("MCP_AUTH_MODE", "token").strip().lower()
    google_oauth = None
    if mode == "google":
        google_oauth = GoogleOAuthSettings(
            client_id=_required("MCP_GOOGLE_CLIENT_ID"),
            client_secret=_required("MCP_GOOGLE_CLIENT_SECRET"),
            base_url=_required("MCP_PUBLIC_URL").rstrip("/"),
            allowed_email=_required("MCP_GOOGLE_ALLOWED_EMAIL").casefold(),
            signing_key=_required("MCP_OAUTH_SIGNING_KEY"),
            client_redirect_uris=tuple(
                value.strip() for value in _required("MCP_OAUTH_CLIENT_REDIRECT_URIS").split(",")
                if value.strip()
            ),
        )
    settings = Settings(
        email=email,
        password=password,
        firebase_api_key=_required("SETTLEUP_FIREBASE_API_KEY"),
        base_url=base_url,
        request_timeout_seconds=float(_int("SETTLEUP_TIMEOUT_SECONDS", 30)),
        token_refresh_margin_seconds=_int("SETTLEUP_TOKEN_REFRESH_MARGIN", 300),
        host=os.environ.get("MCP_HOST", "127.0.0.1").strip(),
        port=_int("MCP_PORT", 8000),
        path=os.environ.get("MCP_PATH", "/mcp").strip(),
        log_level=os.environ.get("LOG_LEVEL", "INFO").strip().upper(),
        auth_token=os.environ.get("MCP_AUTH_TOKEN", "").strip() or None,
        refresh_token=refresh_token,
        auth_mode=mode,
        google_oauth=google_oauth,
    )
    settings.validate_auth()
    return settings


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return load_settings()
