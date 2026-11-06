"""The shared test tools. A fake Firebase server answers each request."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx

from settleup_mcp.config import Settings

BASE_URL = "https://settle-up-sandbox.firebaseio.com"

USER_ID = "user_1"

GROUPS = {
    "group_1": {
        "name": "Flat",
        "convertedToCurrency": "EUR",
        "minimizeDebts": True,
        "inviteLinkActive": False,
        "lastChanged": 1457015264428,
    },
    "group_2": {
        "name": "Trip",
        "convertedToCurrency": "USD",
        "minimizeDebts": True,
        "inviteLinkActive": True,
        "lastChanged": 1457015264428,
    },
}

USER_GROUPS = {
    "group_1": {"order": 2, "member": "member_1"},
    "group_2": {"order": 1, "member": "member_3"},
}

MEMBERS = {
    "group_1": {
        "member_1": {"name": "Ann", "active": True, "defaultWeight": "1"},
        "member_2": {"name": "Ben", "active": True, "defaultWeight": "1"},
        "member_9": {"name": "Old", "active": False, "defaultWeight": "1"},
    },
    "group_2": {"member_3": {"name": "Cid", "active": True, "defaultWeight": "1"}},
}

TRANSACTIONS = {
    "group_1": {
        "tx_1": {
            "type": "expense",
            "purpose": "Coffee",
            "category": "\u2615",
            "currencyCode": "EUR",
            "dateTime": 1000,
            "items": [
                {
                    "amount": "10.00",
                    "forWhom": [
                        {"memberId": "member_1", "weight": "1"},
                        {"memberId": "member_2", "weight": "1"},
                    ],
                }
            ],
            "whoPaid": [{"memberId": "member_1", "weight": "1"}],
        },
        "tx_2": {
            "type": "transfer",
            "purpose": "Payback",
            "currencyCode": "EUR",
            "dateTime": 2000,
            "items": [
                {
                    "amount": "5.00",
                    "forWhom": [{"memberId": "member_1", "weight": "1"}],
                }
            ],
            "whoPaid": [{"memberId": "member_2", "weight": "1"}],
        },
    }
}

DEBTS = {"group_1": [{"from": "member_2", "to": "member_1", "amount": "5.00"}]}

PERMISSIONS = {
    "group_1": {USER_ID: {"level": 30}, "user_2": {"level": 20}},
    "group_2": {USER_ID: {"level": 30}},
}

GROUP_CATEGORIES = {"group_1": {"\u2615": "Coffee and tea", "\U0001f355": "Food"}}

CHANGES = {
    "group_1": {
        "change_1": {
            "action": "add",
            "entity": "transaction",
            "entityId": "tx_1",
            "entityName": "Coffee",
            "by": USER_ID,
            "serverTimestamp": 1000,
        },
        "change_2": {
            "action": "update",
            "entity": "member",
            "entityId": "member_2",
            "entityName": "Ben",
            "by": "user_2",
            "serverTimestamp": 2000,
        },
    }
}

RECURRING = {
    "group_1": {
        "rec_1": {
            "template": {
                "type": "expense",
                "purpose": "Rent",
                "currencyCode": "EUR",
                "whoPaid": [{"memberId": "member_1", "weight": "1"}],
                "items": [
                    {
                        "amount": "800.00",
                        "forWhom": [
                            {"memberId": "member_1", "weight": "1"},
                            {"memberId": "member_2", "weight": "1"},
                        ],
                    }
                ],
            },
            "recurrence": {
                "startDate": 1000,
                "period": "monthly",
                "frequency": 1,
                "monthlySetting": "dayOfMonth",
                "timezoneOffsetMillis": 0,
            },
            "runCount": 3,
            "lastGenerated": 5000,
        }
    }
}

USERS = {USER_ID: {"currentTabId": "group_1"}}


def make_settings(**changes: Any) -> Settings:
    """Give test settings. Each value is a fake value."""
    values: dict[str, Any] = {
        "email": "test@example.com",
        "password": "secret",
        "firebase_api_key": "test-key",
        "base_url": BASE_URL,
        "request_timeout_seconds": 5.0,
        "token_refresh_margin_seconds": 300,
        "host": "127.0.0.1",
        "port": 8000,
        "path": "/mcp",
        "log_level": "INFO",
        "auth_token": None,
        "auth_mode": "none",
    }
    values.update(changes)
    return Settings(**values)


def _copy(value: Any) -> Any:
    """Give a deep copy of one JSON value."""
    return json.loads(json.dumps(value))


def call(server: "FakeServer", tool: str, request: Any = None) -> Any:
    """Call one tool through an in-memory MCP client. Give the result data."""
    from fastmcp import Client

    from settleup_mcp.client import SettleUpClient
    from settleup_mcp.server import create_server

    async def run() -> Any:
        api = SettleUpClient(make_settings(), server.client())
        mcp = create_server(make_settings(), api)
        arguments = {} if request is None else {"request": request}
        async with Client(mcp) as client:
            result = await client.call_tool(tool, arguments)
        return result.data

    return asyncio.run(run())


class FakeServer:
    """Answer the Firebase auth calls and the Settle Up data calls.

    The server holds 1 in-memory tree. It answers GET, POST, PUT, PATCH, and
    DELETE like the Firebase Realtime Database.
    """

    def __init__(self) -> None:
        self.sign_in_count = 0
        self.refresh_count = 0
        self.created: list[dict[str, Any]] = []
        self.writes: list[dict[str, Any]] = []
        self.expires_in = "3600"
        self.forbidden_paths: set[str] = set()
        self.next_id = 0
        self.task_code: Any = "ok"
        self.data: dict[str, Any] = _copy(
            {
                "userGroups": {USER_ID: USER_GROUPS},
                "groups": GROUPS,
                "members": MEMBERS,
                "transactions": TRANSACTIONS,
                "debts": DEBTS,
                "permissions": PERMISSIONS,
                "groupCategories": GROUP_CATEGORIES,
                "changes": CHANGES,
                "recurringTransactions": RECURRING,
                "users": USERS,
                "serverTasks": {},
            }
        )

    # ---- Test helpers --------------------------------------------------

    @property
    def transactions(self) -> dict[str, Any]:
        """Give the transaction node. Some tests change it."""
        return self.data["transactions"]

    @transactions.setter
    def transactions(self, value: dict[str, Any]) -> None:
        self.data["transactions"] = value

    def node(self, path: str) -> Any:
        """Read 1 node out of the tree. Use a path like 'members/group_1'."""
        return self._read(path.split("/"))

    def writes_to(self, method: str, prefix: str) -> list[dict[str, Any]]:
        """Give each write with this method and this path start."""
        return [
            write
            for write in self.writes
            if write["method"] == method and write["path"].startswith(prefix)
        ]

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=self.transport())

    # ---- Request handling ----------------------------------------------

    def handle(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "identitytoolkit" in url:
            self.sign_in_count += 1
            return httpx.Response(
                200,
                json={
                    "idToken": f"id-token-{self.sign_in_count}",
                    "refreshToken": "refresh-token",
                    "expiresIn": self.expires_in,
                    "localId": USER_ID,
                },
            )
        if "securetoken" in url:
            self.refresh_count += 1
            return httpx.Response(
                200,
                json={
                    "id_token": f"refreshed-token-{self.refresh_count}",
                    "refresh_token": "refresh-token",
                    "expires_in": self.expires_in,
                    "user_id": USER_ID,
                },
            )
        return self._data(request)

    def _data(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path.removeprefix("/").removesuffix(".json")
        if path in self.forbidden_paths:
            return httpx.Response(403, json={"error": "Permission denied"})

        parts = [part for part in path.split("/") if part]
        method = request.method
        body = self._body(request)

        if method == "GET":
            return httpx.Response(200, json=self._read(parts))

        self.writes.append({"method": method, "path": path, "body": body})

        if method == "POST":
            return self._post(parts, body)
        if method == "PUT":
            self._write(parts, body)
            return httpx.Response(200, json=body)
        if method == "PATCH":
            node = self._read(parts)
            merged = dict(node) if isinstance(node, dict) else {}
            merged.update(body if isinstance(body, dict) else {})
            self._write(parts, merged)
            return httpx.Response(200, json=body)
        if method == "DELETE":
            self._remove(parts)
            return httpx.Response(200, json=None)
        return httpx.Response(405, json={"error": "Method not allowed"})

    def _post(self, parts: list[str], body: Any) -> httpx.Response:
        self.next_id += 1
        if parts and parts[0] == "serverTasks":
            task_id = f"task_{self.next_id}"
            self._write(
                parts + [task_id],
                {"request": body, "response": {"code": self.task_code}},
            )
            return httpx.Response(200, json={"name": task_id})

        new_id = f"{parts[0][:2]}_new_{self.next_id}"
        if parts and parts[0] == "transactions":
            new_id = "tx_new"
            self.created.append({"group_id": parts[1], "transaction": body})
        self._write(parts + [new_id], body)
        return httpx.Response(200, json={"name": new_id})

    @staticmethod
    def _body(request: httpx.Request) -> Any:
        content = request.content.decode()
        if not content:
            return None
        return json.loads(content)

    def _read(self, parts: list[str]) -> Any:
        node: Any = self.data
        for part in parts:
            if not isinstance(node, dict):
                return None
            node = node.get(part)
        return _copy(node) if isinstance(node, (dict, list)) else node

    def _write(self, parts: list[str], value: Any) -> None:
        node = self.data
        for part in parts[:-1]:
            child = node.get(part)
            if not isinstance(child, dict):
                child = {}
                node[part] = child
            node = child
        node[parts[-1]] = _copy(value) if isinstance(value, (dict, list)) else value

    def _remove(self, parts: list[str]) -> None:
        node = self.data
        for part in parts[:-1]:
            child = node.get(part)
            if not isinstance(child, dict):
                return
            node = child
        node.pop(parts[-1], None)
