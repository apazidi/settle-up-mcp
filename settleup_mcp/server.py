"""Build and start the Settle Up MCP server."""

from __future__ import annotations

import contextlib
import logging
from collections.abc import AsyncIterator
from typing import Any

from fastmcp import FastMCP
from fastmcp.server.auth.providers.jwt import StaticTokenVerifier
from starlette.requests import Request
from starlette.responses import JSONResponse

from settleup_mcp.client import SettleUpClient
from settleup_mcp.config import Settings, get_settings
from settleup_mcp.tools import register_tools

logger = logging.getLogger(__name__)

INSTRUCTIONS = """
This server reads and writes Settle Up shared expense data.

Start with settleup_list_groups to get a group id. Then use
settleup_list_members to get the member ids of that group. The other tools
need those ids.
""".strip()


def create_server(
    settings: Settings | None = None,
    client: SettleUpClient | None = None,
) -> FastMCP:
    """Build the MCP server. Register each tool."""
    settings = settings or get_settings()
    client = client or SettleUpClient(settings)

    @contextlib.asynccontextmanager
    async def lifespan(_: FastMCP) -> AsyncIterator[None]:
        logger.info(
            "The Settle Up MCP server starts. Environment: %s.",
            "sandbox" if settings.is_sandbox else "live",
        )
        try:
            yield
        finally:
            await client.aclose()
            logger.info("The Settle Up MCP server stopped.")

    auth = None
    if settings.auth_token:
        auth = StaticTokenVerifier(
            tokens={
                settings.auth_token: {
                    "client_id": "settleup-agent",
                    "scopes": [],
                }
            }
        )
        logger.info("The server requires a bearer token from each agent.")
    else:
        logger.warning(
            "MCP_AUTH_TOKEN is empty. The server accepts each request. "
            "Use this mode for local tests only."
        )

    mcp: FastMCP = FastMCP(
        name="settleup_mcp",
        instructions=INSTRUCTIONS,
        version="0.1.0",
        auth=auth,
        lifespan=lifespan,
    )

    @mcp.custom_route("/health", methods=["GET"], include_in_schema=False)
    async def health(_: Request) -> JSONResponse:
        """Give the server state. The container health check reads this route."""
        body: dict[str, Any] = {
            "status": "ok",
            "server": "settleup_mcp",
            "environment": "sandbox" if settings.is_sandbox else "live",
            "signed_in": client.auth.user_id is not None,
        }
        return JSONResponse(body)

    register_tools(mcp, client)
    return mcp


def main() -> None:
    """Start the server with the Streamable HTTP transport."""
    settings = get_settings()
    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    server = create_server(settings)
    server.run(
        transport="http",
        host=settings.host,
        port=settings.port,
        path=settings.path,
        log_level=settings.log_level,
    )


if __name__ == "__main__":
    main()
