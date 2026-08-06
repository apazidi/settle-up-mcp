"""The tools that read and write group members."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from settleup_mcp.client import SettleUpError
from settleup_mcp.models import (
    AddMemberRequest,
    DeactivateMemberRequest,
    UpdateMemberRequest,
)
from settleup_mcp.tools.common import WRITE

if TYPE_CHECKING:  # pragma: no cover
    from fastmcp import FastMCP

    from settleup_mcp.client import SettleUpClient


def register(mcp: "FastMCP", client: "SettleUpClient") -> None:
    """Add the member tools to the server."""

    @mcp.tool(
        name="settleup_add_member",
        title="Add a member to a Settle Up group",
        annotations=WRITE,
    )
    async def settleup_add_member(request: AddMemberRequest) -> dict[str, Any]:
        """Add one person to a group.

        A member is a person in 1 group. A member is not a user account. Each
        expense refers to member ids.
        """
        members = await client.list_members(request.group_id)
        for member_id, member in members.items():
            if not isinstance(member, dict):
                continue
            if str(member.get("name", "")).strip().lower() == request.name.lower():
                raise SettleUpError(
                    f"The group has a member with the name {request.name!r} "
                    f"already. The member id is {member_id}. Use "
                    "settleup_update_member to change that member."
                )

        member: dict[str, Any] = {
            "name": request.name,
            "active": request.active,
            "defaultWeight": request.default_weight,
        }
        if request.bank_account:
            member["bankAccount"] = request.bank_account

        member_id = await client.create_member(request.group_id, member)
        return {
            "created": True,
            "group_id": request.group_id,
            "member_id": member_id,
            "name": request.name,
            "active": request.active,
            "default_weight": request.default_weight,
            "next_step": "Use this member id in settleup_add_expense.",
        }

    @mcp.tool(
        name="settleup_update_member",
        title="Change a Settle Up group member",
        annotations=WRITE,
    )
    async def settleup_update_member(request: UpdateMemberRequest) -> dict[str, Any]:
        """Change the name, the weight, the state, or the bank account.

        Give only the fields that change. The server keeps each other field.
        """
        changes = request.changes()
        if not changes:
            raise SettleUpError(
                "The request changes no field. Give at least 1 of these fields: "
                "name, default_weight, active, bank_account."
            )

        current = await client.get_member(request.group_id, request.member_id)
        if not isinstance(current, dict):
            raise SettleUpError(_no_member(request.group_id, request.member_id))

        await client.update_member(request.group_id, request.member_id, changes)
        return {
            "updated": True,
            "group_id": request.group_id,
            "member_id": request.member_id,
            "name": changes.get("name", current.get("name")),
            "changed_fields": sorted(changes.keys()),
        }

    @mcp.tool(
        name="settleup_deactivate_member",
        title="Deactivate a Settle Up group member",
        annotations=WRITE,
    )
    async def settleup_deactivate_member(
        request: DeactivateMemberRequest,
    ) -> dict[str, Any]:
        """Set a member to not active.

        A new expense then skips the member. The old expenses do not change.
        The debts of the member stay. Settle each debt first.
        """
        current = await client.get_member(request.group_id, request.member_id)
        if not isinstance(current, dict):
            raise SettleUpError(_no_member(request.group_id, request.member_id))

        if not current.get("active", True):
            return {
                "updated": False,
                "group_id": request.group_id,
                "member_id": request.member_id,
                "name": current.get("name"),
                "active": False,
                "note": "The member is not active already.",
            }

        await client.update_member(
            request.group_id, request.member_id, {"active": False}
        )
        return {
            "updated": True,
            "group_id": request.group_id,
            "member_id": request.member_id,
            "name": current.get("name"),
            "active": False,
            "next_step": (
                "Use settleup_get_balances to confirm that the member owes "
                "nothing."
            ),
        }


def _no_member(group_id: str, member_id: str) -> str:
    return (
        f"The group {group_id} has no member {member_id}. "
        "Use settleup_list_members to find the correct member id."
    )
