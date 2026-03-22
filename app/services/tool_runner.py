from __future__ import annotations

from typing import Any

import httpx

from app.config import settings
from app.models import Tool


async def run_tool(tool: Tool, payload: dict[str, Any]) -> dict[str, Any]:
    if tool.kind == "echo":
        return {"echo": payload}

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
