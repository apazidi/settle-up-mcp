"""One-time sandbox Google sign-in on loopback; never log credentials."""
from __future__ import annotations

import argparse
import hmac
import json
import logging
import re
import secrets
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import httpx
from dotenv import dotenv_values

from settleup_mcp.config import REFRESH_URL, SANDBOX_BASE_URL

SANDBOX_PROJECT_NUMBER = "84712828597"
MAX_BODY = 16384


class LoginError(RuntimeError):
    """A safe error that contains no upstream response or credentials."""


def exchange_session(api_key: str, refresh_token: str) -> str:
    """Verify the session with Firebase and keep its latest refresh token."""
    try:
        response = httpx.post(
            REFRESH_URL,
            params={"key": api_key},
            data={"grant_type": "refresh_token", "refresh_token": refresh_token},
            timeout=20,
        )
        if response.status_code != 200:
            raise LoginError("Firebase rejected the sandbox session. Sign in again.")
        data = response.json()
        if (
            not isinstance(data, dict)
            or data.get("project_id") != SANDBOX_PROJECT_NUMBER
            or not data.get("user_id")
            or not data.get("id_token")
            or not isinstance(data.get("refresh_token"), str)
            or not data["refresh_token"]
        ):
            raise LoginError("Firebase did not return a valid sandbox session.")
        return data["refresh_token"]
    except (httpx.HTTPError, ValueError):
        raise LoginError("Could not verify the session with Firebase. Retry.") from None


def save_session(env_file: Path, token: str) -> None:
    """Update only the session in an existing local secret file."""
    if not isinstance(token, str) or not re.fullmatch(r"[A-Za-z0-9._~-]{20,12000}", token):
        raise LoginError("Firebase returned an invalid session token.")
    if not env_file.is_file() or env_file.is_symlink():
        raise LoginError("The local environment file must already exist.")
    # In-place write preserves the existing Windows ACL, unlike replacing a
    # file with a temporary file inherited from a different directory.
    from io import StringIO
    from dotenv.parser import parse_stream

    original = env_file.read_text(encoding="utf-8")
    parts = []
    replacement = "SETTLEUP_REFRESH_TOKEN='" + token.replace("'", "\\'") + "'\n"
    replaced = False
    for binding in parse_stream(StringIO(original)):
        if binding.key == "SETTLEUP_REFRESH_TOKEN":
            if not replaced:
                parts.append(replacement)
                replaced = True
        else:
            parts.append(binding.original.string)
    content = "".join(parts)
    if not replaced:
        content += ("\n" if content and not content.endswith("\n") else "") + replacement
    with env_file.open("r+", encoding="utf-8", newline="") as handle:
        handle.write(content)
        handle.truncate()


class LocalLoginServer(ThreadingHTTPServer):
    """Bound exclusively to IPv4 loopback, with a per-run CSRF capability."""

    def __init__(self, env_file: Path, port: int = 3000):
        values = dotenv_values(env_file)
        if values.get("SETTLEUP_BASE_URL", SANDBOX_BASE_URL) != SANDBOX_BASE_URL:
            raise LoginError("This login helper supports the sandbox only.")
        key = values.get("SETTLEUP_FIREBASE_API_KEY", "")
        if not key:
            raise LoginError("Set SETTLEUP_FIREBASE_API_KEY in the local environment file.")
        self.api_key = key
        self.env_file = env_file
        self.csrf = secrets.token_urlsafe(32)
        self.completed = False
        self.completion_lock = threading.Lock()
        super().__init__(("127.0.0.1", port), LoginHandler)
        self.origin = f"http://localhost:{self.server_port}"
        self.expected_host = f"localhost:{self.server_port}"


class LoginHandler(BaseHTTPRequestHandler):
    server: LocalLoginServer

    def log_message(self, format: str, *args: Any) -> None:
        # Paths, request bodies and SDK URLs can carry credentials.
        pass

    def setup(self) -> None:
        super().setup()
        self.connection.settimeout(10)

    def reply(self, status: int, body: bytes, content_type: str = "application/json") -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        # The hosted Firebase Google sign-in needs the localhost referrer. The login
        # page URL is always exactly / and never contains credentials.
        self.send_header("Referrer-Policy", "no-referrer-when-downgrade"
                         if self.path == "/" else "no-referrer")
        self.end_headers()
        self.wfile.write(body)

    def valid_host(self) -> bool:
        return self.headers.get("Host") == self.server.expected_host

    def authorized(self) -> bool:
        provided = self.headers.get("X-Setup-Token", "")
        return self.valid_host() and provided.isascii() and hmac.compare_digest(provided, self.server.csrf)

    def do_GET(self) -> None:
        if not self.valid_host():
            self.reply(403, b'{"error":"Invalid host"}')
            return
        if self.path == "/":
            page = Path(__file__).with_name("local_login.html").read_text(encoding="utf-8")
            page = page.replace("__SETUP_TOKEN__", json.dumps(self.server.csrf))
            self.reply(200, page.encode("utf-8"), "text/html; charset=utf-8")
        elif self.path == "/config" and self.authorized():
            body = {
                "apiKey": self.server.api_key,
                "authDomain": "settle-up-sandbox.firebaseapp.com",
                "projectId": "settle-up-sandbox",
            }
            self.reply(200, json.dumps(body).encode())
        else:
            self.reply(404, b'{"error":"Not found"}')

    def do_POST(self) -> None:
        # Drain bounded request bodies before rejecting them, so Windows does
        # not reset the socket with an unread body and discard the response.
        try:
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length) if 0 < length <= 65536 else b""
        except (ValueError, OSError):
            self.reply(400, b'{"error":"Invalid request body"}')
            return
        if (
            self.path != "/complete"
            or not self.authorized()
            or self.headers.get("Origin") != self.server.origin
        ):
            self.reply(403, b'{"error":"Invalid local request"}')
            return
        if self.server.completed:
            self.reply(409, b'{"error":"Sign-in already completed"}')
            return
        try:
            if not 0 < length <= MAX_BODY or self.headers.get("Content-Type") != "application/json":
                raise ValueError
            body = json.loads(raw)
            token = body.get("refresh_token") if isinstance(body, dict) else None
            if not isinstance(token, str) or not 20 <= len(token) <= 12000:
                raise ValueError
            # Reject newlines/control characters before writing dotenv syntax.
            if not re.fullmatch(r"[A-Za-z0-9._~-]{20,12000}", token):
                raise ValueError
        except (ValueError, OSError):
            self.reply(400, b'{"error":"Invalid session payload"}')
            return
        with self.server.completion_lock:
            if self.server.completed:
                self.reply(409, b'{"error":"Sign-in already completed"}')
                return
            try:
                verified = exchange_session(self.server.api_key, token)
                save_session(self.server.env_file, verified)
            except LoginError as error:
                self.reply(400, json.dumps({"error": str(error)}).encode())
                return
            except OSError:
                self.reply(500, b'{"error":"Could not save the local session"}')
                return
            self.server.completed = True
        self.reply(200, b'{"ok":true}')
        threading.Thread(target=self.server.shutdown, daemon=True).start()



def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    parser.add_argument("--port", type=int, default=3000)
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    for name in ("httpx", "httpcore"):
        logging.getLogger(name).setLevel(logging.CRITICAL)
    try:
        with LocalLoginServer(args.env_file.resolve(), args.port) as server:
            timer = threading.Timer(args.timeout, server.shutdown)
            timer.daemon = True
            timer.start()
            print(f"Open {server.origin} and sign in to the sandbox.", flush=True)
            if not args.no_browser:
                webbrowser.open(server.origin)
            try:
                server.serve_forever(poll_interval=0.2)
            finally:
                timer.cancel()
            print("Sandbox session saved locally." if server.completed else "Sign-in timed out.", flush=True)
    except (LoginError, OSError) as error:
        # OSError details can expose local configuration; only safe errors are shown.
        message = str(error) if isinstance(error, LoginError) else "Cannot start local sign-in. Check the port and local file."
        parser.exit(1, message + "\n")


if __name__ == "__main__":
    main()
