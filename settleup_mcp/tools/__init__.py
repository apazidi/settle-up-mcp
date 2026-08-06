"""The tool modules. Each module registers its tools on the server."""

from __future__ import annotations

from typing import TYPE_CHECKING

from settleup_mcp.tools import groups, history, members, recurring, transactions

if TYPE_CHECKING:  # pragma: no cover
    from fastmcp import FastMCP

    from settleup_mcp.client import SettleUpClient


def register_tools(mcp: "FastMCP", client: "SettleUpClient") -> None:
    """Add each tool to the server."""
    groups.register(mcp, client)
    members.register(mcp, client)
    transactions.register(mcp, client)
    recurring.register(mcp, client)
    history.register(mcp, client)


__all__ = ["register_tools"]
