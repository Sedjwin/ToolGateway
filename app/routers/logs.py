"""Execution log access."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_admin_principal
from app.database import get_db
from app.models import ToolExecutionLog
from app.schemas import ExecutionLogOut

router = APIRouter(prefix="/api/logs", tags=["logs"])


@router.get("", response_model=list[ExecutionLogOut])
async def list_logs(
    tool_id: str | None = None,
    principal_id: str | None = None,
    status: str | None = None,
    limit: int = 100,
    offset: int = 0,
    _: dict = Depends(get_admin_principal),
    db: AsyncSession = Depends(get_db),
):
    """All execution logs, newest first. Filterable by tool, principal, and status."""
    safe_limit = max(1, min(limit, 1000))
    query = select(ToolExecutionLog).order_by(ToolExecutionLog.created_at.desc())
    if tool_id:
        query = query.where(ToolExecutionLog.tool_id == tool_id)
    if principal_id:
        query = query.where(ToolExecutionLog.principal_id == principal_id)
    if status:
        query = query.where(ToolExecutionLog.status == status)
    query = query.limit(safe_limit).offset(offset)
    result = await db.execute(query)
    return result.scalars().all()


@router.get("/{log_id}", response_model=ExecutionLogOut)
async def get_log(
    log_id: int,
    _: dict = Depends(get_admin_principal),
    db: AsyncSession = Depends(get_db),
):
    log = await db.get(ToolExecutionLog, log_id)
    if not log:
        raise HTTPException(404, "Log entry not found")
    return log
