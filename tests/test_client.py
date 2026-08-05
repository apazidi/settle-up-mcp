"""Test the Settle Up REST client."""

from __future__ import annotations

import asyncio

import pytest

from settleup_mcp.client import SettleUpClient, SettleUpError
from tests.conftest import FakeServer, make_settings


def test_the_client_adds_the_token_to_each_request() -> None:
    server = FakeServer()
    seen: list[str] = []
    original = server.handle

    def spy(request):  # type: ignore[no-untyped-def]
        seen.append(str(request.url))
        return original(request)

    server.handle = spy  # type: ignore[method-assign]

    async def run() -> None:
        client = SettleUpClient(make_settings(), server.client())
        groups = await client.list_user_groups("user_1")
        assert set(groups) == {"group_1", "group_2"}
        data_calls = [url for url in seen if "firebaseio" in url]
        assert data_calls
        assert all("auth=id-token-1" in url for url in data_calls)
        await client.aclose()

    asyncio.run(run())


def test_a_forbidden_group_gives_a_clear_message() -> None:
    server = FakeServer()
    server.forbidden_paths.add("members/group_2")

    async def run() -> None:
        client = SettleUpClient(make_settings(), server.client())
        with pytest.raises(SettleUpError) as error:
            await client.list_members("group_2")
        assert "settleup_list_groups" in str(error.value)
        await client.aclose()

    asyncio.run(run())


def test_a_missing_node_gives_an_empty_result() -> None:
    server = FakeServer()

    async def run() -> None:
        client = SettleUpClient(make_settings(), server.client())
        assert await client.list_transactions("group_2") == {}
        assert await client.list_debts("group_2") == []
        await client.aclose()

    asyncio.run(run())
