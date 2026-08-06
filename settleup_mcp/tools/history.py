"""The tools that read the group history, the categories, and the permissions."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from settleup_mcp.models import (
    ListCategoriesRequest,
    ListChangesRequest,
    ListPermissionsRequest,
    RecalculateDebtsRequest,
)
from settleup_mcp.tools.common import READ_ONLY, WRITE, paginate, to_iso

if TYPE_CHECKING:  # pragma: no cover
    from fastmcp import FastMCP

    from settleup_mcp.client import SettleUpClient

PERMISSION_LEVELS = {30: "owner", 20: "read and write", 10: "read only"}


def register(mcp: "FastMCP", client: "SettleUpClient") -> None:
    """Add the history tools to the server."""

    @mcp.tool(
        name="settleup_list_changes",
        title="List the change log of a Settle Up group",
        annotations=READ_ONLY,
    )
    async def settleup_list_changes(request: ListChangesRequest) -> dict[str, Any]:
        """List the changes in one group.

        The Settle Up server writes 1 entry for each change. Use this tool to
        find who added, changed, or deleted an entity.
        """
        changes = await client.list_changes(request.group_id)

        rows = []
        for change_id, change in changes.items():
            if not isinstance(change, dict):
                continue
            millis = _millis_of(change)
            rows.append(
                {
                    "change_id": change_id,
                    "action": change.get("action"),
                    "entity": change.get("entity"),
                    "entity_id": change.get("entityId"),
                    "entity_name": change.get("entityName"),
                    "by_user_id": change.get("by"),
                    "time": to_iso(millis),
                    "time_millis": millis,
                }
            )
        rows.sort(key=lambda row: row["time_millis"], reverse=request.newest_first)

        page = paginate(rows, request.limit, request.offset)
        return {
            "group_id": request.group_id,
            "total": page["total"],
            "limit": page["limit"],
            "offset": page["offset"],
            "count": page["count"],
            "has_more": page["has_more"],
            "changes": page["items"],
            "note": "An entry with no by_user_id comes from the server.",
        }

    @mcp.tool(
        name="settleup_list_categories",
        title="List the custom categories of a Settle Up group",
        annotations=READ_ONLY,
    )
    async def settleup_list_categories(
        request: ListCategoriesRequest,
    ) -> dict[str, Any]:
        """List the custom category names of one group.

        A category is an emoji. A group can give a name to each emoji. Use an
        emoji from this list in settleup_add_expense.
        """
        categories, transactions = await asyncio.gather(
            client.list_categories(request.group_id),
            client.list_transactions(request.group_id),
        )

        counts: dict[str, int] = {}
        for transaction in transactions.values():
            if not isinstance(transaction, dict):
                continue
            emoji = transaction.get("category")
            if emoji:
                counts[str(emoji)] = counts.get(str(emoji), 0) + 1

        rows = [
            {
                "emoji": emoji,
                "name": categories.get(emoji),
                "used_count": counts.get(emoji, 0),
            }
            for emoji in sorted(set(categories) | set(counts))
        ]
        rows.sort(key=lambda row: int(row["used_count"] or 0), reverse=True)

        return {
            "group_id": request.group_id,
            "total": len(rows),
            "categories": rows,
        }

    @mcp.tool(
        name="settleup_list_permissions",
        title="List who can access a Settle Up group",
        annotations=READ_ONLY,
    )
    async def settleup_list_permissions(
        request: ListPermissionsRequest,
    ) -> dict[str, Any]:
        """List the user accounts that can access one group.

        A permission belongs to a user account. It does not belong to a
        member. The levels are 30 (owner), 20 (read and write), and 10 (read
        only).
        """
        permissions, user_id = await asyncio.gather(
            client.list_permissions(request.group_id),
            client.get_user_id(),
        )

        rows = []
        for other_id, permission in permissions.items():
            if not isinstance(permission, dict):
                continue
            level = permission.get("level")
            try:
                level = int(level)
            except (TypeError, ValueError):
                level = 0
            rows.append(
                {
                    "user_id": other_id,
                    "level": level,
                    "level_name": PERMISSION_LEVELS.get(level, "unknown"),
                    "is_you": other_id == user_id,
                }
            )
        rows.sort(key=lambda row: int(row["level"] or 0), reverse=True)

        page = paginate(rows, request.limit, request.offset)
        return {
            "group_id": request.group_id,
            "your_user_id": user_id,
            "total": page["total"],
            "limit": page["limit"],
            "offset": page["offset"],
            "count": page["count"],
            "has_more": page["has_more"],
            "permissions": page["items"],
        }

    @mcp.tool(
        name="settleup_recalculate_debts",
        title="Recalculate the debts of a Settle Up group",
        annotations=WRITE,
    )
    async def settleup_recalculate_debts(
        request: RecalculateDebtsRequest,
    ) -> dict[str, Any]:
        """Ask the Settle Up server to calculate the debts again.

        The server does this automatically after each change. Use this tool
        only when the balances look wrong.
        """
        result = await client.run_server_task(
            "calculateGroupsDebts", {"groupId": request.group_id}
        )
        return {
            "group_id": request.group_id,
            "task_id": result["task_id"],
            "status": result["status"],
            "next_step": "Use settleup_get_balances to read the new balances.",
        }


def _millis_of(change: dict[str, Any]) -> int:
    try:
        return int(change.get("serverTimestamp") or 0)
    except (TypeError, ValueError):
        return 0
