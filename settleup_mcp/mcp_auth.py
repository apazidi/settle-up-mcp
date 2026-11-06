"""MCP client authentication, separate from the Settle Up Firebase session."""

from __future__ import annotations

import logging

from fastmcp.server.auth import AuthProvider
from fastmcp.server.auth.auth import AccessToken
from fastmcp.server.auth.providers.google import GoogleProvider
from fastmcp.server.auth.providers.jwt import StaticTokenVerifier

from settleup_mcp.config import GoogleOAuthSettings, Settings

logger = logging.getLogger(__name__)


class OwnerGoogleProvider(GoogleProvider):
    """Use FastMCP OAuth/PKCE and authorize only the configured account owner."""

    def __init__(self, config: GoogleOAuthSettings) -> None:
        self._allowed_email = config.allowed_email.strip().casefold()
        self._google_client_id = config.client_id
        super().__init__(
            client_id=config.client_id,
            client_secret=config.client_secret,
            base_url=config.base_url,
            required_scopes=["openid", "https://www.googleapis.com/auth/userinfo.email"],
            jwt_signing_key=config.signing_key,
            allowed_client_redirect_uris=list(config.client_redirect_uris),
            require_authorization_consent=True,
        )

    async def load_access_token(self, token: str) -> AccessToken | None:
        # FastMCP validates its own signature/audience/expiry, resolves the
        # upstream session and verifies it with Google before we inspect claims.
        verified = await super().load_access_token(token)
        if verified is None:
            return None
        claims = verified.claims
        email = claims.get("email")
        email_verified = claims.get("email_verified")
        if (
            not isinstance(email, str)
            or email.strip().casefold() != self._allowed_email
            or (email_verified is not True and email_verified != "true")
            or claims.get("aud") != self._google_client_id
        ):
            logger.warning("Rejected an OAuth identity outside the configured owner policy.")
            return None
        return verified


def build_auth(settings: Settings) -> AuthProvider | None:
    """Fail closed on missing/ambiguous authentication configuration."""
    settings.validate_auth()
    if settings.auth_mode == "google":
        assert settings.google_oauth is not None
        return OwnerGoogleProvider(settings.google_oauth)
    if settings.auth_mode == "token":
        assert settings.auth_token is not None
        return StaticTokenVerifier(
            tokens={settings.auth_token: {"client_id": "settleup-agent", "scopes": []}}
        )
    logger.warning("Authentication disabled explicitly for loopback development.")
    return None
