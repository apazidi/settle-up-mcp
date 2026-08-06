"""Test the recurring transaction tools."""

from __future__ import annotations

import pytest
from fastmcp.exceptions import ToolError

from tests.conftest import FakeServer, call


def test_list_recurring_describes_each_template() -> None:
    data = call(FakeServer(), "settleup_list_recurring", {"group_id": "group_1"})
    assert data["total"] == 1
    row = data["recurring_transactions"][0]
    assert row["template_id"] == "rec_1"
    assert row["purpose"] == "Rent"
    assert row["amount"] == "800.00"
    assert row["period"] == "monthly"
    assert row["paid_by"] == ["Ann"]
    assert row["run_count"] == 3


def test_add_recurring_writes_the_template_and_the_recurrence() -> None:
    server = FakeServer()
    data = call(
        server,
        "settleup_add_recurring",
        {
            "group_id": "group_1",
            "amount": "800.00",
            "purpose": "Rent",
            "paid_by": [{"member_id": "member_1"}],
            "period": "monthly",
            "monthly_setting": "dayOfMonth",
            "start_date": "2026-01-01T00:00:00+00:00",
        },
    )
    assert data["created"] is True
    assert data["currency_code"] == "EUR"

    stored = server.node(f"recurringTransactions/group_1/{data['template_id']}")
    assert stored["template"]["type"] == "expense"
    assert "dateTime" not in stored["template"]
    assert stored["recurrence"]["period"] == "monthly"
    assert stored["recurrence"]["monthlySetting"] == "dayOfMonth"
    assert stored["recurrence"]["frequency"] == 1
    split = stored["template"]["items"][0]["forWhom"]
    assert [share["memberId"] for share in split] == ["member_1", "member_2"]


def test_add_recurring_needs_a_monthly_setting() -> None:
    with pytest.raises(ToolError) as error:
        call(
            FakeServer(),
            "settleup_add_recurring",
            {
                "group_id": "group_1",
                "amount": "10",
                "purpose": "Rent",
                "paid_by": [{"member_id": "member_1"}],
                "period": "monthly",
            },
        )
    assert "monthly_setting" in str(error.value)


def test_add_recurring_rejects_a_bad_end_date() -> None:
    with pytest.raises(ToolError) as error:
        call(
            FakeServer(),
            "settleup_add_recurring",
            {
                "group_id": "group_1",
                "amount": "10",
                "purpose": "Gym",
                "paid_by": [{"member_id": "member_1"}],
                "period": "weekly",
                "start_date": "2026-02-01T00:00:00+00:00",
                "end_date": "2026-01-01T00:00:00+00:00",
            },
        )
    assert "end_date" in str(error.value)


def test_add_recurring_rejects_an_unknown_member() -> None:
    with pytest.raises(ToolError) as error:
        call(
            FakeServer(),
            "settleup_add_recurring",
            {
                "group_id": "group_1",
                "amount": "10",
                "purpose": "Gym",
                "paid_by": [{"member_id": "member_404"}],
                "period": "daily",
            },
        )
    assert "settleup_list_members" in str(error.value)


def test_delete_recurring_needs_the_confirm_flag() -> None:
    server = FakeServer()
    with pytest.raises(ToolError) as error:
        call(
            server,
            "settleup_delete_recurring",
            {"group_id": "group_1", "template_id": "rec_1", "confirm": False},
        )
    assert "not confirmed" in str(error.value)
    assert server.node("recurringTransactions/group_1/rec_1") is not None


def test_delete_recurring_removes_the_template() -> None:
    server = FakeServer()
    data = call(
        server,
        "settleup_delete_recurring",
        {"group_id": "group_1", "template_id": "rec_1", "confirm": True},
    )
    assert data["deleted"] is True
    assert data["purpose"] == "Rent"
    assert server.node("recurringTransactions/group_1/rec_1") is None


def test_delete_recurring_rejects_an_unknown_template() -> None:
    with pytest.raises(ToolError) as error:
        call(
            FakeServer(),
            "settleup_delete_recurring",
            {"group_id": "group_1", "template_id": "rec_404", "confirm": True},
        )
    assert "settleup_list_recurring" in str(error.value)
