"""The shared test tools. A fake Firebase server answers each request."""

from __future__ import annotations

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
        "lastChanged": 1457015264428,
    },
    "group_2": {
        "name": "Trip",
        "convertedToCurrency": "USD",
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
    }
    values.update(changes)
    return Settings(**values)


class FakeServer:
    """Answer the Firebase auth calls and the Settle Up data calls."""

    def __init__(self) -> None:
        self.sign_in_count = 0
        self.refresh_count = 0
        self.created: list[dict[str, Any]] = []
        self.expires_in = "3600"
        self.transactions = json.loads(json.dumps(TRANSACTIONS))
        self.forbidden_paths: set[str] = set()

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=self.transport())

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

        parts = path.split("/")
        head = parts[0]

        if request.method == "POST" and head == "transactions":
            body = json.loads(request.content.decode())
            self.created.append({"group_id": parts[1], "transaction": body})
            return httpx.Response(200, json={"name": "tx_new"})

        if request.method != "GET":
            return httpx.Response(200, json=None)

        table: dict[str, Any] = {
            "userGroups": {USER_ID: USER_GROUPS},
            "groups": GROUPS,
            "members": MEMBERS,
            "transactions": self.transactions,
            "debts": DEBTS,
        }
        node: Any = table.get(head)
        for part in parts[1:]:
            if not isinstance(node, dict):
                node = None
                break
            node = node.get(part)
        return httpx.Response(200, json=node)
