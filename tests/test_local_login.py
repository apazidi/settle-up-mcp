"""Exercise the local login boundary without real Google credentials."""
from __future__ import annotations

import threading

import httpx
import pytest
from dotenv import dotenv_values

from settleup_mcp import local_login as login


@pytest.fixture
def local_server(tmp_path):
    env = tmp_path / ".env"
    env.write_text("SETTLEUP_FIREBASE_API_KEY=test-key\nMCP_AUTH_TOKEN=keep-me\n", encoding="utf-8")
    server = login.LocalLoginServer(env, port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()


def request(server, method, path, **kwargs):
    headers = {"Host": server.expected_host}
    headers.update(kwargs.pop("headers", {}))
    return httpx.request(
        method, f"http://127.0.0.1:{server.server_port}{path}",
        headers=headers, timeout=3, **kwargs,
    )


def auth_headers(server):
    return {"X-Setup-Token": server.csrf, "Origin": server.origin}


def test_configuration_is_not_available_without_capability(local_server):
    response = request(local_server, "GET", "/config")
    assert response.status_code == 404
    assert "test-key" not in response.text
    assert response.headers["cache-control"] == "no-store"


def test_wrong_host_cannot_read_login_page(local_server):
    response = request(local_server, "GET", "/", headers={"Host": "attacker.example"})
    assert response.status_code == 403
    assert local_server.csrf not in response.text


def test_config_requires_correct_capability(local_server):
    response = request(local_server, "GET", "/config", headers=auth_headers(local_server))
    assert response.status_code == 200
    assert response.json()["projectId"] == "settle-up-sandbox"
    assert "access-control-allow-origin" not in response.headers


@pytest.mark.parametrize("invalid", [
    {"Origin": "https://attacker.example"},
    {"X-Setup-Token": "wrong-token"},
    {"Host": "attacker.example"},
    {"Origin": ""},
])
def test_cross_origin_and_forged_submissions_are_rejected(local_server, monkeypatch, invalid):
    def unexpected(*args):
        pytest.fail("Rejected requests must not contact Firebase")
    monkeypatch.setattr(login, "exchange_session", unexpected)
    headers = auth_headers(local_server) | invalid
    response = request(local_server, "POST", "/complete", headers=headers,
                       json={"refresh_token": "a" * 40})
    assert response.status_code == 403
    assert not local_server.completed
    assert "SETTLEUP_REFRESH_TOKEN" not in local_server.env_file.read_text()


@pytest.mark.parametrize("payload", [
    {}, [], {"refresh_token": "short"},
    {"refresh_token": "x" * 40 + "\nMCP_AUTH_MODE=none"},
    {"refresh_token": "x" * 17000},
])
def test_invalid_payloads_cannot_change_environment(local_server, payload, monkeypatch):
    def unexpected(*args):
        pytest.fail("Invalid payload must not contact Firebase")
    monkeypatch.setattr(login, "exchange_session", unexpected)
    response = request(local_server, "POST", "/complete",
                       headers=auth_headers(local_server), json=payload)
    assert response.status_code == 400
    assert not local_server.completed


def test_verified_session_is_saved_without_touching_other_settings(local_server, monkeypatch):
    rotated = "rotated_sandbox_session_" + "a" * 30
    monkeypatch.setattr(login, "exchange_session", lambda key, token: rotated)
    response = request(local_server, "POST", "/complete",
                       headers=auth_headers(local_server),
                       json={"refresh_token": "a" * 40})
    assert response.status_code == 200
    assert rotated not in response.text
    values = dotenv_values(local_server.env_file)
    assert values["SETTLEUP_REFRESH_TOKEN"] == rotated
    assert values["MCP_AUTH_TOKEN"] == "keep-me"
    assert local_server.completed


def test_failed_verification_does_not_overwrite_session(local_server, monkeypatch):
    login.save_session(local_server.env_file, "existing_session_" + "a" * 30)
    before = local_server.env_file.read_bytes()
    def reject(*args):
        raise login.LoginError("Firebase rejected the sandbox session.")
    monkeypatch.setattr(login, "exchange_session", reject)
    response = request(local_server, "POST", "/complete",
                       headers=auth_headers(local_server),
                       json={"refresh_token": "a" * 40})
    assert response.status_code == 400
    assert local_server.env_file.read_bytes() == before


def test_save_session_preserves_comments_and_removes_duplicate_seeds(tmp_path):
    env = tmp_path / ".env"
    env.write_text("# private\nSETTLEUP_REFRESH_TOKEN=old\nOTHER='value'\nSETTLEUP_REFRESH_TOKEN=duplicate\n")
    login.save_session(env, "valid_session_" + "a" * 40)
    assert env.read_text().count("SETTLEUP_REFRESH_TOKEN=") == 1
    assert "# private\n" in env.read_text()
    assert dotenv_values(env)["OTHER"] == "value"


@pytest.mark.parametrize("status,body", [
    (400, {"error": {"message": "sensitive-upstream-error"}}),
    (200, {"project_id": "another-project", "id_token": "secret-id", "user_id": "u", "refresh_token": "secret-refresh"}),
    (200, {"project_id": login.SANDBOX_PROJECT_NUMBER}),
    (200, []),
])
def test_wrong_project_and_upstream_errors_are_safe(monkeypatch, status, body):
    monkeypatch.setattr(login.httpx, "post", lambda *a, **kw: httpx.Response(status, json=body))
    with pytest.raises(login.LoginError) as caught:
        login.exchange_session("private-api-key", "private-refresh-token")
    assert "private-" not in str(caught.value)
    assert "sensitive-upstream" not in str(caught.value)
    assert "secret-" not in str(caught.value)


def test_exchange_keeps_rotated_token(monkeypatch):
    body = {"project_id": login.SANDBOX_PROJECT_NUMBER, "id_token": "id",
            "user_id": "user", "refresh_token": "rotated-token"}
    monkeypatch.setattr(login.httpx, "post", lambda *a, **kw: httpx.Response(200, json=body))
    assert login.exchange_session("key", "seed") == "rotated-token"


def test_live_environment_is_refused(tmp_path):
    env = tmp_path / ".env"
    env.write_text("SETTLEUP_FIREBASE_API_KEY=test\nSETTLEUP_BASE_URL=https://settle-up-live.firebaseio.com\n")
    with pytest.raises(login.LoginError, match="sandbox only"):
        login.LocalLoginServer(env, port=0)


def test_save_rejects_environment_injection(tmp_path):
    env = tmp_path / ".env"
    env.write_text("MCP_AUTH_MODE=token\n")
    original = env.read_bytes()
    with pytest.raises(login.LoginError):
        login.save_session(env, "a" * 40 + "\nMCP_AUTH_MODE=none")
    assert env.read_bytes() == original


def test_login_page_supplies_origin_required_by_google(local_server):
    response = request(local_server, "GET", "/")
    assert response.status_code == 200
    assert response.headers["referrer-policy"] == "no-referrer-when-downgrade"
    assert "test-key" not in response.text


def test_network_failure_does_not_disclose_credential_url(monkeypatch):
    def fail(*args, **kwargs):
        raise httpx.ConnectError("https://example.invalid/?key=private-key")
    monkeypatch.setattr(login.httpx, "post", fail)
    with pytest.raises(login.LoginError) as caught:
        login.exchange_session("private-key", "private-refresh-token")
    assert "private-" not in str(caught.value)
    assert caught.value.__suppress_context__
