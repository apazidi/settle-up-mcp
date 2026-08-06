"""Test the transaction tools that read, change, and delete."""

from __future__ import annotations

import pytest
from fastmcp.exceptions import ToolError

from tests.conftest import FakeServer, call


def test_get_expense_gives_all_details() -> None:
    data = call(
        FakeServer(),
        "settleup_get_expense",
        {"group_id": "group_1", "transaction_id": "tx_1"},
    )
    assert data["purpose"] == "Coffee"
    assert data["amount"] == "10.00"
    assert data["type"] == "expense"
    assert [share["name"] for share in data["split_between"]] == ["Ann", "Ben"]


def test_get_expense_rejects_an_unknown_id() -> None:
    with pytest.raises(ToolError) as error:
        call(
            FakeServer(),
            "settleup_get_expense",
            {"group_id": "group_1", "transaction_id": "tx_404"},
        )
    assert "settleup_list_expenses" in str(error.value)


def test_add_transfer_writes_a_transfer() -> None:
    server = FakeServer()
    data = call(
        server,
        "settleup_add_transfer",
        {
            "group_id": "group_1",
            "amount": "5.00",
            "from_member_id": "member_2",
            "to_member_id": "member_1",
            "date_time": "2026-08-05T18:30:00+05:30",
        },
    )
    assert data["created"] is True
    assert data["from_name"] == "Ben"
    assert data["to_name"] == "Ann"

    written = server.created[0]["transaction"]
    assert written["type"] == "transfer"
    assert written["whoPaid"] == [{"memberId": "member_2", "weight": "1"}]
    assert written["items"][0]["forWhom"] == [{"memberId": "member_1", "weight": "1"}]


def test_add_transfer_rejects_the_same_member_twice() -> None:
    with pytest.raises(ToolError) as error:
        call(
            FakeServer(),
            "settleup_add_transfer",
            {
                "group_id": "group_1",
                "amount": "5.00",
                "from_member_id": "member_1",
                "to_member_id": "member_1",
            },
        )
    assert "2 different member ids" in str(error.value)


def test_update_expense_changes_only_the_given_fields() -> None:
    server = FakeServer()
    data = call(
        server,
        "settleup_update_expense",
        {
            "group_id": "group_1",
            "transaction_id": "tx_1",
            "amount": "12.50",
            "purpose": "Tea",
        },
    )
    assert data["updated"] is True
    assert sorted(data["changed_fields"]) == ["amount", "purpose"]

    stored = server.node("transactions/group_1/tx_1")
    assert stored["purpose"] == "Tea"
    assert stored["items"][0]["amount"] == "12.50"
    assert stored["category"] == "\u2615"
    assert len(stored["items"][0]["forWhom"]) == 2


def test_update_expense_rejects_an_empty_request() -> None:
    with pytest.raises(ToolError) as error:
        call(
            FakeServer(),
            "settleup_update_expense",
            {"group_id": "group_1", "transaction_id": "tx_1"},
        )
    assert "changes no field" in str(error.value)


def test_update_expense_rejects_an_unknown_member() -> None:
    with pytest.raises(ToolError) as error:
        call(
            FakeServer(),
            "settleup_update_expense",
            {
                "group_id": "group_1",
                "transaction_id": "tx_1",
                "paid_by": [{"member_id": "member_404"}],
            },
        )
    assert "settleup_list_members" in str(error.value)


def test_delete_expense_needs_the_confirm_flag() -> None:
    server = FakeServer()
    with pytest.raises(ToolError) as error:
        call(
            server,
            "settleup_delete_expense",
            {"group_id": "group_1", "transaction_id": "tx_1", "confirm": False},
        )
    assert "not confirmed" in str(error.value)
    assert server.node("transactions/group_1/tx_1") is not None


def test_delete_expense_removes_the_transaction() -> None:
    server = FakeServer()
    data = call(
        server,
        "settleup_delete_expense",
        {"group_id": "group_1", "transaction_id": "tx_1", "confirm": True},
    )
    assert data["deleted"] is True
    assert data["amount"] == "10.00"
    assert server.node("transactions/group_1/tx_1") is None


def test_summarize_spending_groups_by_category() -> None:
    data = call(
        FakeServer(),
        "settleup_summarize_spending",
        {"group_id": "group_1", "group_by": "category"},
    )
    assert data["transaction_count"] == 1
    assert data["grand_total"] == "10.00"
    assert data["rows"] == [{"key": "\u2615 Coffee and tea", "total": "10.00"}]


def test_summarize_spending_groups_by_member() -> None:
    data = call(
        FakeServer(),
        "settleup_summarize_spending",
        {"group_id": "group_1", "group_by": "member"},
    )
    totals = {row["key"]: row["total"] for row in data["rows"]}
    assert totals == {"Ann": "5.00", "Ben": "5.00"}


def test_summarize_spending_uses_the_time_window() -> None:
    data = call(
        FakeServer(),
        "settleup_summarize_spending",
        {"group_id": "group_1", "since": "2030-01-01T00:00:00Z"},
    )
    assert data["transaction_count"] == 0
    assert data["grand_total"] == "0"


def test_summarize_spending_rejects_a_bad_window() -> None:
    with pytest.raises(ToolError):
        call(
            FakeServer(),
            "settleup_summarize_spending",
            {
                "group_id": "group_1",
                "since": "2030-01-01T00:00:00Z",
                "until": "2020-01-01T00:00:00Z",
            },
        )
