"""The tools that read groups, members, and balances."""

from __future__ import annotations

import asyncio
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from settleup_mcp.client import SettleUpError
from settleup_mcp.models import (
    ChangeCurrencyRequest,
    CreateGroupRequest,
    DeleteGroupRequest,
    GetBalancesRequest,
    GetGroupRequest,
    GetInviteLinkRequest,
    ListGroupsRequest,
    ListMembersRequest,
    UpdateGroupRequest,
)
from settleup_mcp.tools.common import (
    DESTRUCTIVE,
    READ_ONLY,
    WRITE,
    decimal_of,
    format_amount,
    names_of,
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
        names = names_of(members)

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

    @mcp.tool(
        name="settleup_get_group",
        title="Get the details of a Settle Up group",
        annotations=READ_ONLY,
    )
    async def settleup_get_group(request: GetGroupRequest) -> dict[str, Any]:
        """Give the settings and the counts of one group.

        Use this tool to read the currency, the member count, and the
        transaction count before a write.
        """
        group, members, transactions = await asyncio.gather(
            client.get_group(request.group_id),
            client.list_members(request.group_id),
            client.list_transactions(request.group_id),
        )
        if not isinstance(group, dict):
            raise SettleUpError(_no_group(request.group_id))

        active = sum(
            1
            for member in members.values()
            if isinstance(member, dict) and member.get("active", True)
        )
        return {
            "group_id": request.group_id,
            "name": group.get("name"),
            "currency_code": group.get("convertedToCurrency"),
            "minimize_debts": bool(group.get("minimizeDebts", True)),
            "invite_link_active": bool(group.get("inviteLinkActive", False)),
            "member_count": len(members),
            "active_member_count": active,
            "transaction_count": len(transactions),
            "last_changed": to_iso(group.get("lastChanged")),
        }

    @mcp.tool(
        name="settleup_create_group",
        title="Create a Settle Up group",
        annotations=WRITE,
    )
    async def settleup_create_group(request: CreateGroupRequest) -> dict[str, Any]:
        """Create one new group. Add yourself as the first member.

        The tool makes 5 writes. It creates the group, the permission, your
        member, the group link, and the current tab.
        """
        user_id = await client.get_user_id()
        group_id = await client.create_group(
            {
                "name": request.name,
                "convertedToCurrency": request.currency_code,
                "minimizeDebts": request.minimize_debts,
                "inviteLinkActive": False,
            }
        )
        await client.set_permission(group_id, user_id, 30)
        member_id = await client.create_member(
            group_id,
            {"name": request.your_member_name, "active": True, "defaultWeight": "1"},
        )
        await client.set_user_group(
            user_id, group_id, {"member": member_id, "order": 0}
        )
        await client.set_current_tab(user_id, group_id)

        return {
            "created": True,
            "group_id": group_id,
            "name": request.name,
            "currency_code": request.currency_code,
            "your_member_id": member_id,
            "your_user_id": user_id,
            "next_step": (
                "Use settleup_add_member to add each other person. Then use "
                "settleup_add_expense."
            ),
        }

    @mcp.tool(
        name="settleup_update_group",
        title="Change the settings of a Settle Up group",
        annotations=WRITE,
    )
    async def settleup_update_group(request: UpdateGroupRequest) -> dict[str, Any]:
        """Change the name, the debt setting, or the invite link.

        Give only the fields that change. This tool does not change the
        currency. Use settleup_change_currency for that.
        """
        changes = request.changes()
        if not changes:
            raise SettleUpError(
                "The request changes no field. Give at least 1 of these "
                "fields: name, minimize_debts, invite_link_active."
            )

        group = await client.get_group(request.group_id)
        if not isinstance(group, dict):
            raise SettleUpError(_no_group(request.group_id))

        await client.update_group(request.group_id, changes)
        return {
            "updated": True,
            "group_id": request.group_id,
            "name": changes.get("name", group.get("name")),
            "changed_fields": sorted(changes.keys()),
        }

    @mcp.tool(
        name="settleup_get_invite_link",
        title="Get the invite link of a Settle Up group",
        annotations=WRITE,
    )
    async def settleup_get_invite_link(
        request: GetInviteLinkRequest,
    ) -> dict[str, Any]:
        """Give the link that invites a person into one group.

        The tool switches the link on if the link is off. A person that opens
        the link gets read and write access.
        """
        group = await client.get_group(request.group_id)
        if not isinstance(group, dict):
            raise SettleUpError(_no_group(request.group_id))

        activated = False
        if not group.get("inviteLinkActive", False):
            await client.update_group(request.group_id, {"inviteLinkActive": True})
            activated = True

        return {
            "group_id": request.group_id,
            "name": group.get("name"),
            "invite_link": f"https://settleup.io/join/{request.group_id}",
            "activated_now": activated,
            "caution": (
                "Each person with this link gets read and write access. Send "
                "the link to a trusted person only. Use settleup_update_group "
                "with invite_link_active false to stop the link."
            ),
        }

    @mcp.tool(
        name="settleup_change_currency",
        title="Change the currency of a Settle Up group",
        annotations=WRITE,
    )
    async def settleup_change_currency(
        request: ChangeCurrencyRequest,
    ) -> dict[str, Any]:
        """Change the group currency. The server converts each amount.

        Caution: The server uses the current exchange rate. It changes each
        old transaction. Ask the user before you call this tool.
        """
        group = await client.get_group(request.group_id)
        if not isinstance(group, dict):
            raise SettleUpError(_no_group(request.group_id))

        current = str(group.get("convertedToCurrency") or "").upper()
        if current == request.target_currency:
            return {
                "changed": False,
                "group_id": request.group_id,
                "currency_code": current,
                "note": "The group uses this currency already.",
            }

        result = await client.run_server_task(
            "currencyChange",
            {"groupId": request.group_id, "targetCurrency": request.target_currency},
        )
        return {
            "changed": result["status"] == "ok",
            "group_id": request.group_id,
            "from_currency": current,
            "to_currency": request.target_currency,
            "task_id": result["task_id"],
            "status": result["status"],
        }

    @mcp.tool(
        name="settleup_delete_group",
        title="Delete a Settle Up group",
        annotations=DESTRUCTIVE,
    )
    async def settleup_delete_group(request: DeleteGroupRequest) -> dict[str, Any]:
        """Delete one group with each member and each transaction.

        Caution: You cannot undo this delete. Ask the user first. Then call
        this tool again with confirm set to true.
        """
        if not request.confirm:
            raise SettleUpError(
                "The delete is not confirmed. Show the group name and the "
                "transaction count to the user. Ask the user first. Then call "
                "this tool again with confirm set to true."
            )

        group, transactions = await asyncio.gather(
            client.get_group(request.group_id),
            client.list_transactions(request.group_id),
        )
        if not isinstance(group, dict):
            raise SettleUpError(_no_group(request.group_id))

        result = await client.run_server_task(
            "deleteGroup", {"groupId": request.group_id}
        )
        return {
            "deleted": result["status"] == "ok",
            "group_id": request.group_id,
            "name": group.get("name"),
            "deleted_transaction_count": len(transactions),
            "task_id": result["task_id"],
            "status": result["status"],
        }


def _no_group(group_id: str) -> str:
    return (
        f"No group has the id {group_id}. "
        "Use settleup_list_groups to find the correct group id."
    )


def _order_of(link: dict[str, Any]) -> float:
    try:
        return float(link.get("order", 0))
    except (TypeError, ValueError):
        return 0.0
