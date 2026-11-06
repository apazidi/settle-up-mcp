# Connect a personal Settle Up account to ChatGPT

This fork adds Google OAuth for MCP clients (upstream issue #2). It remains
single-account: every authorized call uses the one Settle Up account configured
on the server. `MCP_GOOGLE_ALLOWED_EMAIL` is mandatory and restricts access to
the owner. This does not implement multi-tenancy (issue #1).

## Two separate logins

1. **ChatGPT → this MCP server:** Google OAuth through FastMCP's OAuth proxy.
   FastMCP handles PKCE, client registration, consent, token signing and refresh.
   The server also checks the verified owner's email and Google client ID.
2. **This server → Settle Up:** Firebase Authentication using email/password
   or a Firebase refresh token from the owner's Settle Up session. The developer
   API key identifies the app; it does not sign in a user.

Signing into the sandbox web app through Google does not configure the MCP
server's Google OAuth client.

## 1. Prepare Settle Up in the sandbox

Register an application in the [Settle Up developer portal](https://developers.settleup.io/).
Put its sandbox API key in `SETTLEUP_FIREBASE_API_KEY`. Keep
`SETTLEUP_BASE_URL=https://settle-up-sandbox.firebaseio.com`.

Use the [sandbox web app](https://settle-up-sandbox-app.web.app/) to create a test
group with fictitious expenses. Choose one server login method:

- Email/password: set `SETTLEUP_EMAIL` and `SETTLEUP_PASSWORD`.
- Existing OAuth account: set `SETTLEUP_REFRESH_TOKEN` to a Firebase refresh
  token from an authorized sign-in to that same Settle Up environment.
  Email/password can stay empty. This must be the **Firebase refresh token**,
  not a Google access token, ID token, or developer API key.

This version accepts an existing Firebase session; it does not yet provide
an interactive Settle Up login/bootstrap screen. Do not paste session tokens
into chat, issues, source code or screenshots. Enter them directly into your
local secret store or untracked `.env`. Sandbox tokens cannot access live data.

Firebase token rotation is followed in memory. The configured seed token is
not overwritten. If it is revoked or stops working after a restart, sign in
again and replace the secret. Refresh errors never switch an explicitly
configured OAuth session to another email/password identity.

## 2. Configure the MCP server's Google OAuth application

In your own Google Cloud project, create an OAuth **Web application** client.
Request only `openid` and `https://www.googleapis.com/auth/userinfo.email`.
Add the owner as a test user if the Google OAuth application is in testing.

Set its authorized redirect URI to `https://YOUR-MCP-HOST/auth/callback`.
The public origin must use HTTPS; mount this server at the origin root.

Configure these settings in the untracked `.env`:

| Setting | Value |
| --- | --- |
| `MCP_AUTH_MODE` | `google` |
| `MCP_AUTH_TOKEN` | Empty |
| `MCP_PUBLIC_URL` | Your HTTPS origin |
| `MCP_GOOGLE_CLIENT_ID` | Your Google OAuth client ID |
| `MCP_GOOGLE_CLIENT_SECRET` | Its client secret |
| `MCP_GOOGLE_ALLOWED_EMAIL` | The owner's verified Google email |
| `MCP_OAUTH_SIGNING_KEY` | A random, stable signing secret |
| `MCP_OAUTH_CLIENT_REDIRECT_URIS` | Exact callback URL shown by ChatGPT |

Generate the signing secret locally with `secrets.token_urlsafe(48)`. Keep it
stable across restarts. These Google client credentials belong to this MCP
server; do not substitute Settle Up's Google client ID or Firebase API key.

The ChatGPT callback is **different** from Google's `/auth/callback`. Copy the
exact callback displayed by ChatGPT into `MCP_OAUTH_CLIENT_REDIRECT_URIS`;
comma-separate additional exact HTTPS callbacks if needed. Wildcards are
rejected. Recreate the container after changing configuration.

## 3. Run with persistent OAuth state

Copy `.env.example` to `.env`, fill in the values locally, then run:

```sh
docker compose up --build -d
curl http://127.0.0.1:8000/health
```

Docker publishes port 8000 on loopback. Put an HTTPS reverse proxy in front of
it. Route the entire origin, including `/.well-known/*`, `/authorize`,
`/token`, `/register`, `/auth/callback` and `/mcp`, to the application.

Preserve the OAuth state volume. It contains encrypted FastMCP client/session
state; protect and back it up together with the signing key.

Outside Docker, set `FASTMCP_HOME` to a persistent private directory outside
the source checkout. Set environment variables before starting
`python -m settleup_mcp.server`; that command does not load `.env` automatically.
Docker Compose does load the `.env` substitutions.

The health endpoint confirms that the process is running. It does not prove
that Settle Up credentials or the complete OAuth flow work.

## 4. Connect and test in ChatGPT

Follow the current [OpenAI connection guide](https://developers.openai.com/plugins/deploy/connect-chatgpt).
Add the custom MCP server using `https://YOUR-MCP-HOST/mcp` and OAuth.
Account/workspace permissions apply. Sign in with the permitted Google account.

First list groups, members and expenses in the sandbox. Then explicitly add,
edit and delete a fictitious expense and verify it in the sandbox app.
Test expiry/refresh, reconnection after a server restart, and rejection of
another Google account. Check browser and phone separately.

Offline tests cover discovery, PKCE rejection, callback restrictions, owner
policy, HTTP token protection and Firebase refresh behavior. They do **not**
establish that Google or ChatGPT has approved/configured this deployment.
A real end-to-end connection requires your OAuth client, sandbox secrets and
HTTPS host before requesting a live key.

## Other modes and migration

`MCP_AUTH_MODE=token` preserves static bearer-token clients. It is the default
and now requires `MCP_AUTH_TOKEN`; missing credentials stop startup.

For isolated local tests only, explicitly set `MCP_AUTH_MODE=none` and
`MCP_HOST=127.0.0.1`. Anonymous mode is refused on a wildcard/public listener
and is not usable with the default Compose listener. Never expose it through
a public proxy.

## References

- [Settle Up API](https://api.settleup.io/)
- [OpenAI MCP authentication](https://developers.openai.com/plugins/build/auth)
- [FastMCP Google provider](https://gofastmcp.com/integrations/google)
- [Upstream issue #2](https://github.com/rithviknishad/settle-up-mcp/issues/2)
