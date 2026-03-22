"""Built-in tool endpoints — lightweight capabilities served by ToolGateway itself."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter

router = APIRouter(prefix="/api/builtins", tags=["builtins"])


@router.get("/time")
async def get_time():
    """Return the current UTC date and time. Used as the backend for the get-time tool."""
    now_utc = datetime.now(timezone.utc)
    return {
        "utc_iso":    now_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "date":       now_utc.strftime("%Y-%m-%d"),
        "time":       now_utc.strftime("%H:%M:%S"),
        "day":        now_utc.strftime("%A"),
        "unix":       int(now_utc.timestamp()),
        "timezone":   "UTC",
    }
