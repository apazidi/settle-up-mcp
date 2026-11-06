"""Exercise MCP discovery, rejection, client registration and owner authorization."""

import asyncio
from unittest.mock import AsyncMock

import fastmcp
import httpx
import pytest
from fastmcp.server.auth.auth import AccessToken
from fastmcp.server.auth.providers.google import GoogleProvider

from settleup_mcp.client import SettleUpClient
from settleup_mcp.mcp_auth import OwnerGoogleProvider
from settleup_mcp.server import create_server
from tests.conftest import FakeServer, make_settings
from tests.test_config import google_config


@pytest.fixture
def oauth_home(tmp_path, monkeypatch):
    monkeypatch.setattr(fastmcp.settings, "home", tmp_path)
    return tmp_path


@pytest.mark.parametrize(("changes", "allowed"), [
    ({}, True),
    ({"email": "OWNER@example.com"}, True),
    ({"email_verified": "true"}, True),
    ({"email": "other@example.com"}, False),
    ({"email": None}, False),
    ({"email_verified": False}, False),
    ({"email_verified": "false"}, False),
    ({"email_verified": 1}, False),
    ({"aud": "another-client"}, False),
])
def test_only_verified_owner_of_expected_google_app_is_allowed(oauth_home, monkeypatch, changes, allowed):
    claims = {"email": "owner@example.com", "email_verified": True,
              "aud": "client.apps.googleusercontent.com"}
    claims.update(changes)
    verified = AccessToken(token="fake-upstream-token", client_id="user-1", scopes=[], claims=claims)
    parent = AsyncMock(return_value=verified)
    monkeypatch.setattr(GoogleProvider, "load_access_token", parent)
    auth = OwnerGoogleProvider(google_config())
    result = asyncio.run(auth.verify_token("fake-mcp-token"))
    assert (result is not None) is allowed
    parent.assert_awaited_once_with("fake-mcp-token")


def test_invalid_upstream_session_cannot_authorize_owner(oauth_home, monkeypatch):
    monkeypatch.setattr(GoogleProvider, "load_access_token", AsyncMock(return_value=None))
    assert asyncio.run(OwnerGoogleProvider(google_config()).verify_token("invalid")) is None


def test_http_discovery_rejection_registration_and_pkce(oauth_home):
    async def run():
        settings = make_settings(auth_mode="google", google_oauth=google_config())
        api = SettleUpClient(settings, FakeServer().client())
        server = create_server(settings, api)
        app = server.http_app(path="/mcp")
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                         base_url="https://mcp.example.com") as http:
                resource = await http.get("/.well-known/oauth-protected-resource/mcp")
                assert resource.status_code == 200
                assert resource.json()["resource"] == "https://mcp.example.com/mcp"
                metadata = await http.get("/.well-known/oauth-authorization-server")
                assert metadata.status_code == 200
                auth_meta = metadata.json()
                assert "S256" in auth_meta["code_challenge_methods_supported"]
                assert auth_meta["issuer"].rstrip("/") == "https://mcp.example.com"
                for headers in ({}, {"Authorization": "Bearer invalid"}):
                    denied = await http.post("/mcp", headers=headers, json={
                        "jsonrpc": "2.0", "id": 1, "method": "tools/list",
                    })
                    assert denied.status_code == 401
                    assert "resource_metadata" in denied.headers["www-authenticate"]
                bad = await http.post("/register", json={
                    "client_name": "Test", "redirect_uris": ["https://attacker.example/callback"],
                })
                assert bad.status_code == 400
                assert bad.json()["error"] == "invalid_redirect_uri"
                registered = await http.post("/register", json={
                    "client_name": "Test",
                    "redirect_uris": ["https://chatgpt.com/connector/oauth/test"],
                    "token_endpoint_auth_method": "none",
                    "grant_types": ["authorization_code", "refresh_token"],
                    "response_types": ["code"],
                })
                assert registered.status_code == 201, registered.text
                client_id = registered.json()["client_id"]
                bad_pkce = await http.get("/authorize", params={
                    "client_id": client_id,
                    "redirect_uri": "https://chatgpt.com/connector/oauth/test",
                    "response_type": "code", "code_challenge": "x" * 43,
                    "code_challenge_method": "plain",
                })
                assert bad_pkce.status_code in (400, 302)
                assert "invalid_request" in (bad_pkce.text + bad_pkce.headers.get("location", ""))
    asyncio.run(run())


def test_static_token_still_protects_http():
    async def run():
        settings = make_settings(auth_mode="token", auth_token="fake-test-token")
        server = create_server(settings, SettleUpClient(settings, FakeServer().client()))
        app = server.http_app(path="/mcp", stateless_http=True)
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                         base_url="http://testserver") as http:
                payload = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                           "params": {"protocolVersion": "2025-11-25", "capabilities": {},
                                      "clientInfo": {"name": "test", "version": "1"}}}
                assert (await http.post("/mcp", json=payload)).status_code == 401
                accepted = await http.post("/mcp", json=payload, headers={
                    "Authorization": "Bearer fake-test-token",
                    "Accept": "application/json, text/event-stream",
                })
                assert accepted.status_code == 200, accepted.text
    asyncio.run(run())


@pytest.mark.parametrize(("email", "status"), [
    ("owner@example.com", 200), ("other@example.com", 401),
])
def test_owner_policy_is_enforced_on_http_requests(oauth_home, monkeypatch, email, status):
    verified = AccessToken(
        token="fake-google-token", client_id="user-1",
        scopes=["openid", "https://www.googleapis.com/auth/userinfo.email"],
        claims={"email": email, "email_verified": True,
                "aud": "client.apps.googleusercontent.com"},
    )
    monkeypatch.setattr(GoogleProvider, "load_access_token", AsyncMock(return_value=verified))
    async def run():
        settings = make_settings(auth_mode="google", google_oauth=google_config())
        api = SettleUpClient(settings, FakeServer().client())
        app = create_server(settings, api).http_app(path="/mcp", stateless_http=True)
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                         base_url="https://mcp.example.com") as http:
                response = await http.post("/mcp", headers={
                    "Authorization": "Bearer fake-mcp-token",
                    "Accept": "application/json, text/event-stream",
                }, json={"jsonrpc": "2.0", "id": 1, "method": "initialize",
                         "params": {"protocolVersion": "2025-11-25", "capabilities": {},
                                    "clientInfo": {"name": "test", "version": "1"}}})
                assert response.status_code == status
    asyncio.run(run())
