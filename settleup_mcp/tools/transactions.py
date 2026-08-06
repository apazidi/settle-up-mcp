"""The tools that read and write transactions."""

from __future__ import annotations

import asyncio
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from settleup_mcp.client import SettleUpError
from settleup_mcp.models import (
    AddExpenseRequest,
    AddTransferRequest,
    DeleteExpenseRequest,
    GetExpenseRequest,
    ListExpensesRequest,
    MemberShare,
    SummarizeSpendingRequest,
    UpdateExpenseRequest,
    parse_moment,
)
from settleup_mcp.tools.common import (
    DESTRUCTIVE,
    READ_ONLY,
    WRITE,
    check_members,
    decimal_of,
    default_split,
    format_amount,
    group_currency,
    member_ids_of,
    names_of,
    paginate,
    shares_of,
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
        names = names_of(members)

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

        rows.sort(key=lambda row: row["date_time_millis"], reverse=request.newest_first)

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
        name="settleup_get_expense",
        title="Get one Settle Up transaction",
        annotations=READ_ONLY,
    )
    async def settleup_get_expense(request: GetExpenseRequest) -> dict[str, Any]:
        """Read all details of one transaction.

        Use this tool before settleup_update_expense. Then you can see the
        current values.
        """
        transaction, members = await asyncio.gather(
            client.get_transaction(request.group_id, request.transaction_id),
            client.list_members(request.group_id),
        )
        if not isinstance(transaction, dict):
            raise SettleUpError(_no_transaction(request.group_id, request.transaction_id))
        result = _describe(request.transaction_id, transaction, names_of(members))
        result["group_id"] = request.group_id
        result["receipt_url"] = transaction.get("receiptUrl")
        result["timezone"] = transaction.get("timezone")
        return result

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
        moment = _moment(request.date_time)

        group, members = await asyncio.gather(
            client.get_group(request.group_id),
            client.list_members(request.group_id),
        )
        _need_members(members, request.group_id)

        shares = request.split_between or default_split(members)
        if not shares:
            raise SettleUpError(
                f"The group {request.group_id} has no active member. "
                "Give split_between with at least 1 member id."
            )
        check_members(members, request.paid_by, shares)
        currency = group_currency(group, request.currency_code)

        transaction: dict[str, Any] = {
            "type": "expense",
            "purpose": request.purpose,
            "currencyCode": currency,
            "dateTime": to_millis(moment),
            "timezone": timezone_offset(moment),
            "fixedExchangeRate": False,
            "whoPaid": shares_of(request.paid_by),
            "items": [{"amount": request.amount, "forWhom": shares_of(shares)}],
        }
        if request.category:
            transaction["category"] = request.category

        transaction_id = await client.create_transaction(request.group_id, transaction)
        names = names_of(members)
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

    @mcp.tool(
        name="settleup_add_transfer",
        title="Record a payment between 2 Settle Up members",
        annotations=WRITE,
    )
    async def settleup_add_transfer(request: AddTransferRequest) -> dict[str, Any]:
        """Record a payment from 1 member to another member.

        Use this tool when a person pays a debt. The transfer makes the debt
        smaller. Use settleup_get_balances first to read the debt.
        """
        if request.from_member_id == request.to_member_id:
            raise SettleUpError(
                "The payer and the receiver are the same member. "
                "Give 2 different member ids."
            )
        moment = _moment(request.date_time)

        group, members = await asyncio.gather(
            client.get_group(request.group_id),
            client.list_members(request.group_id),
        )
        _need_members(members, request.group_id)

        payer = MemberShare(member_id=request.from_member_id)
        receiver = MemberShare(member_id=request.to_member_id)
        check_members(members, [payer, receiver])
        currency = group_currency(group, request.currency_code)

        transaction = {
            "type": "transfer",
            "purpose": request.purpose,
            "currencyCode": currency,
            "dateTime": to_millis(moment),
            "timezone": timezone_offset(moment),
            "fixedExchangeRate": False,
            "whoPaid": shares_of([payer]),
            "items": [{"amount": request.amount, "forWhom": shares_of([receiver])}],
        }

        transaction_id = await client.create_transaction(request.group_id, transaction)
        names = names_of(members)
        return {
            "created": True,
            "group_id": request.group_id,
            "transaction_id": transaction_id,
            "type": "transfer",
            "amount": request.amount,
            "currency_code": currency,
            "from_member_id": request.from_member_id,
            "from_name": names.get(request.from_member_id),
            "to_member_id": request.to_member_id,
            "to_name": names.get(request.to_member_id),
            "date_time": moment.isoformat(),
            "next_step": "Use settleup_get_balances to read the new balances.",
        }

    @mcp.tool(
        name="settleup_update_expense",
        title="Change a Settle Up transaction",
        annotations=WRITE,
    )
    async def settleup_update_expense(request: UpdateExpenseRequest) -> dict[str, Any]:
        """Change 1 or more fields of a transaction.

        Give only the fields that change. The server keeps each other field.
        Use settleup_get_expense first to read the current values.
        """
        if not request.has_changes():
            raise SettleUpError(
                "The request changes no field. Give at least 1 of these fields: "
                "amount, purpose, paid_by, split_between, category, date_time."
            )

        current, members = await asyncio.gather(
            client.get_transaction(request.group_id, request.transaction_id),
            client.list_members(request.group_id),
        )
        if not isinstance(current, dict):
            raise SettleUpError(_no_transaction(request.group_id, request.transaction_id))

        updated = dict(current)
        changed: list[str] = []

        if request.purpose is not None:
            updated["purpose"] = request.purpose
            changed.append("purpose")
        if request.category is not None:
            updated["category"] = request.category
            changed.append("category")
        if request.date_time is not None:
            moment = _moment(request.date_time)
            updated["dateTime"] = to_millis(moment)
            updated["timezone"] = timezone_offset(moment)
            changed.append("date_time")
        if request.paid_by is not None:
            check_members(members, request.paid_by)
            updated["whoPaid"] = shares_of(request.paid_by)
            changed.append("paid_by")

        items = updated.get("items")
        rest = items[1:] if isinstance(items, list) else []
        first = dict(items[0]) if isinstance(items, list) and items else {}

        if request.amount is not None:
            if rest:
                raise SettleUpError(
                    "This transaction has more than 1 item, for example a tip. "
                    "This tool cannot change the amount. Change it in the app."
                )
            first["amount"] = request.amount
            changed.append("amount")
        if request.split_between is not None:
            check_members(members, request.split_between)
            first["forWhom"] = shares_of(request.split_between)
            changed.append("split_between")
        if request.amount is not None or request.split_between is not None:
            updated["items"] = [first, *rest]

        await client.replace_transaction(
            request.group_id, request.transaction_id, updated
        )
        result = _describe(request.transaction_id, updated, names_of(members))
        result["group_id"] = request.group_id
        result["updated"] = True
        result["changed_fields"] = changed
        result["next_step"] = "Use settleup_get_balances to read the new balances."
        return result

    @mcp.tool(
        name="settleup_delete_expense",
        title="Delete a Settle Up transaction",
        annotations=DESTRUCTIVE,
    )
    async def settleup_delete_expense(request: DeleteExpenseRequest) -> dict[str, Any]:
        """Delete 1 transaction. The delete is permanent.

        Caution: Ask the user before you call this tool. Set confirm to true
        only after the user agrees.
        """
        if not request.confirm:
            raise SettleUpError(
                "The delete is not confirmed. Ask the user first. "
                "Then call this tool again with confirm set to true."
            )

        current = await client.get_transaction(request.group_id, request.transaction_id)
        if not isinstance(current, dict):
            raise SettleUpError(
                f"The group {request.group_id} has no transaction "
                f"{request.transaction_id}. It is deleted already, or the id is "
                "wrong."
            )

        await client.delete_transaction(request.group_id, request.transaction_id)
        return {
            "deleted": True,
            "group_id": request.group_id,
            "transaction_id": request.transaction_id,
            "purpose": current.get("purpose"),
            "amount": format_amount(transaction_total(current)),
            "next_step": "Use settleup_get_balances to read the new balances.",
        }

    @mcp.tool(
        name="settleup_summarize_spending",
        title="Summarize the spending of a Settle Up group",
        annotations=READ_ONLY,
    )
    async def settleup_summarize_spending(
        request: SummarizeSpendingRequest,
    ) -> dict[str, Any]:
        """Add the expense amounts by category, by member, or by month.

        This tool counts expenses only. It skips each transfer, because a
        transfer moves money and does not spend it.
        """
        try:
            since, until = request.window()
        except ValueError as error:
            raise SettleUpError(str(error)) from error

        group, members, transactions, categories = await asyncio.gather(
            client.get_group(request.group_id),
            client.list_members(request.group_id),
            client.list_transactions(request.group_id),
            client.list_categories(request.group_id),
        )
        names = names_of(members)

        totals: dict[str, Decimal] = defaultdict(lambda: Decimal(0))
        counted = 0
        grand = Decimal(0)

        for transaction in transactions.values():
            if not isinstance(transaction, dict):
                continue
            if str(transaction.get("type", "expense")) != "expense":
                continue
            millis = _millis_of(transaction)
            if since is not None and millis < since:
                continue
            if until is not None and millis >= until:
                continue

            total = transaction_total(transaction)
            counted += 1
            grand += total

            if request.group_by == "category":
                emoji = str(transaction.get("category") or "")
                key = f"{emoji} {categories.get(emoji, '')}".strip() or "No category"
                totals[key] += total
            elif request.group_by == "month":
                moment = datetime.fromtimestamp(millis / 1000, tz=timezone.utc)
                totals[moment.strftime("%Y-%m")] += total
            else:
                for member_id, share in _member_shares(transaction, total).items():
                    totals[names.get(member_id) or member_id] += share

        rows = [
            {"key": key, "total": format_amount(value)}
            for key, value in totals.items()
        ]
        if request.group_by == "month":
            rows.sort(key=lambda row: str(row["key"]))
        else:
            rows.sort(key=lambda row: decimal_of(row["total"]), reverse=True)

        return {
            "group_id": request.group_id,
            "group_name": (group or {}).get("name"),
            "currency_code": (group or {}).get("convertedToCurrency"),
            "group_by": request.group_by,
            "since": request.since,
            "until": request.until,
            "transaction_count": counted,
            "grand_total": format_amount(grand),
            "rows": rows[: request.top],
        }


def _moment(text: str | None) -> datetime:
    """Read an ISO 8601 date. Change a bad value into a clear tool error."""
    try:
        return parse_moment(text)
    except ValueError as error:
        raise SettleUpError(str(error)) from error


def _no_transaction(group_id: str, transaction_id: str) -> str:
    return (
        f"The group {group_id} has no transaction {transaction_id}. "
        "Use settleup_list_expenses to find the correct transaction id."
    )


def _need_members(members: dict[str, Any], group_id: str) -> None:
    if not members:
        raise SettleUpError(
            f"The group {group_id} has no members. "
            "Use settleup_list_groups to find a correct group id."
        )


def _millis_of(transaction: dict[str, Any]) -> int:
    try:
        return int(transaction.get("dateTime") or 0)
    except (TypeError, ValueError):
        return 0


def _member_shares(transaction: dict[str, Any], total: Decimal) -> dict[str, Decimal]:
    """Split the total of 1 transaction between the members, by weight."""
    weights: dict[str, Decimal] = defaultdict(lambda: Decimal(0))
    for item in transaction.get("items") or []:
        if not isinstance(item, dict):
            continue
        for share in item.get("forWhom") or []:
            if isinstance(share, dict) and share.get("memberId"):
                weights[str(share["memberId"])] += decimal_of(share.get("weight", 1))

    sum_of_weights = sum(weights.values(), Decimal(0))
    if sum_of_weights == 0:
        return {}
    return {
        member_id: total * weight / sum_of_weights
        for member_id, weight in weights.items()
    }


def _describe(
    transaction_id: str,
    transaction: dict[str, Any],
    names: dict[str, Any],
) -> dict[str, Any]:
    """Change one raw transaction into a clear result for the agent."""
    millis = _millis_of(transaction)

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
