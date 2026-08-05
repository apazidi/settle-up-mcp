"""The tools that read and write transactions."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from settleup_mcp.client import SettleUpError
from settleup_mcp.models import AddExpenseRequest, ListExpensesRequest, MemberShare
from settleup_mcp.tools.common import (
    READ_ONLY,
    WRITE,
    format_amount,
    member_ids_of,
    paginate,
    timezone_offset,
    to_iso,
    to_millis,
    transaction_total,
)

if TYPE_CHECKING:  # pragma: no cover
    from fastmcp import FastMCP

    from settleup_mcp.client import SettleUpClient


def register(mcp: "FastMCP", client: "SettleUpClient") -> None:
    """Add the transaction tools to the server."""

    @mcp.tool(
        name="settleup_list_expenses",
        title="List the transactions of a Settle Up group",
        annotations=READ_ONLY,
    )
    async def settleup_list_expenses(request: ListExpensesRequest) -> dict[str, Any]:
        """List the transactions of one group.

        A transaction is an expense or a transfer. An income is an expense
        with a negative amount.
        """
        transactions, members = await asyncio.gather(
            client.list_transactions(request.group_id),
            client.list_members(request.group_id),
        )
        names = {
            member_id: (member or {}).get("name")
            for member_id, member in members.items()
            if isinstance(member, dict)
        }

        rows = []
        for transaction_id, transaction in transactions.items():
            if not isinstance(transaction, dict):
                continue
            kind = str(transaction.get("type", "expense"))
            if request.transaction_type != "all" and kind != request.transaction_type:
                continue
            if request.member_id and request.member_id not in member_ids_of(
                transaction
            ):
                continue
            rows.append(_describe(transaction_id, transaction, names))

        rows.sort(
            key=lambda row: row["date_time_millis"], reverse=request.newest_first
        )

        page = paginate(rows, request.limit, request.offset)
        return {
            "group_id": request.group_id,
            "total": page["total"],
            "limit": page["limit"],
            "offset": page["offset"],
            "count": page["count"],
            "has_more": page["has_more"],
            "transactions": page["items"],
        }

    @mcp.tool(
        name="settleup_add_expense",
        title="Add an expense to a Settle Up group",
        annotations=WRITE,
    )
    async def settleup_add_expense(request: AddExpenseRequest) -> dict[str, Any]:
        """Add one expense to a group. This tool changes the group data.

        Give the group id, the amount, the purpose, and the payer. Leave
        split_between empty to split the cost between all active members.
        """
        try:
            moment = request.parsed_date_time()
        except ValueError as error:
            raise SettleUpError(str(error)) from error

        group, members = await asyncio.gather(
            client.get_group(request.group_id),
            client.list_members(request.group_id),
        )
        if not members:
            raise SettleUpError(
                f"The group {request.group_id} has no members. "
                "Use settleup_list_groups to find a correct group id."
            )

        shares = request.split_between or _default_split(members)
        if not shares:
            raise SettleUpError(
                f"The group {request.group_id} has no active member. "
                "Give split_between with at least 1 member id."
            )

        _check_members(members, request.paid_by, shares)

        currency = request.currency_code or (group or {}).get("convertedToCurrency")
        if not currency:
            raise SettleUpError(
                "The group has no currency. Give currency_code, for example 'EUR'."
            )
        group_currency = (group or {}).get("convertedToCurrency")
        if group_currency and currency != group_currency:
            raise SettleUpError(
                f"The group uses {group_currency}. This tool cannot add an "
                f"expense in {currency}, because it has no exchange rate. "
                f"Give the amount in {group_currency}."
            )

        transaction: dict[str, Any] = {
            "type": "expense",
            "purpose": request.purpose,
            "currencyCode": currency,
            "dateTime": to_millis(moment),
            "timezone": timezone_offset(moment),
            "fixedExchangeRate": False,
            "whoPaid": [_share(payer) for payer in request.paid_by],
            "items": [
                {
                    "amount": request.amount,
                    "forWhom": [_share(share) for share in shares],
                }
            ],
        }
        if request.category:
            transaction["category"] = request.category

        transaction_id = await client.create_transaction(
            request.group_id, transaction
        )
        names = {
            member_id: (member or {}).get("name")
            for member_id, member in members.items()
            if isinstance(member, dict)
        }
        return {
            "created": True,
            "group_id": request.group_id,
            "transaction_id": transaction_id,
            "purpose": request.purpose,
            "amount": request.amount,
            "currency_code": currency,
            "date_time": moment.isoformat(),
            "paid_by": [names.get(payer.member_id) for payer in request.paid_by],
            "split_between": [names.get(share.member_id) for share in shares],
            "next_step": "Use settleup_get_balances to read the new balances.",
        }


def _share(share: MemberShare) -> dict[str, str]:
    return {"memberId": share.member_id, "weight": share.weight}


def _default_split(members: dict[str, Any]) -> list[MemberShare]:
    """Give each active member with the default weight of that member."""
    shares = []
    for member_id, member in members.items():
        if not isinstance(member, dict) or not member.get("active", True):
            continue
        weight = str(member.get("defaultWeight", "1"))
        if weight in ("0", "0.0"):
            continue
        shares.append(MemberShare(member_id=member_id, weight=weight))
    return shares


def _check_members(
    members: dict[str, Any],
    payers: list[MemberShare],
    shares: list[MemberShare],
) -> None:
    """Stop the tool if a member id is not in the group."""
    unknown = sorted(
        {share.member_id for share in [*payers, *shares]} - set(members.keys())
    )
    if unknown:
        raise SettleUpError(
            f"The group does not have these member ids: {', '.join(unknown)}. "
            "Use settleup_list_members to find the correct member ids."
        )


def _describe(
    transaction_id: str,
    transaction: dict[str, Any],
    names: dict[str, Any],
) -> dict[str, Any]:
    """Change one raw transaction into a clear result for the agent."""
    millis = transaction.get("dateTime") or 0
    try:
        millis = int(millis)
    except (TypeError, ValueError):
        millis = 0

    payers = [
        {
            "member_id": str(payer.get("memberId")),
            "name": names.get(str(payer.get("memberId"))),
            "weight": str(payer.get("weight", "1")),
        }
        for payer in transaction.get("whoPaid") or []
        if isinstance(payer, dict)
    ]

    split: list[dict[str, Any]] = []
    for item in transaction.get("items") or []:
        if not isinstance(item, dict):
            continue
        for share in item.get("forWhom") or []:
            if not isinstance(share, dict):
                continue
            split.append(
                {
                    "member_id": str(share.get("memberId")),
                    "name": names.get(str(share.get("memberId"))),
                    "weight": str(share.get("weight", "1")),
                }
            )

    return {
        "transaction_id": transaction_id,
        "type": str(transaction.get("type", "expense")),
        "purpose": transaction.get("purpose"),
        "category": transaction.get("category"),
        "amount": format_amount(transaction_total(transaction)),
        "currency_code": transaction.get("currencyCode"),
        "date_time": to_iso(millis),
        "date_time_millis": millis,
        "paid_by": payers,
        "split_between": split,
    }
