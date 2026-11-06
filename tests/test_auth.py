"""Test the Firebase sign-in and the token refresh."""

from __future__ import annotations

import asyncio

import httpx
import pytest

from settleup_mcp.auth import AuthError, FirebaseAuth
from tests.conftest import FakeServer, make_settings


def test_sign_in_once_then_reuse_the_token() -> None:
    server = FakeServer()

    async def run() -> None:
        async with server.client() as http:
            auth = FirebaseAuth(make_settings(), http)
            first = await auth.get_id_token()
            second = await auth.get_id_token()
            assert first == second == "id-token-1"
            assert server.sign_in_count == 1
            assert server.refresh_count == 0
            assert auth.user_id == "user_1"

    asyncio.run(run())


def test_refresh_before_the_token_expires() -> None:
    server = FakeServer()
    server.expires_in = "60"  # Less than the 300 second margin.

    async def run() -> None:
        async with server.client() as http:
            auth = FirebaseAuth(make_settings(), http)
            assert await auth.get_id_token() == "id-token-1"
            assert await auth.get_id_token() == "refreshed-token-1"
            assert server.sign_in_count == 1
            assert server.refresh_count == 1

    asyncio.run(run())


def test_bad_credentials_give_a_clear_message() -> None:
    def handle(_: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": {"message": "INVALID_PASSWORD"}})

    async def run() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
            auth = FirebaseAuth(make_settings(), http)
            with pytest.raises(AuthError) as error:
                await auth.get_id_token()
            message = str(error.value)
            assert "INVALID_PASSWORD" in message
            assert "SETTLEUP_EMAIL" in message
            assert "secret" not in message

    asyncio.run(run())


def test_oauth_refresh_token_bootstraps_without_password():
    server = FakeServer()
    async def run():
        async with server.client() as http:
            auth = FirebaseAuth(make_settings(email="", password="", refresh_token="oauth-session"), http)
            assert await auth.get_id_token() == "refreshed-token-1"
            assert await auth.get_user_id() == "user_1"
            assert server.refresh_count == 1
            assert server.sign_in_count == 0
    asyncio.run(run())


def test_revoked_oauth_session_never_falls_back_to_password():
    requests = []
    def handle(request):
        requests.append(request)
        return httpx.Response(400, json={"error": {"message": "TOKEN_EXPIRED"}})
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
            auth = FirebaseAuth(make_settings(refresh_token="private-session"), http)
            with pytest.raises(AuthError, match="SETTLEUP_REFRESH_TOKEN") as error:
                await auth.get_id_token()
            assert "private-session" not in str(error.value)
        assert len(requests) == 1
        assert requests[0].url.host == "securetoken.googleapis.com"
    asyncio.run(run())


def test_rotated_refresh_token_is_used_for_next_refresh():
    tokens = []
    def handle(request):
        from urllib.parse import parse_qs
        tokens.append(parse_qs(request.content.decode())["refresh_token"][0])
        return httpx.Response(200, json={
            "id_token": "id-" + str(len(tokens)), "refresh_token": "rotated-session",
            "user_id": "user_1", "expires_in": "3600",
        })
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
            auth = FirebaseAuth(make_settings(refresh_token="initial-session"), http)
            await auth.get_id_token()
            await auth.invalidate()
            await auth.get_id_token()
        assert tokens == ["initial-session", "rotated-session"]
    asyncio.run(run())


def test_network_errors_do_not_expose_url_credentials():
    def handle(request):
        raise httpx.ConnectError("request with private-key in URL", request=request)
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
            auth = FirebaseAuth(make_settings(firebase_api_key="private-key"), http)
            with pytest.raises(AuthError) as error:
                await auth.get_id_token()
            assert "private-key" not in str(error.value)
    asyncio.run(run())
