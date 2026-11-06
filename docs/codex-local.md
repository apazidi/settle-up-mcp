# Local Codex setup on Windows

This uses the sandbox and a loopback HTTP server. The Google sign-in helper is
separate from the Google OAuth provider for hosted ChatGPT connections.

## Local configuration

Create an untracked `.env` from `.env.example` and set the sandbox
`SETTLEUP_FIREBASE_API_KEY`. Keep the sandbox database URL. Select
`MCP_AUTH_MODE=token` and generate an independent random `MCP_AUTH_TOKEN`.

The Firebase Web API key identifies the Settle Up app. The MCP bearer token
protects this local server. Never use one in place of the other, and never put
an actual token in `bearer_token_env_var`: that field takes a variable **name**.

The existing virtual environment must contain the locked project dependencies,
including python-dotenv (already in `Pipfile.lock`). Real credentials stay in
the local `.env` and the local Codex configuration, outside Git.

## Sign in to the sandbox

From the repository root:

```powershell
.\.venv\Scripts\python.exe -m settleup_mcp.local_login
```

Open `http://localhost:3000` in the browser and use the Google account you use
in the sandbox app. This helper deliberately supports only sandbox.

The page uses Firebase's Google popup flow with the project's registered hosted
callback. Direct Google Identity Services and direct redirects to localhost can
be rejected with origin_mismatch or redirect_uri_mismatch, even though the
Settle Up API documentation mentions localhost:3000. Do not assume a listed
Firebase authorized domain is also a Google JavaScript origin or redirect URI.

The Python helper verifies the session with Firebase before updating
`SETTLEUP_REFRESH_TOKEN`. No Google password is entered into the local page.
The SDK keeps its temporary state in memory and signs out after saving.
The login page URL contains no credentials. It uses Google's documented
localhost referrer policy so the hosted sign-in can identify its caller.
API responses retain the no-referrer policy.

The helper listens only on IPv4 loopback, requires the exact localhost Host,
checks the Origin and a random per-run CSRF token, limits request size, and
stops after success or 15 minutes. It does not log tokens or raw HTTP errors.
Do not proxy the helper publicly. Protect the `.env` with user-only file
permissions; updating the session preserves the file's existing Windows ACL.

If the page has expired, run the command again and reload it. If browser
privacy settings prevent sign-in, inspect only redacted diagnostics; browser
popup titles and URLs can contain credentials.

## Start the MCP server

```powershell
.\scripts\start-local.ps1
```

This starts a hidden process on `http://127.0.0.1:8000/mcp`, reads `.env`,
and writes logs and the process ID under ignored `.local/`.
The launcher expects the local sandbox to use port 8000.
For a foreground run:

```powershell
.\.venv\Scripts\python.exe -m settleup_mcp.local_server
```

The health route confirms process readiness, not successful Settle Up sign-in.

## Connect Codex

Add one server entry to the user's local `~/.codex/config.toml`:

```toml
[mcp_servers.settleup_sandbox]
url = "http://127.0.0.1:8000/mcp"
http_headers = { Authorization = "Bearer REPLACE_LOCALLY_WITH_MCP_AUTH_TOKEN" }
```

The header must use the same MCP token as `.env`. Keep this user configuration
private and out of Git. Alternatively use
`bearer_token_env_var = "SETTLEUP_MCP_TOKEN"` and make that variable available
to the Codex process; do not configure both approaches.

Reload MCP servers or restart Codex and open a new chat. Ask it to list sandbox
groups. Test reading before asking it to change a fictitious expense.
The HTTP server must remain running for tools to work.

For Windows sign-in startup, create a user Startup shortcut with target
`<repo>\.venv\Scripts\pythonw.exe`, arguments `-m settleup_mcp.local_server`,
and working directory `<repo>`. This runs without a console and writes
diagnostics to ignored `.local/server-startup.log`. The shortcut does not
write `server.pid`; the PowerShell launcher does. Remove the shortcut to
disable automatic startup. The repository does not install startup entries
automatically.

## Hosted ChatGPT later

See [ChatGPT setup](chatgpt.md) for HTTPS and MCP Google OAuth. Sandbox sessions
and developer keys do not grant access to live groups.

Sources:
- [Settle Up API and sandbox Google client](https://api.settleup.io/)
- [Firebase Google popup sign-in](https://firebase.google.com/docs/auth/web/google-signin)
- [Google localhost origin and referrer requirements](https://developers.google.com/identity/gsi/web/guides/get-google-api-clientid)
- [Codex MCP configuration](https://learn.chatgpt.com/docs/extend/mcp?surface=cli)
