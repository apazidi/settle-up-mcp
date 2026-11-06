"""Sign in to Firebase. Refresh the ID token before it expires."""

from __future__ import annotations

import asyncio
import logging
import time

import httpx

from settleup_mcp.config import REFRESH_URL, SIGN_IN_URL, Settings

logger = logging.getLogger(__name__)


class AuthError(RuntimeError):
    """The server cannot get a valid Firebase ID token."""


class FirebaseAuth:
    """Hold the Firebase tokens for one Settle Up user.

    The class makes 2 plain HTTPS calls. It does not use the Firebase SDK.
    """

    def __init__(self, settings: Settings, http_client: httpx.AsyncClient) -> None:
        self._settings = settings
        self._http = http_client
        self._lock = asyncio.Lock()
        self._id_token: str | None = None
        self._refresh_token: str | None = settings.refresh_token
        self._user_id: str | None = None
        self._expires_at: float = 0.0

    @property
    def user_id(self) -> str | None:
        """Give the Firebase user id, or None before the first sign-in."""
        return self._user_id

    async def get_id_token(self) -> str:
        """Give a valid ID token. Sign in or refresh the token if necessary."""
        async with self._lock:
            if self._id_token and not self._is_expired():
                return self._id_token
            if self._refresh_token:
                try:
                    await self._refresh()
                    return self._id_token or ""
                except AuthError:
                    if self._settings.refresh_token:
                        # An explicitly configured OAuth session must never
                        # fall back to another identity via email/password.
                        raise AuthError(
                            "The Settle Up session could not be refreshed. Retry, or "
                            "sign in to Settle Up again and replace SETTLEUP_REFRESH_TOKEN."
                        ) from None
                    logger.warning("The token refresh failed; retrying password sign-in.")
            await self._sign_in()
            return self._id_token or ""

    async def get_user_id(self) -> str:
        """Give the Firebase user id. Sign in first if necessary."""
        await self.get_id_token()
        if not self._user_id:
            raise AuthError("The sign-in gave no user id. Check the Settle Up account.")
        return self._user_id

    async def invalidate(self) -> None:
        """Forget the ID token. The next call signs in or refreshes again."""
        async with self._lock:
            self._id_token = None
            self._expires_at = 0.0

    def _is_expired(self) -> bool:
        margin = self._settings.token_refresh_margin_seconds
        return time.monotonic() >= (self._expires_at - margin)

    def _store(self, id_token: str, refresh_token: str, expires_in: str) -> None:
        try:
            lifetime = float(expires_in)
        except (TypeError, ValueError):
            lifetime = 3600.0
        self._id_token = id_token
        self._refresh_token = refresh_token or self._refresh_token
        self._expires_at = time.monotonic() + lifetime

    async def _sign_in(self) -> None:
        """Exchange the email and the password for the 2 tokens."""
        if not self._settings.email or not self._settings.password:
            raise AuthError("Configure SETTLEUP_REFRESH_TOKEN or Settle Up email/password.")
        payload: dict[str, object] = {
            "email": self._settings.email,
            "password": self._settings.password,
            "returnSecureToken": True,
        }
        data = await self._post(
            SIGN_IN_URL,
            params={"key": self._settings.firebase_api_key},
            json=payload,
            action="sign in",
        )
        self._user_id = data.get("localId")
        self._store(
            data.get("idToken", ""),
            data.get("refreshToken", ""),
            data.get("expiresIn", "3600"),
        )
        if not self._id_token:
            raise AuthError("The sign-in gave no ID token. Check the credentials.")
        logger.info("The server signed in to Settle Up as user %s.", self._user_id)

    async def _refresh(self) -> None:
        """Exchange the refresh token for a new ID token."""
        data = await self._post(
            REFRESH_URL,
            params={"key": self._settings.firebase_api_key},
            data={
                "grant_type": "refresh_token",
                "refresh_token": self._refresh_token or "",
            },
            action="refresh the token",
        )
        self._user_id = data.get("user_id", self._user_id)
        self._store(
            data.get("id_token", ""),
            data.get("refresh_token", ""),
            data.get("expires_in", "3600"),
        )
        if not self._id_token:
            raise AuthError("The refresh gave no ID token.")
        logger.debug("The server refreshed the Settle Up ID token.")

    async def _post(
        self,
        url: str,
        *,
        action: str,
        params: dict[str, str],
        json: dict[str, object] | None = None,
        data: dict[str, str] | None = None,
    ) -> dict[str, str]:
        try:
            response = await self._http.post(url, params=params, json=json, data=data)
        except httpx.HTTPError:
            raise AuthError(
                f"The server cannot reach Firebase to {action}. "
                "Check the network."
            ) from None

        if response.status_code >= 400:
            raise AuthError(
                f"Firebase refused the request to {action}. "
                f"Status {response.status_code}. "
                f"Reason: {_firebase_reason(response)}. "
                "Check the configured Settle Up credentials: SETTLEUP_EMAIL, "
                "SETTLEUP_PASSWORD or SETTLEUP_REFRESH_TOKEN, and SETTLEUP_FIREBASE_API_KEY."
            )
        return response.json()


def _firebase_reason(response: httpx.Response) -> str:
    """Give the short Firebase error text. Never give a secret."""
    try:
        body = response.json()
    except ValueError:
        return "unknown"
    error = body.get("error")
    if isinstance(error, dict):
        return str(error.get("message", "unknown"))
    if isinstance(error, str):
        return error
    return "unknown"
