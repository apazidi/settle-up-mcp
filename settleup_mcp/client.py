"""The Settle Up REST client. All HTTP calls to the API stay in this file."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

from settleup_mcp.auth import AuthError, FirebaseAuth
from settleup_mcp.config import Settings

logger = logging.getLogger(__name__)

Json = dict[str, Any]


class SettleUpError(RuntimeError):
    """A Settle Up API call failed. The message tells the agent the next step."""


class SettleUpClient:
    """Read and write Settle Up data through the Firebase REST API."""

    def __init__(
        self,
        settings: Settings,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._settings = settings
        self._http = http_client or httpx.AsyncClient(
            timeout=settings.request_timeout_seconds
        )
        self._auth = FirebaseAuth(settings, self._http)

    async def aclose(self) -> None:
        """Close the HTTP connections."""
        await self._http.aclose()

    @property
    def auth(self) -> FirebaseAuth:
        return self._auth

    async def get_user_id(self) -> str:
        """Give the Firebase user id of the configured Settle Up account."""
        return await self._auth.get_user_id()

    async def check_health(self) -> bool:
        """Confirm that the server can get a token. Give True on success."""
        token = await self._auth.get_id_token()
        return bool(token)

    async def get(self, path: str, params: Json | None = None) -> Any:
        """Read one path. Give the decoded JSON, or None if the path is empty."""
        return await self._request("GET", path, params=params)

    async def post(self, path: str, body: Json) -> Any:
        """Create one entity. Give the new key in a `name` field."""
        return await self._request("POST", path, json=body)

    async def put(self, path: str, body: Any) -> Any:
        """Write one path. The old value is lost."""
        return await self._request("PUT", path, json=body)

    async def patch(self, path: str, body: Json) -> Any:
        """Update some fields of one path."""
        return await self._request("PATCH", path, json=body)

    async def delete(self, path: str) -> Any:
        """Delete one path."""
        return await self._request("DELETE", path)

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: Json | None = None,
        json: Any = None,
    ) -> Any:
        response = await self._send(method, path, params, json)
        if response.status_code == 401:
            # The token can expire between 2 calls. Get a new token and retry 1 time.
            await self._auth.invalidate()
            response = await self._send(method, path, params, json)

        if response.status_code >= 400:
            raise SettleUpError(_explain(method, path, response))

        if not response.content:
            return None
        try:
            return response.json()
        except ValueError as error:
            raise SettleUpError(
                f"The Settle Up API gave data that is not JSON for {path}. "
                "Try the request again."
            ) from error

    async def _send(
        self,
        method: str,
        path: str,
        params: Json | None,
        json: Any,
    ) -> httpx.Response:
        try:
            token = await self._auth.get_id_token()
        except AuthError as error:
            raise SettleUpError(
                f"The server cannot sign in to Settle Up. {error}"
            ) from error

        query: Json = dict(params or {})
        query["auth"] = token
        url = f"{self._settings.base_url}/{path.strip('/')}.json"

        try:
            return await self._http.request(method, url, params=query, json=json)
        except httpx.HTTPError:
            raise SettleUpError(
                f"The server cannot reach the Settle Up API at {path}. "
                "Check the network and SETTLEUP_BASE_URL."
            ) from None

    # ---- Domain calls -------------------------------------------------

    async def list_user_groups(self, user_id: str) -> Json:
        """Give the groups of one user. The key is the group id."""
        return await self.get(f"userGroups/{user_id}") or {}

    async def get_group(self, group_id: str) -> Json | None:
        """Give one group."""
        return await self.get(f"groups/{group_id}")

    async def list_members(self, group_id: str) -> Json:
        """Give the members of one group. The key is the member id."""
        return await self.get(f"members/{group_id}") or {}

    async def list_transactions(self, group_id: str) -> Json:
        """Give the transactions of one group. The key is the transaction id."""
        return await self.get(f"transactions/{group_id}") or {}

    async def list_debts(self, group_id: str) -> list[Json]:
        """Give the debts of one group. The server calculates them."""
        debts = await self.get(f"debts/{group_id}")
        if not debts:
            return []
        if isinstance(debts, dict):
            return [value for value in debts.values() if isinstance(value, dict)]
        return [item for item in debts if isinstance(item, dict)]

    async def create_transaction(self, group_id: str, transaction: Json) -> str:
        """Create one transaction. Give the new transaction id."""
        result = await self.post(f"transactions/{group_id}", transaction)
        return _new_id(result, "transaction")

    async def get_transaction(self, group_id: str, transaction_id: str) -> Json | None:
        """Give one transaction."""
        return await self.get(f"transactions/{group_id}/{transaction_id}")

    async def replace_transaction(
        self, group_id: str, transaction_id: str, transaction: Json
    ) -> None:
        """Write one transaction. The old value is lost."""
        await self.put(f"transactions/{group_id}/{transaction_id}", transaction)

    async def delete_transaction(self, group_id: str, transaction_id: str) -> None:
        """Delete one transaction."""
        await self.delete(f"transactions/{group_id}/{transaction_id}")

    # ---- Members ------------------------------------------------------

    async def create_member(self, group_id: str, member: Json) -> str:
        """Create one member. Give the new member id."""
        result = await self.post(f"members/{group_id}", member)
        return _new_id(result, "member")

    async def get_member(self, group_id: str, member_id: str) -> Json | None:
        """Give one member."""
        return await self.get(f"members/{group_id}/{member_id}")

    async def update_member(
        self, group_id: str, member_id: str, changes: Json
    ) -> None:
        """Change some fields of one member."""
        await self.patch(f"members/{group_id}/{member_id}", changes)

    # ---- Groups -------------------------------------------------------

    async def create_group(self, group: Json) -> str:
        """Create one group. Give the new group id."""
        result = await self.post("groups", group)
        return _new_id(result, "group")

    async def update_group(self, group_id: str, changes: Json) -> None:
        """Change some fields of one group."""
        await self.patch(f"groups/{group_id}", changes)

    async def set_permission(self, group_id: str, user_id: str, level: int) -> None:
        """Give one user access to one group."""
        await self.put(f"permissions/{group_id}/{user_id}", {"level": level})

    async def list_permissions(self, group_id: str) -> Json:
        """Give the users that can access one group. The key is the user id."""
        return await self.get(f"permissions/{group_id}") or {}

    async def set_user_group(self, user_id: str, group_id: str, link: Json) -> None:
        """Add one group to the group list of one user."""
        await self.put(f"userGroups/{user_id}/{group_id}", link)

    async def set_current_tab(self, user_id: str, group_id: str) -> None:
        """Set the group that the user sees next in the app."""
        await self.put(f"users/{user_id}/currentTabId", group_id)

    async def list_categories(self, group_id: str) -> Json:
        """Give the custom category names. The key is the emoji."""
        return await self.get(f"groupCategories/{group_id}") or {}

    async def list_changes(self, group_id: str) -> Json:
        """Give the change log of one group. The key is the change id."""
        return await self.get(f"changes/{group_id}") or {}

    # ---- Recurring transactions ---------------------------------------

    async def list_recurring(self, group_id: str) -> Json:
        """Give the transaction templates. The key is the template id."""
        return await self.get(f"recurringTransactions/{group_id}") or {}

    async def create_recurring(self, group_id: str, template: Json) -> str:
        """Create one transaction template. Give the new template id."""
        result = await self.post(f"recurringTransactions/{group_id}", template)
        return _new_id(result, "recurring transaction")

    async def delete_recurring(self, group_id: str, template_id: str) -> None:
        """Delete one transaction template."""
        await self.delete(f"recurringTransactions/{group_id}/{template_id}")

    # ---- Server tasks -------------------------------------------------

    async def run_server_task(
        self,
        task_name: str,
        request: Json,
        *,
        attempts: int = 10,
        delay_seconds: float = 1.0,
    ) -> Json:
        """Start one server task. Wait for the result.

        The Settle Up server runs these tasks in the background. This method
        polls the response code until the task gives an answer.
        """
        result = await self.post(f"serverTasks/{task_name}", {"request": request})
        task_id = _new_id(result, f"{task_name} task")

        for attempt in range(attempts):
            if attempt:
                await asyncio.sleep(delay_seconds)
            code = await self.get(f"serverTasks/{task_name}/{task_id}/response/code")
            if code is None:
                continue
            text = str(code)
            if text.lower() == "ok":
                return {"task_id": task_id, "status": "ok"}
            raise SettleUpError(
                f"The Settle Up server task {task_name} failed with the code "
                f"{text!r}. Check the input values. Then try again."
            )

        return {
            "task_id": task_id,
            "status": "pending",
            "note": (
                f"The task {task_name} still runs. Read the group again in some "
                "seconds to confirm the result."
            ),
        }


def _new_id(result: Any, entity: str) -> str:
    """Read the new key out of a Firebase POST answer."""
    if not isinstance(result, dict) or "name" not in result:
        raise SettleUpError(
            f"The Settle Up API gave no id for the new {entity}. "
            "Read the group again to confirm the result."
        )
    return str(result["name"])


def _explain(method: str, path: str, response: httpx.Response) -> str:
    """Give a clear error message. Never give a secret."""
    status = response.status_code
    if status in (401, 403):
        return (
            f"Settle Up refused the {method} on {path}. Status {status}. "
            "The account has no permission for this group. "
            "Use settleup_list_groups to find a group with access."
        )
    if status == 404:
        return (
            f"Settle Up did not find {path}. Status 404. "
            "Check the group id and the member id."
        )
    if status == 429:
        return (
            f"Settle Up limited the rate of the {method} on {path}. "
            "Wait some seconds. Then try again."
        )
    if status >= 500:
        return (
            f"The Settle Up server failed on the {method} on {path}. "
            f"Status {status}. Try again later."
        )
    return (
        f"The {method} on {path} failed. Status {status}. "
        "Check the tool input values."
    )
