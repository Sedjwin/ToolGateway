"""Execute a tool and return its raw result."""
from __future__ import annotations

from typing import Any

import httpx

from app.config import settings
from app.models import Tool


async def run_tool(tool: Tool, payload: dict[str, Any]) -> dict[str, Any]:
    """
    Execute the tool using its kind/endpoint configuration.
    Returns a dict result. Raises on failure.
    """
    if tool.kind == "echo":
        return {"echo": payload}

    if tool.kind == "local":
        # Execution happens in the calling service (AgentManager).
        # ToolGateway handles permission checks and audit logging only.
        return {"proceed": True}

    if tool.kind == "http":
        if not tool.endpoint_url:
            raise ValueError("Tool endpoint_url is required for http tools")

        method = tool.method.upper()
        async with httpx.AsyncClient(timeout=settings.http_timeout_seconds) as client:
            if method == "GET":
                resp = await client.get(tool.endpoint_url, params=payload)
            else:
                resp = await client.request(method, tool.endpoint_url, json=payload)

        content_type = resp.headers.get("content-type", "")
        if "application/json" in content_type:
            result: dict[str, Any] = resp.json()
        else:
            result = {"text": resp.text}
        result["http_status"] = resp.status_code
        return result

    raise ValueError(f"Unsupported tool kind: {tool.kind}")
