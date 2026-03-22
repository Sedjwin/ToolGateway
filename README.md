# ToolGateway

`ToolGateway` is the tool control plane for the local AI stack.

## What it does

- Registers tools and tracks lifecycle state
- Enforces per-agent grants at runtime
- Applies optional incoming and outgoing filters (first-match by priority)
- Executes tools (built-in `echo`, `http` wrapper)
- Logs full execution boundary:
  - incoming payload
  - filtered request
  - raw tool response
  - filtered response

## API overview

- `GET /health`
- `POST /tools` (admin)
- `PUT /tools/{tool_id}/grants` (admin)
- `POST /tools/{tool_id}/filters` (admin)
- `POST /tools/requests` (admin)
- `POST /execute` (service key, normal agent path)
- `POST /admin/execute` (admin test path)
- `GET /logs/executions` (admin)

## Auth headers

- Admin operations: `X-Admin-Key`
- Service execution path: `X-Service-Key`

## Local run

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
./start.sh
```

## Tests

```bash
source .venv/bin/activate
pytest -q
```
