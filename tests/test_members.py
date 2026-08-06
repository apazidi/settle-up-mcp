"""Test the member tools."""

from __future__ import annotations

import pytest
from fastmcp.exceptions import ToolError

from tests.conftest import FakeServer, call


def test_add_member_writes_the_member() -> None:
    server = FakeServer()
    data = call(
        server,
        "settleup_add_member",
        {"group_id": "group_1", "name": "Dan", "default_weight": "2"},
    )
    assert data["created"] is True
    assert data["name"] == "Dan"

    stored = server.node(f"members/group_1/{data['member_id']}")
    assert stored == {"name": "Dan", "active": True, "defaultWeight": "2"}


def test_add_member_rejects_a_name_that_exists() -> None:
    with pytest.raises(ToolError) as error:
        call(FakeServer(), "settleup_add_member", {"group_id": "group_1", "name": "ann"})
    assert "settleup_update_member" in str(error.value)


def test_update_member_changes_only_the_given_fields() -> None:
    server = FakeServer()
    data = call(
        server,
        "settleup_update_member",
        {"group_id": "group_1", "member_id": "member_2", "name": "Benjamin"},
    )
    assert data["updated"] is True
    assert data["changed_fields"] == ["name"]

    stored = server.node("members/group_1/member_2")
    assert stored["name"] == "Benjamin"
    assert stored["active"] is True
    assert stored["defaultWeight"] == "1"


def test_update_member_rejects_an_empty_request() -> None:
    with pytest.raises(ToolError) as error:
        call(
            FakeServer(),
            "settleup_update_member",
            {"group_id": "group_1", "member_id": "member_2"},
        )
    assert "changes no field" in str(error.value)


def test_update_member_rejects_an_unknown_member() -> None:
    with pytest.raises(ToolError) as error:
        call(
            FakeServer(),
            "settleup_update_member",
            {"group_id": "group_1", "member_id": "member_404", "name": "X"},
        )
    assert "settleup_list_members" in str(error.value)


def test_deactivate_member_sets_the_member_to_not_active() -> None:
    server = FakeServer()
    data = call(
        server,
        "settleup_deactivate_member",
        {"group_id": "group_1", "member_id": "member_2"},
    )
    assert data["updated"] is True
    assert data["active"] is False
    assert server.node("members/group_1/member_2")["active"] is False


def test_deactivate_member_reports_a_member_that_is_not_active() -> None:
    server = FakeServer()
    data = call(
        server,
        "settleup_deactivate_member",
        {"group_id": "group_1", "member_id": "member_9"},
    )
    assert data["updated"] is False
    assert server.writes_to("PATCH", "members/group_1/member_9") == []
