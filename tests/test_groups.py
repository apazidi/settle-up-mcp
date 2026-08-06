"""Test the group tools that read details and change the group."""

from __future__ import annotations

import pytest
from fastmcp.exceptions import ToolError

from tests.conftest import USER_ID, FakeServer, call


def test_get_group_gives_the_settings_and_the_counts() -> None:
    data = call(FakeServer(), "settleup_get_group", {"group_id": "group_1"})
    assert data["name"] == "Flat"
    assert data["currency_code"] == "EUR"
    assert data["member_count"] == 3
    assert data["active_member_count"] == 2
    assert data["transaction_count"] == 2


def test_get_group_rejects_an_unknown_group() -> None:
    with pytest.raises(ToolError) as error:
        call(FakeServer(), "settleup_get_group", {"group_id": "group_404"})
    assert "settleup_list_groups" in str(error.value)


def test_create_group_makes_the_5_writes() -> None:
    server = FakeServer()
    data = call(
        server,
        "settleup_create_group",
        {
            "name": "Holiday",
            "currency_code": "inr",
            "your_member_name": "Ann",
        },
    )
    group_id = data["group_id"]
    assert data["created"] is True
    assert data["currency_code"] == "INR"

    assert server.node(f"groups/{group_id}")["name"] == "Holiday"
    assert server.node(f"permissions/{group_id}/{USER_ID}") == {"level": 30}
    assert server.node(f"members/{group_id}/{data['your_member_id']}")["name"] == "Ann"
    assert server.node(f"userGroups/{USER_ID}/{group_id}") == {
        "member": data["your_member_id"],
        "order": 0,
    }
    assert server.node(f"users/{USER_ID}/currentTabId") == group_id


def test_update_group_changes_the_name() -> None:
    server = FakeServer()
    data = call(
        server,
        "settleup_update_group",
        {"group_id": "group_1", "name": "Flat share"},
    )
    assert data["updated"] is True
    assert server.node("groups/group_1")["name"] == "Flat share"
    assert server.node("groups/group_1")["convertedToCurrency"] == "EUR"


def test_update_group_rejects_an_empty_request() -> None:
    with pytest.raises(ToolError) as error:
        call(FakeServer(), "settleup_update_group", {"group_id": "group_1"})
    assert "changes no field" in str(error.value)


def test_get_invite_link_switches_the_link_on() -> None:
    server = FakeServer()
    data = call(server, "settleup_get_invite_link", {"group_id": "group_1"})
    assert data["activated_now"] is True
    assert data["invite_link"].endswith("group_1")
    assert server.node("groups/group_1")["inviteLinkActive"] is True


def test_get_invite_link_keeps_a_link_that_is_on() -> None:
    server = FakeServer()
    data = call(server, "settleup_get_invite_link", {"group_id": "group_2"})
    assert data["activated_now"] is False
    assert server.writes_to("PATCH", "groups/group_2") == []


def test_change_currency_runs_the_server_task() -> None:
    server = FakeServer()
    data = call(
        server,
        "settleup_change_currency",
        {"group_id": "group_1", "target_currency": "usd"},
    )
    assert data["changed"] is True
    assert data["from_currency"] == "EUR"
    assert data["to_currency"] == "USD"
    task = server.node(f"serverTasks/currencyChange/{data['task_id']}")
    assert task["request"]["request"] == {
        "groupId": "group_1",
        "targetCurrency": "USD",
    }


def test_change_currency_skips_the_same_currency() -> None:
    server = FakeServer()
    data = call(
        server,
        "settleup_change_currency",
        {"group_id": "group_1", "target_currency": "EUR"},
    )
    assert data["changed"] is False
    assert server.node("serverTasks") == {}


def test_change_currency_reports_a_task_error() -> None:
    server = FakeServer()
    server.task_code = "unknownCurrency"
    with pytest.raises(ToolError) as error:
        call(
            server,
            "settleup_change_currency",
            {"group_id": "group_1", "target_currency": "USD"},
        )
    assert "unknownCurrency" in str(error.value)


def test_delete_group_needs_the_confirm_flag() -> None:
    server = FakeServer()
    with pytest.raises(ToolError) as error:
        call(
            server,
            "settleup_delete_group",
            {"group_id": "group_1", "confirm": False},
        )
    assert "not confirmed" in str(error.value)
    assert server.node("serverTasks") == {}


def test_delete_group_runs_the_server_task() -> None:
    server = FakeServer()
    data = call(
        server, "settleup_delete_group", {"group_id": "group_1", "confirm": True}
    )
    assert data["deleted"] is True
    assert data["name"] == "Flat"
    assert data["deleted_transaction_count"] == 2
    assert server.node(f"serverTasks/deleteGroup/{data['task_id']}") is not None
