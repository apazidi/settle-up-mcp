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
