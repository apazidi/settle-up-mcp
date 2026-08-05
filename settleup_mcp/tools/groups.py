"""The tools that read groups, members, and balances."""

from __future__ import annotations

import asyncio
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from settleup_mcp.models import (
    GetBalancesRequest,
    ListGroupsRequest,
    ListMembersRequest,
)
from settleup_mcp.tools.common import (
    READ_ONLY,
    decimal_of,
    format_amount,
    paginate,
    to_iso,
)

if TYPE_CHECKING:  # pragma: no cover
    from fastmcp import FastMCP

    from settleup_mcp.client import SettleUpClient


def register(mcp: "FastMCP", client: "SettleUpClient") -> None:
    """Add the group tools to the server."""

    @mcp.tool(
        name="settleup_list_groups",
        title="List Settle Up groups",
        annotations=READ_ONLY,
    )
    async def settleup_list_groups(
        request: ListGroupsRequest = ListGroupsRequest(),
    ) -> dict[str, Any]:
        """List each Settle Up group that the account can read.

        Use this tool first. The other tools need a group id from this list.
        """
        user_id = await client.get_user_id()
        user_groups = await client.list_user_groups(user_id)

        entries = [
            (group_id, link)
            for group_id, link in user_groups.items()
            if isinstance(link, dict)
        ]
        entries.sort(key=lambda item: _order_of(item[1]))

        page = paginate(entries, request.limit, request.offset)
        details = await asyncio.gather(
            *(client.get_group(group_id) for group_id, _ in page["items"])
        )

        groups = []
        for (group_id, link), group in zip(page["items"], details):
            group = group or {}
            groups.append(
                {
                    "group_id": group_id,
                    "name": group.get("name"),
                    "currency_code": group.get("convertedToCurrency"),
                    "your_member_id": link.get("member"),
                    "last_changed": to_iso(group.get("lastChanged")),
                }
            )

        return {
            "user_id": user_id,
            "total": page["total"],
            "limit": page["limit"],
            "offset": page["offset"],
            "count": page["count"],
            "has_more": page["has_more"],
            "groups": groups,
        }

    @mcp.tool(
        name="settleup_list_members",
        title="List the members of a Settle Up group",
        annotations=READ_ONLY,
    )
    async def settleup_list_members(request: ListMembersRequest) -> dict[str, Any]:
        """List the members of one group.

        A member is a person in the group. Each expense refers to member ids.
        """
        members = await client.list_members(request.group_id)

        rows = []
        for member_id, member in members.items():
            if not isinstance(member, dict):
                continue
            active = bool(member.get("active", True))
            if request.only_active and not active:
                continue
            rows.append(
                {
                    "member_id": member_id,
                    "name": member.get("name"),
                    "active": active,
                    "default_weight": str(member.get("defaultWeight", "1")),
                }
            )
        rows.sort(key=lambda row: str(row["name"] or "").lower())

        page = paginate(rows, request.limit, request.offset)
        return {
            "group_id": request.group_id,
            "total": page["total"],
            "limit": page["limit"],
            "offset": page["offset"],
            "count": page["count"],
            "has_more": page["has_more"],
            "members": page["items"],
        }

    @mcp.tool(
        name="settleup_get_balances",
        title="Get who owes what in a Settle Up group",
        annotations=READ_ONLY,
    )
    async def settleup_get_balances(request: GetBalancesRequest) -> dict[str, Any]:
        """Give the debts and the net balance of each member in one group.

        The Settle Up server calculates the debts. A positive net balance
        means that the other members owe money to this member.
        """
        group, members, debts = await asyncio.gather(
            client.get_group(request.group_id),
            client.list_members(request.group_id),
            client.list_debts(request.group_id),
        )
        group = group or {}
        names = {
            member_id: (member or {}).get("name")
            for member_id, member in members.items()
            if isinstance(member, dict)
        }

        net: dict[str, Decimal] = {member_id: Decimal(0) for member_id in names}
        rows = []
        for debt in debts:
            payer = str(debt.get("from", ""))
            receiver = str(debt.get("to", ""))
            amount = decimal_of(debt.get("amount"))
            net[payer] = net.get(payer, Decimal(0)) - amount
            net[receiver] = net.get(receiver, Decimal(0)) + amount
            rows.append(
                {
                    "from_member_id": payer,
                    "from_name": names.get(payer),
                    "to_member_id": receiver,
                    "to_name": names.get(receiver),
                    "amount": format_amount(amount),
                }
            )

        balances = [
            {
                "member_id": member_id,
                "name": names.get(member_id),
                "balance": format_amount(amount),
            }
            for member_id, amount in net.items()
        ]
        balances.sort(key=lambda row: decimal_of(row["balance"]), reverse=True)

        return {
            "group_id": request.group_id,
            "group_name": group.get("name"),
            "currency_code": group.get("convertedToCurrency"),
            "debts": rows,
            "net_balances": balances,
            "settled": not rows,
        }


def _order_of(link: dict[str, Any]) -> float:
    try:
        return float(link.get("order", 0))
    except (TypeError, ValueError):
        return 0.0
