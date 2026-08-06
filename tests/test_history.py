"""Test the history tools, the category tool, and the permission tool."""

from __future__ import annotations

from tests.conftest import USER_ID, FakeServer, call


def test_list_changes_gives_the_newest_first() -> None:
    data = call(FakeServer(), "settleup_list_changes", {"group_id": "group_1"})
    assert data["total"] == 2
    assert [row["change_id"] for row in data["changes"]] == ["change_2", "change_1"]
    assert data["changes"][0]["entity"] == "member"
    assert data["changes"][0]["by_user_id"] == "user_2"


def test_list_changes_can_give_the_oldest_first() -> None:
    data = call(
        FakeServer(),
        "settleup_list_changes",
        {"group_id": "group_1", "newest_first": False},
    )
    assert [row["change_id"] for row in data["changes"]] == ["change_1", "change_2"]


def test_list_categories_counts_the_use_of_each_emoji() -> None:
    data = call(FakeServer(), "settleup_list_categories", {"group_id": "group_1"})
    rows = {row["emoji"]: row for row in data["categories"]}
    assert rows["\u2615"]["name"] == "Coffee and tea"
    assert rows["\u2615"]["used_count"] == 1
    assert rows["\U0001f355"]["used_count"] == 0


def test_list_permissions_names_each_level() -> None:
    data = call(FakeServer(), "settleup_list_permissions", {"group_id": "group_1"})
    assert data["your_user_id"] == USER_ID
    assert data["total"] == 2
    first = data["permissions"][0]
    assert first["user_id"] == USER_ID
    assert first["level_name"] == "owner"
    assert first["is_you"] is True
    assert data["permissions"][1]["level_name"] == "read and write"


def test_recalculate_debts_runs_the_server_task() -> None:
    server = FakeServer()
    data = call(server, "settleup_recalculate_debts", {"group_id": "group_1"})
    assert data["status"] == "ok"
    task = server.node(f"serverTasks/calculateGroupsDebts/{data['task_id']}")
    assert task["request"]["request"] == {"groupId": "group_1"}
