# ToolGateway

Tool control plane for the local AI stack. Manages tool registry, approval workflow, execution policy, and full audit logging.

**Port:** `13377` (external) / `8006` (internal)

---

## Overview

- **Tool registry** — register tools (HTTP, echo), track versions, manage lifecycle state
- **SkillMD** — markdown instructions stored per tool; fetched by AgentManager when enabling a tool for an agent
- **Approval workflow** — all tools require admin approval before execution; new versions reset to pending
- **Grant model** — per-principal execution permissions with variable overrides
- **Policy filters** — incoming and outgoing filter pipeline (logical rules or AI-evaluated checks)
- **Execution logging** — full audit trail at the ToolGateway boundary
- **Admin panel** — browser UI at `/`

---

## Service Boundaries

| Service | Controls |
|---------|---------|
| `AIGateway` | Models, provider routing, LLM requests |
| `ToolGateway` | Tool registry, grants, filters, execution |
| `AgentManager` | Agent identity, session orchestration, tool calling |

`AgentManager` enables tools per agent (caching SkillMD at config time) and calls `POST /api/execute` at inference time using the agent's `um_api_key`.

---

## Configuration

Set via environment variables or `.env`:

| Variable | Default | Description |
|----------|---------|-------------|
| `TOOLGATEWAY_HOST` | `127.0.0.1` | Listen address |
| `TOOLGATEWAY_PORT` | `13377` | Listen port |
| `TOOLGATEWAY_DATABASE_URL` | `sqlite+aiosqlite:///./data/toolgateway.db` | Database |
| `TOOLGATEWAY_USERMANAGER_URL` | `http://localhost:8005` | UserManager base URL |
| `TOOLGATEWAY_AIGATEWAY_URL` | `http://localhost:8001` | AIGateway (for agent-evaluated filters) |
| `TOOLGATEWAY_AGENTMANAGER_URL` | `http://localhost:8003` | AgentManager (for agent dropdown in admin UI) |

---

## Authentication

All endpoints that require auth accept:

- **JWT Bearer** — `Authorization: Bearer <token>` (from UserManager `/auth/login`)
- **API key** — `Authorization: Bearer <key>` (agent principals, from AgentManager `um_api_key`)

Admin endpoints additionally require `is_admin=True` on the validated principal.

---

## API Reference

### Tools

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/api/tools` | None | List all tools |
| POST | `/api/tools` | Admin | Register a new tool |
| GET | `/api/tools/{id}` | None | Get tool detail |
| PATCH | `/api/tools/{id}` | Admin | Update tool state/config |
| DELETE | `/api/tools/{id}` | Admin | Retire tool |
| GET | `/api/tools/{id}/versions` | None | List versions |
| POST | `/api/tools/{id}/versions` | Admin | Add a version (resets to pending_review) |
| POST | `/api/tools/{id}/versions/{vid}/approve` | Admin | Approve a version |

**Tool fields include:**

| Field | Description |
|-------|-------------|
| `skill_md` | Markdown instructions for the LLM on how/when to call this tool. Fetched by AgentManager when enabling the tool for an agent. Edit via the tool detail panel in the admin UI. |

### Grants

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/api/grants` | Principal | List grants — admins see all; non-admins see own grants only |
| POST | `/api/grants` | Admin | Create a grant |
| PATCH | `/api/grants/{id}` | Admin | Update enabled state / variable overrides |
| DELETE | `/api/grants/{id}` | Admin | Revoke a grant |

### Agents

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/api/agents` | Admin | List agents (proxied from AgentManager) — used by admin UI grant creation |

### Filters

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/api/tools/{id}/filters` | None | List filters on a tool |
| POST | `/api/tools/{id}/filters` | Admin | Create a filter |
| PATCH | `/api/tools/{id}/filters/{fid}` | Admin | Update a filter |
| DELETE | `/api/tools/{id}/filters/{fid}` | Admin | Delete a filter |
| POST | `/api/tools/{id}/filters/{fid}/dry-run` | Admin | Test a filter against a sample payload |

### Execution

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/api/execute` | Principal | Execute a tool (validates grant + runs filter pipeline) |
| POST | `/api/admin/execute` | Admin | Admin test execution |

**Request:**
```json
{
  "tool_name": "email",
  "payload": {"destination": "user@example.com", "body": "Hello"},
  "session_id": "optional",
  "originating_user_id": "optional"
}
```

**Response (success):**
```json
{
  "status": "ok",
  "request_id": "...",
  "tool": "email",
  "principal": "agent:42",
  "data": { "http_status": 200 }
}
```

**Response (rejected):**
```json
{
  "status": "rejected",
  "request_id": "...",
  "tool": "email",
  "principal": "agent:42",
  "reason": "Only @ourpersonalemail.com is permitted",
  "filter_type": "logical",
  "filter_name": "domain-restriction"
}
```

### Logs

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/api/logs` | Admin | List execution logs (filter: tool_id, principal_id, status) |
| GET | `/api/logs/{id}` | Admin | Single log entry |

### Install Requests

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/api/requests` | Admin | List all requests |
| POST | `/api/requests` | Any | Submit a tool install request |
| POST | `/api/requests/{id}/approve` | Admin | Approve a request |
| POST | `/api/requests/{id}/reject` | Admin | Reject a request |

### Stats & Health

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/api/stats` | Admin | Dashboard stats |
| GET | `/health` | None | Health check |

---

## Tool Lifecycle

```
requested → pending_review → quarantined → approved → assignable → granted → active → suspended/blocked → retired
```

A new tool version resets the tool to `pending_review` — an admin must re-approve even for the same tool.

---

## Filter Pipeline

Every tool call passes through two filter phases:

1. **Incoming** — applied before tool execution (request shaping, request blocking)
2. **Outgoing** — applied after tool execution (response shaping, response blocking)

Only the **highest-priority** (lowest number) matching filter per phase is applied.

### Filter Types

**Logical** — deterministic, parameter-based conditions. Available operators:
`contains`, `not_contains`, `matches`, `equals`, `in_list`, `not_in_list`,
`starts_with`, `not_starts_with`, `ends_with`, `not_ends_with`

Example: deny emails outside @ourpersonalemail.com
```json
{
  "conditions": [{"target": "destination", "operator": "not_ends_with", "value": "@ourpersonalemail.com"}],
  "join": "AND",
  "action": "deny",
  "message": "Only @ourpersonalemail.com is permitted"
}
```

**Agent-evaluated** — AI policy check via AIGateway evaluator agent:
```json
{
  "evaluator_agent_id": "moderation_offline",
  "policy_question": "Does this message contain content that could embarrass the organisation?",
  "fallback": "deny"
}
```

### Filter Scope

- `all` — applies to every principal
- `selected` — applies only to the listed principals (`["agent:42", "human:1"]`)

---

## SkillMD

Each tool has a `skill_md` field — markdown instructions telling the LLM when and how to call the tool. This is edited in the tool detail panel of the admin UI and fetched by AgentManager when an admin enables the tool for an agent. The content is cached on the agent record and injected into the system prompt at inference time, so no runtime ToolGateway call is needed per message.

---

## Admin Panel

Browser UI at `/`. Tabs:

- **Dashboard** — stats, recent executions
- **Tools** — register tools, manage state, approve versions, edit SkillMD
- **Approval Queue** — tools awaiting review
- **Grants** — per-principal execution permissions (agent dropdown auto-populated from AgentManager)
- **Filters** — filter wizard (logical + agent-evaluated), dry-run panel
- **Logs** — full execution audit trail
- **Requests** — tool install requests with approve/reject

---

## Running

```bash
cd ToolGateway
pip install -r requirements.txt
cp .env.example .env
./start.sh
```

Or via systemd:
```bash
sudo cp toolgateway.service /etc/systemd/system/
sudo systemctl enable --now toolgateway.service
```

## Tests

```bash
source .venv/bin/activate
pytest -q
```
