"""The helper functions that more than 1 tool module uses."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, TypeVar

T = TypeVar("T")

READ_ONLY = {"readOnlyHint": True, "destructiveHint": False, "openWorldHint": True}
WRITE = {"readOnlyHint": False, "destructiveHint": False, "openWorldHint": True}


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
