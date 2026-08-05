# Settle Up MCP Server

[![Build and push the image](https://github.com/rithviknishad/settle-up-mcp/actions/workflows/docker.yml/badge.svg)](https://github.com/rithviknishad/settle-up-mcp/actions/workflows/docker.yml)

This server gives Settle Up tools to an AI agent. The agent reads groups,
members, transactions, and balances. The agent can also add an expense.

The server uses FastMCP v4 and the Streamable HTTP transport. It talks to the
Settle Up REST API. The Settle Up API is a Firebase Realtime Database.

## 1. Tools

| Tool | Action | Read-only |
|---|---|---|
| `settleup_list_groups` | Get the groups of the account | Yes |
| `settleup_list_members` | Get the members of a group | Yes |
| `settleup_list_expenses` | Get the transactions of a group | Yes |
| `settleup_get_balances` | Get who owes what in a group | Yes |
| `settleup_add_expense` | Add a new expense | No |

Each list tool has a `limit` value and an `offset` value. The default limit is
50. The maximum limit is 200.

## 2. Configuration

Set each value in an environment variable. Copy `.env.example` to `.env`.

**Caution: Never write a secret in the code. Never commit the `.env` file.**

| Variable | Purpose | Default |
|---|---|---|
| `SETTLEUP_EMAIL` | The Settle Up user email | required |
| `SETTLEUP_PASSWORD` | The Settle Up user password | required |
| `SETTLEUP_FIREBASE_API_KEY` | The Firebase Web API key | required |
| `SETTLEUP_BASE_URL` | The API server | the sandbox |
| `SETTLEUP_TIMEOUT_SECONDS` | The HTTP timeout | 30 |
| `SETTLEUP_TOKEN_REFRESH_MARGIN` | Refresh this many seconds early | 300 |
| `MCP_AUTH_TOKEN` | The bearer token for the agent | empty |
| `MCP_HOST` | The network interface | `0.0.0.0` |
| `MCP_PORT` | The port | 8000 |
| `MCP_PATH` | The MCP endpoint path | `/mcp` |
| `LOG_LEVEL` | The log level | `INFO` |

Environments:

- Sandbox: `https://settle-up-sandbox.firebaseio.com`
- Live: `https://settle-up-live.firebaseio.com`

The sandbox Web API key is public:
`AIzaSyCBsW4lveImpcB92c-cnNg2VQgx9JdijU8`. Ask Settle Up for the live key.

**Caution: Develop on the sandbox first. Do not use real data for a test.**

## 3. Authentication

The server signs in to Firebase with the email and the password. Firebase gives
an ID token and a refresh token. The server adds the ID token to each REST
request.

The ID token expires after 1 hour. The server refreshes the token 300 seconds
before it expires. The server also signs in again if a request gives status 401.

**Caution: The server keeps the Settle Up secrets. It never sends them to the
agent.**

## 4. Agent access

If `MCP_AUTH_TOKEN` is empty, the server accepts each request. Use this mode
for a local test only.

If `MCP_AUTH_TOKEN` holds a value, each agent must send the header
`Authorization: Bearer <token>`. The server rejects each other request.

**Caution: This server gives finance data. Put an HTTPS reverse proxy in front
of the container for a production deployment.**

## 5. Local start

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
set -a && source .env && set +a
.venv/bin/python -m settleup_mcp.server
```

The MCP endpoint is `http://127.0.0.1:8000/mcp`.
The health route is `http://127.0.0.1:8000/health`.

## 6. Container start

### 6.1 Build the image on your machine

```bash
docker build -t settleup-mcp .
docker compose up -d
docker compose ps
curl http://localhost:8000/health
```

### 6.2 Pull the image from GHCR

GitHub Actions builds the image for `linux/amd64` and `linux/arm64`. It pushes
the image to the GitHub Container Registry.

```bash
docker pull ghcr.io/rithviknishad/settle-up-mcp:latest
```

Available tags:

| Tag | Content |
|---|---|
| `latest` | The last commit on the `main` branch |
| `main` | The same image as `latest` |
| `1.2.3`, `1.2`, `1` | A version tag, for example the git tag `v1.2.3` |
| `sha-<commit>` | One exact commit |

To use the image with the compose file, set the `image` value and delete the
`build` value.

The container runs as the non-root user `appuser`. The compose file reads each
secret from the environment at run time. The image holds no secret.

## 7. Continuous integration

The workflow `.github/workflows/docker.yml` does these steps:

1. Run the tests with Python 3.12.
2. Build 1 image. Start a container. Test the `/health` route.
3. Build the image for 2 architectures. Push it to GHCR.
4. Attest the build provenance.

A pull request runs the tests and the build, but it pushes no image.

To make a release, push a version tag:

```bash
git tag v0.1.0
git push origin v0.1.0
```

**Caution: Make the GHCR package public in the repository settings. If the
package stays private, each user needs a token to pull the image.**

## 8. Tests

```bash
.venv/bin/pip install pytest
.venv/bin/python -m pytest
```

The tests use a fake HTTP transport. They make no call to Settle Up.

To test the tools against the sandbox, use the MCP Inspector:

```bash
npx @modelcontextprotocol/inspector
```

Connect the inspector to `http://localhost:8000/mcp`. Use the Streamable HTTP
transport.

## 9. Project structure

```
settleup_mcp/
  server.py      Build the server. Add the health route. Start the server.
  client.py      The REST client. All Settle Up calls stay here.
  auth.py        Sign in. Refresh the ID token.
  models.py      The Pydantic input models.
  config.py      Read the configuration from the environment.
  tools/         One file for each tool group.
```

To add a tool:

1. Add an input model to `models.py`.
2. Add a call to `client.py` if the endpoint is new.
3. Add the tool function to a file in `tools/`.
4. Set the annotations. Use `READ_ONLY` or `WRITE` from `tools/common.py`.

## 10. Data notes

- An amount is a decimal string, for example `"250.50"`.
- An income is an expense with a negative amount.
- A weight gives the share of a member. Use `"1"` for an equal share.
- A member is not a user. A member id is unique in 1 group only.
- The Settle Up server calculates the debts. The server writes them to
  `/debts/<groupId>`.
- `settleup_add_expense` uses the group currency only. It gives an error for
  another currency, because it has no exchange rate.
