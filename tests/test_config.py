"""Configuration must fail closed before starting a listener."""

from dataclasses import replace

import pytest

from settleup_mcp.config import ConfigError, GoogleOAuthSettings, load_settings
from tests.conftest import make_settings


@pytest.fixture
def clean_config(monkeypatch):
    import os
    for name in list(os.environ):
        if name.startswith(("SETTLEUP_", "MCP_")):
            monkeypatch.delenv(name)
    monkeypatch.setenv("SETTLEUP_FIREBASE_API_KEY", "fake-api-key")
    monkeypatch.setenv("SETTLEUP_REFRESH_TOKEN", "fake-refresh-token")
    monkeypatch.setenv("MCP_AUTH_TOKEN", "fake-mcp-token")
    return monkeypatch


def test_refresh_session_does_not_need_a_password(clean_config):
    settings = load_settings()
    assert settings.password == ""
    assert settings.refresh_token == "fake-refresh-token"
    assert settings.host == "127.0.0.1"


def test_missing_token_does_not_disable_authentication(clean_config):
    clean_config.delenv("MCP_AUTH_TOKEN")
    with pytest.raises(ConfigError, match="requires MCP_AUTH_TOKEN"):
        load_settings()


@pytest.mark.parametrize("mode", ["typo", "oauth", ""])
def test_unknown_modes_fail_closed(clean_config, mode):
    clean_config.setenv("MCP_AUTH_MODE", mode)
    with pytest.raises(ConfigError, match="must be token, google, or none"):
        load_settings()


def test_anonymous_mode_requires_explicit_loopback(clean_config):
    clean_config.delenv("MCP_AUTH_TOKEN")
    clean_config.setenv("MCP_AUTH_MODE", "none")
    assert load_settings().auth_mode == "none"
    clean_config.setenv("MCP_HOST", "0.0.0.0")
    with pytest.raises(ConfigError, match="loopback"):
        load_settings()


def test_missing_firebase_credentials_fail(clean_config):
    clean_config.delenv("SETTLEUP_REFRESH_TOKEN")
    with pytest.raises(ConfigError, match="SETTLEUP_REFRESH_TOKEN"):
        load_settings()


def test_password_login_still_works(clean_config):
    clean_config.delenv("SETTLEUP_REFRESH_TOKEN")
    clean_config.setenv("SETTLEUP_EMAIL", "owner@example.com")
    clean_config.setenv("SETTLEUP_PASSWORD", " pass with spaces ")
    assert load_settings().password == " pass with spaces "


def test_untrusted_database_origin_rejected(clean_config):
    clean_config.setenv("SETTLEUP_BASE_URL", "https://example.com")
    with pytest.raises(ConfigError, match="sandbox or live"):
        load_settings()


def test_google_configuration_and_secrets_repr(clean_config):
    clean_config.delenv("MCP_AUTH_TOKEN")
    clean_config.setenv("MCP_AUTH_MODE", "google")
    for name, value in {
        "MCP_GOOGLE_CLIENT_ID": "client.apps.googleusercontent.com",
        "MCP_GOOGLE_CLIENT_SECRET": "fake-client-secret",
        "MCP_GOOGLE_ALLOWED_EMAIL": "OWNER@example.com",
        "MCP_PUBLIC_URL": "https://mcp.example.com",
        "MCP_OAUTH_SIGNING_KEY": "s" * 40,
        "MCP_OAUTH_CLIENT_REDIRECT_URIS": "https://chatgpt.com/connector/oauth/test",
    }.items():
        clean_config.setenv(name, value)
    settings = load_settings()
    assert settings.google_oauth.allowed_email == "owner@example.com"
    for secret in ("fake-client-secret", "fake-api-key", "fake-refresh-token", "s" * 40):
        assert secret not in repr(settings)
    assert "secret-password" not in repr(replace(settings, password="secret-password"))
    clean_config.setenv("MCP_AUTH_TOKEN", "ambiguous-secret")
    with pytest.raises(ConfigError, match="Unset MCP_AUTH_TOKEN"):
        load_settings()


@pytest.mark.parametrize("origin", [
    "http://mcp.example.com", "https://user:pass@mcp.example.com",
    "https://mcp.example.com/path", "https://mcp.example.com?query=1",
])
def test_public_origin_requires_https_origin(origin):
    with pytest.raises(ConfigError, match="HTTPS origin"):
        google_config(base_url=origin)


def google_config(**overrides):
    values = {
        "client_id": "client.apps.googleusercontent.com",
        "client_secret": "fake-google-secret",
        "base_url": "https://mcp.example.com",
        "allowed_email": "owner@example.com",
        "signing_key": "x" * 40,
        "client_redirect_uris": ("https://chatgpt.com/connector/oauth/test",),
    }
    values.update(overrides)
    return GoogleOAuthSettings(**values)


@pytest.mark.parametrize("callbacks", [
    (), ("https://*",), ("http://example.com/callback",),
    ("https://example.com/callback#fragment",),
])
def test_oauth_callbacks_must_be_explicit_https_urls(callbacks):
    with pytest.raises(ConfigError):
        google_config(client_redirect_uris=callbacks)


def test_google_owner_and_signing_key_are_required():
    with pytest.raises(ConfigError, match="owner"):
        google_config(allowed_email="")
    with pytest.raises(ConfigError, match="32 characters"):
        google_config(signing_key="short")
