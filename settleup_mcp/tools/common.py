"""The helper functions that more than 1 tool module uses."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, TypeVar

T = TypeVar("T")

READ_ONLY = {"readOnlyHint": True, "destructiveHint": False, "openWorldHint": True}
WRITE = {"readOnlyHint": False, "destructiveHint": False, "openWorldHint": True}
DESTRUCTIVE = {
    "readOnlyHint": False,
    "destructiveHint": True,
    "idempotentHint": True,
    "openWorldHint": True,
}


def names_of(members: dict[str, Any]) -> dict[str, Any]:
    """Give a map from the member id to the member name."""
    return {
        member_id: (member or {}).get("name")
        for member_id, member in members.items()
        if isinstance(member, dict)
    }


def shares_of(shares: list[Any]) -> list[dict[str, str]]:
    """Change each MemberShare into the API form."""
    return [
        {"memberId": share.member_id, "weight": share.weight} for share in shares
    ]


def default_split(members: dict[str, Any]) -> list[Any]:
    """Give each active member with the default weight of that member."""
    from settleup_mcp.models import MemberShare

    shares = []
    for member_id, member in members.items():
        if not isinstance(member, dict) or not member.get("active", True):
            continue
        weight = str(member.get("defaultWeight", "1"))
        if decimal_of(weight) == 0:
            continue
        shares.append(MemberShare(member_id=member_id, weight=weight))
    return shares


def check_members(members: dict[str, Any], *groups: list[Any]) -> None:
    """Stop the tool if a member id is not in the group."""
    from settleup_mcp.client import SettleUpError

    wanted = {share.member_id for shares in groups for share in shares}
    unknown = sorted(wanted - set(members.keys()))
    if unknown:
        raise SettleUpError(
            f"The group does not have these member ids: {', '.join(unknown)}. "
            "Use settleup_list_members to find the correct member ids."
        )


def group_currency(
    group: dict[str, Any] | None, wanted: str | None
) -> str:
    """Give the currency for a new transaction. Stop on a currency conflict."""
    from settleup_mcp.client import SettleUpError

    current = (group or {}).get("convertedToCurrency")
    currency = wanted or current
    if not currency:
        raise SettleUpError(
            "The group has no currency. Give currency_code, for example 'EUR'."
        )
    if current and currency != current:
        raise SettleUpError(
            f"The group uses {current}. This tool cannot write an amount in "
            f"{currency}, because it has no exchange rate. "
            f"Give the amount in {current}."
        )
    return str(currency)


def paginate(items: list[T], limit: int, offset: int) -> dict[str, Any]:
    """Cut one page out of a list. Give the page and the counts."""
    total = len(items)
    page = items[offset : offset + limit]
    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "count": len(page),
        "has_more": (offset + len(page)) < total,
        "items": page,
    }


def to_iso(millis: Any) -> str | None:
    """Change a millisecond timestamp into an ISO 8601 text."""
    try:
        value = int(millis)
    except (TypeError, ValueError):
        return None
    return datetime.fromtimestamp(value / 1000, tz=timezone.utc).isoformat()


def to_millis(moment: datetime) -> int:
    """Change a datetime into a millisecond timestamp."""
    return int(moment.timestamp() * 1000)


def timezone_offset(moment: datetime) -> str:
    """Give the time zone offset as text, for example '+05:30'."""
    offset = moment.utcoffset()
    if offset is None:
        return "+00:00"
    total_minutes = int(offset.total_seconds() // 60)
    sign = "+" if total_minutes >= 0 else "-"
    total_minutes = abs(total_minutes)
    return f"{sign}{total_minutes // 60:02d}:{total_minutes % 60:02d}"


def decimal_of(value: Any) -> Decimal:
    """Change a value into a Decimal. Give 0 if the value is not a number."""
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal(0)


def format_amount(value: Decimal) -> str:
    """Give the amount as plain text without an exponent."""
    return format(value, "f")


def transaction_total(transaction: dict[str, Any]) -> Decimal:
    """Add each item amount of one transaction."""
    items = transaction.get("items")
    if not isinstance(items, list):
        return Decimal(0)
    total = Decimal(0)
    for item in items:
        if isinstance(item, dict):
            total += decimal_of(item.get("amount"))
    return total


def member_ids_of(transaction: dict[str, Any]) -> set[str]:
    """Give each member id that one transaction refers to."""
    found: set[str] = set()
    for payer in transaction.get("whoPaid") or []:
        if isinstance(payer, dict) and payer.get("memberId"):
            found.add(str(payer["memberId"]))
    for item in transaction.get("items") or []:
        if not isinstance(item, dict):
            continue
        for share in item.get("forWhom") or []:
            if isinstance(share, dict) and share.get("memberId"):
                found.add(str(share["memberId"]))
    return found
