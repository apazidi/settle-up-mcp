# Settle Up MCP Server

[![Build and push the image](https://github.com/rithviknishad/settle-up-mcp/actions/workflows/docker.yml/badge.svg)](https://github.com/rithviknishad/settle-up-mcp/actions/workflows/docker.yml)

An MCP server for [Settle Up](https://settleup.io). It lets an AI agent read
your groups, members, expenses, and balances, and add a new expense.

## Tools

| Tool | Action | Read-only |
|---|---|---|
| `settleup_list_groups` | Get your groups | Yes |
| `settleup_list_members` | Get the members of a group | Yes |
| `settleup_list_expenses` | Get the transactions of a group | Yes |
| `settleup_get_balances` | Get who owes what in a group | Yes |
| `settleup_add_expense` | Add a new expense | No |

## Configuration

Copy `.env.example` to `.env`. Then write your values.

| Variable | Purpose |
|---|---|
| `SETTLEUP_EMAIL` | Your Settle Up email |
| `SETTLEUP_PASSWORD` | Your Settle Up password |
| `SETTLEUP_FIREBASE_API_KEY` | The Firebase Web API key |
| `SETTLEUP_BASE_URL` | The API server. The default is the sandbox |
| `MCP_AUTH_TOKEN` | The bearer token that each agent must send |

The [Settle Up API documentation](https://api.settleup.io) gives the API key,
the server URLs, and the sign-in rules. Develop on the sandbox first.

**Caution: If `MCP_AUTH_TOKEN` is empty, the server accepts each request. Set a
token and put HTTPS in front of the server before you deploy it.**

## Run it

```bash
docker compose up -d
curl http://localhost:8000/health
```

The MCP endpoint is `http://localhost:8000/mcp`. It uses the Streamable HTTP
transport.

To use a built image, pull `ghcr.io/rithviknishad/settle-up-mcp:latest`.

## Connect an agent

```json
{
  "mcpServers": {
    "settleup": {
      "url": "http://localhost:8000/mcp",
      "headers": { "Authorization": "Bearer YOUR_TOKEN" }
    }
  }
}
```

## Develop

This project needs Python 3.13, [Pipenv](https://pipenv.pypa.io), and
[direnv](https://direnv.net).

```bash
pipenv install --dev
direnv allow

pipenv run test      # Run the tests.
pipenv run server    # Start the server.
```

## Licence

MIT. See [LICENSE](LICENSE).
