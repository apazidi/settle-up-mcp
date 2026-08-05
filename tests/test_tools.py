"""Test each tool through an in-memory MCP client."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

from settleup_mcp.client import SettleUpClient
from settleup_mcp.server import create_server
from tests.conftest import FakeServer, make_settings


def call(server: FakeServer, tool: str, request: dict[str, Any]) -> Any:
    """Call one tool. Give the structured result."""

    async def run() -> Any:
        api = SettleUpClient(make_settings(), server.client())
        mcp = create_server(make_settings(), api)
        async with Client(mcp) as client:
            result = await client.call_tool(tool, {"request": request})
        return result.data

    return asyncio.run(run())


def test_the_server_lists_each_tool() -> None:
    async def run() -> list[str]:
        api = SettleUpClient(make_settings(), FakeServer().client())
        mcp = create_server(make_settings(), api)
        async with Client(mcp) as client:
            tools = await client.list_tools()
        return sorted(tool.name for tool in tools)

    assert asyncio.run(run()) == [
        "settleup_add_expense",
        "settleup_get_balances",
        "settleup_list_expenses",
        "settleup_list_groups",
        "settleup_list_members",
    ]


def test_list_groups_sorts_and_paginates() -> None:
    server = FakeServer()
    data = call(server, "settleup_list_groups", {"limit": 1, "offset": 0})
    assert data["total"] == 2
    assert data["has_more"] is True
    assert data["groups"][0]["group_id"] == "group_2"
    assert data["groups"][0]["name"] == "Trip"
    assert data["groups"][0]["your_member_id"] == "member_3"

    page_2 = call(server, "settleup_list_groups", {"limit": 1, "offset": 1})
    assert page_2["groups"][0]["group_id"] == "group_1"
    assert page_2["has_more"] is False


def test_list_members_can_hide_the_inactive_members() -> None:
    server = FakeServer()
    everybody = call(server, "settleup_list_members", {"group_id": "group_1"})
    assert everybody["total"] == 3

    active = call(
        server, "settleup_list_members", {"group_id": "group_1", "only_active": True}
    )
    assert [row["name"] for row in active["members"]] == ["Ann", "Ben"]


def test_get_balances_gives_the_debts_and_the_net_balance() -> None:
    data = call(FakeServer(), "settleup_get_balances", {"group_id": "group_1"})
    assert data["currency_code"] == "EUR"
    assert data["settled"] is False
    assert data["debts"] == [
        {
            "from_member_id": "member_2",
            "from_name": "Ben",
            "to_member_id": "member_1",
            "to_name": "Ann",
            "amount": "5.00",
        }
    ]
    balances = {row["member_id"]: row["balance"] for row in data["net_balances"]}
    assert balances["member_1"] == "5.00"
    assert balances["member_2"] == "-5.00"


def test_list_expenses_filters_and_sorts() -> None:
    server = FakeServer()
    newest = call(server, "settleup_list_expenses", {"group_id": "group_1"})
    assert [row["transaction_id"] for row in newest["transactions"]] == [
        "tx_2",
        "tx_1",
    ]

    only_expenses = call(
        server,
        "settleup_list_expenses",
        {"group_id": "group_1", "transaction_type": "expense"},
    )
    assert only_expenses["total"] == 1
    row = only_expenses["transactions"][0]
    assert row["purpose"] == "Coffee"
    assert row["amount"] == "10.00"
    assert row["paid_by"][0]["name"] == "Ann"

    oldest = call(
        server,
        "settleup_list_expenses",
        {"group_id": "group_1", "newest_first": False},
    )
    assert oldest["transactions"][0]["transaction_id"] == "tx_1"


def test_add_expense_splits_between_the_active_members() -> None:
    server = FakeServer()
    data = call(
        server,
        "settleup_add_expense",
        {
            "group_id": "group_1",
            "amount": "30.00",
            "purpose": "Dinner",
            "paid_by": [{"member_id": "member_1"}],
            "date_time": "2026-08-05T18:30:00+05:30",
        },
    )
    assert data["created"] is True
    assert data["transaction_id"] == "tx_new"

    written = server.created[0]["transaction"]
    assert written["type"] == "expense"
    assert written["currencyCode"] == "EUR"
    assert written["timezone"] == "+05:30"
    assert written["whoPaid"] == [{"memberId": "member_1", "weight": "1"}]
    assert written["items"][0]["amount"] == "30.00"
    assert [share["memberId"] for share in written["items"][0]["forWhom"]] == [
        "member_1",
        "member_2",
    ]


def test_add_expense_rejects_an_unknown_member() -> None:
    with pytest.raises(ToolError) as error:
        call(
            FakeServer(),
            "settleup_add_expense",
            {
                "group_id": "group_1",
                "amount": "10",
                "purpose": "Tea",
                "paid_by": [{"member_id": "member_404"}],
            },
        )
    assert "settleup_list_members" in str(error.value)


def test_add_expense_rejects_an_amount_that_is_not_a_number() -> None:
    with pytest.raises(ToolError):
        call(
            FakeServer(),
            "settleup_add_expense",
            {
                "group_id": "group_1",
                "amount": "ten euro",
                "purpose": "Tea",
                "paid_by": [{"member_id": "member_1"}],
            },
        )


def test_add_expense_rejects_another_currency() -> None:
    with pytest.raises(ToolError) as error:
        call(
            FakeServer(),
            "settleup_add_expense",
            {
                "group_id": "group_1",
                "amount": "10",
                "purpose": "Tea",
                "currency_code": "usd",
                "paid_by": [{"member_id": "member_1"}],
            },
        )
    assert "EUR" in str(error.value)
