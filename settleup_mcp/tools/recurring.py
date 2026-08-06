"""The tools that read and write the recurring transaction templates."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from settleup_mcp.client import SettleUpError
from settleup_mcp.models import (
    AddRecurringRequest,
    DeleteRecurringRequest,
    ListRecurringRequest,
)
from settleup_mcp.tools.common import (
    DESTRUCTIVE,
    READ_ONLY,
    WRITE,
    check_members,
    default_split,
    format_amount,
    group_currency,
    names_of,
    paginate,
    shares_of,
    to_iso,
    to_millis,
    transaction_total,
)

if TYPE_CHECKING:  # pragma: no cover
    from fastmcp import FastMCP

    from settleup_mcp.client import SettleUpClient


def register(mcp: "FastMCP", client: "SettleUpClient") -> None:
    """Add the recurring transaction tools to the server."""

    @mcp.tool(
        name="settleup_list_recurring",
        title="List the recurring transactions of a Settle Up group",
        annotations=READ_ONLY,
    )
    async def settleup_list_recurring(
        request: ListRecurringRequest,
    ) -> dict[str, Any]:
        """List the transaction templates of one group.

        The Settle Up server uses a template to generate an expense, for
        example the rent each month.
        """
        templates, members = await asyncio.gather(
            client.list_recurring(request.group_id),
            client.list_members(request.group_id),
        )
        names = names_of(members)

        rows = []
        for template_id, entry in templates.items():
            if not isinstance(entry, dict):
                continue
            rows.append(_describe(template_id, entry, names))
        rows.sort(key=lambda row: str(row["purpose"] or "").lower())

        page = paginate(rows, request.limit, request.offset)
        return {
            "group_id": request.group_id,
            "total": page["total"],
            "limit": page["limit"],
            "offset": page["offset"],
            "count": page["count"],
            "has_more": page["has_more"],
            "recurring_transactions": page["items"],
        }

    @mcp.tool(
        name="settleup_add_recurring",
        title="Add a recurring transaction to a Settle Up group",
        annotations=WRITE,
    )
    async def settleup_add_recurring(request: AddRecurringRequest) -> dict[str, Any]:
        """Add one transaction template.

        The Settle Up server generates an expense on each date. The server
        runs 6 times each day. It generates each expense between 01:00 and
        05:00 in the time zone of the user.
        """
        try:
            start = request.parsed_start()
            end = request.parsed_end()
        except ValueError as error:
            raise SettleUpError(str(error)) from error

        if end and end <= start:
            raise SettleUpError(
                "The end_date is at or before the start_date. "
                "Give an end_date after the start_date."
            )
        if request.period == "monthly" and not request.monthly_setting:
            raise SettleUpError(
                "The period 'monthly' needs monthly_setting. Use 'dayOfMonth' "
                "or 'lastDayOfMonth'."
            )
        if request.weekly_setting and request.period != "weekly":
            raise SettleUpError(
                "The field weekly_setting works with the period 'weekly' only."
            )

        group, members = await asyncio.gather(
            client.get_group(request.group_id),
            client.list_members(request.group_id),
        )
        if not members:
            raise SettleUpError(
                f"The group {request.group_id} has no members. "
                "Use settleup_list_groups to find a correct group id."
            )

        shares = request.split_between or default_split(members)
        if not shares:
            raise SettleUpError(
                f"The group {request.group_id} has no active member. "
                "Give split_between with at least 1 member id."
            )
        check_members(members, request.paid_by, shares)
        currency = group_currency(group, request.currency_code)

        template: dict[str, Any] = {
            "type": "expense",
            "purpose": request.purpose,
            "currencyCode": currency,
            "fixedExchangeRate": False,
            "whoPaid": shares_of(request.paid_by),
            "items": [{"amount": request.amount, "forWhom": shares_of(shares)}],
        }
        if request.category:
            template["category"] = request.category

        offset = start.utcoffset()
        recurrence: dict[str, Any] = {
            "startDate": to_millis(start),
            "period": request.period,
            "frequency": request.frequency,
            "timezoneOffsetMillis": int(offset.total_seconds() * 1000)
            if offset
            else 0,
        }
        if end:
            recurrence["endDate"] = to_millis(end)
        if request.end_count:
            recurrence["endCount"] = request.end_count
        if request.monthly_setting:
            recurrence["monthlySetting"] = request.monthly_setting
        if request.weekly_setting:
            recurrence["weeklySetting"] = request.weekly_setting

        template_id = await client.create_recurring(
            request.group_id,
            {"template": template, "recurrence": recurrence},
        )
        return {
            "created": True,
            "group_id": request.group_id,
            "template_id": template_id,
            "purpose": request.purpose,
            "amount": request.amount,
            "currency_code": currency,
            "period": request.period,
            "frequency": request.frequency,
            "start_date": start.isoformat(),
            "end_date": end.isoformat() if end else None,
            "note": (
                "The server generates the first expense on the start date. "
                "It does not generate an expense for a past date."
            ),
        }

    @mcp.tool(
        name="settleup_delete_recurring",
        title="Delete a Settle Up recurring transaction",
        annotations=DESTRUCTIVE,
    )
    async def settleup_delete_recurring(
        request: DeleteRecurringRequest,
    ) -> dict[str, Any]:
        """Delete one transaction template. The server then generates no more.

        Caution: Ask the user before you call this tool. The generated
        expenses stay in the group. This tool deletes the template only.
        """
        if not request.confirm:
            raise SettleUpError(
                "The delete is not confirmed. Ask the user first. "
                "Then call this tool again with confirm set to true."
            )

        templates = await client.list_recurring(request.group_id)
        current = templates.get(request.template_id)
        if not isinstance(current, dict):
            raise SettleUpError(
                f"The group {request.group_id} has no recurring transaction "
                f"{request.template_id}. Use settleup_list_recurring to find "
                "the correct template id."
            )

        await client.delete_recurring(request.group_id, request.template_id)
        return {
            "deleted": True,
            "group_id": request.group_id,
            "template_id": request.template_id,
            "purpose": (current.get("template") or {}).get("purpose"),
            "note": "The expenses that the server generated stay in the group.",
        }


def _describe(
    template_id: str,
    entry: dict[str, Any],
    names: dict[str, Any],
) -> dict[str, Any]:
    """Change one raw template into a clear result for the agent."""
    template = entry.get("template") or {}
    recurrence = entry.get("recurrence") or {}

    payers = [
        names.get(str(payer.get("memberId")))
        for payer in template.get("whoPaid") or []
        if isinstance(payer, dict)
    ]

    return {
        "template_id": template_id,
        "purpose": template.get("purpose"),
        "amount": format_amount(transaction_total(template)),
        "currency_code": template.get("currencyCode"),
        "category": template.get("category"),
        "paid_by": payers,
        "period": recurrence.get("period"),
        "frequency": recurrence.get("frequency"),
        "start_date": to_iso(recurrence.get("startDate")),
        "end_date": to_iso(recurrence.get("endDate")),
        "end_count": recurrence.get("endCount"),
        "monthly_setting": recurrence.get("monthlySetting"),
        "weekly_setting": recurrence.get("weeklySetting"),
        "run_count": entry.get("runCount", 0),
        "last_generated": to_iso(entry.get("lastGenerated")),
    }
