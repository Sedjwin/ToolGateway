"""Tool filter management and dry-run testing."""
from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_admin_principal
from app.database import get_db
from app.models import Tool, ToolFilter
from app.schemas import (
    FilterDryRunRequest,
    ToolFilterCreate,
    ToolFilterOut,
    ToolFilterUpdate,
)
from app.services.filter_engine import apply_first_matching_filter

router = APIRouter(prefix="/api/tools", tags=["filters"])
logger = logging.getLogger(__name__)


def _filter_out(f: ToolFilter) -> ToolFilterOut:
    return ToolFilterOut(
        id=f.id,
        tool_id=f.tool_id,
        name=f.name,
        phase=f.phase,
        priority=f.priority,
        scope=f.scope,
        principals=json.loads(f.principals_json or "[]"),
        filter_type=f.filter_type,
        action=f.action,
        transparent=f.transparent,
        enabled=f.enabled,
        config=json.loads(f.config_json or "{}"),
        created_at=f.created_at,
    )


@router.get("/{tool_id}/filters", response_model=list[ToolFilterOut])
async def list_filters(tool_id: str, db: AsyncSession = Depends(get_db)):
    tool = await db.get(Tool, tool_id)
    if not tool:
        raise HTTPException(404, "Tool not found")
    result = await db.execute(
        select(ToolFilter)
        .where(ToolFilter.tool_id == tool_id)
        .order_by(ToolFilter.phase.asc(), ToolFilter.priority.asc(), ToolFilter.id.asc())
    )
    return [_filter_out(f) for f in result.scalars().all()]


@router.post("/{tool_id}/filters", response_model=ToolFilterOut, status_code=201)
async def create_filter(
    tool_id: str,
    body: ToolFilterCreate,
    principal: dict = Depends(get_admin_principal),
    db: AsyncSession = Depends(get_db),
):
    tool = await db.get(Tool, tool_id)
    if not tool:
        raise HTTPException(404, "Tool not found")

    # Merge action into config for the engine
    config = dict(body.config)
    config.setdefault("action", body.action)

    f = ToolFilter(
        tool_id=tool_id,
        name=body.name,
        phase=body.phase,
        priority=body.priority,
        scope=body.scope,
        principals_json=json.dumps(body.principals),
        filter_type=body.filter_type,
        action=body.action,
        transparent=body.transparent,
        enabled=body.enabled,
        config_json=json.dumps(config),
    )
    db.add(f)
    await db.commit()
    await db.refresh(f)
    logger.info("Filter '%s' created on tool %s by %s", body.name, tool.name, principal["username"])
    return _filter_out(f)


@router.patch("/{tool_id}/filters/{filter_id}", response_model=ToolFilterOut)
async def update_filter(
    tool_id: str,
    filter_id: int,
    body: ToolFilterUpdate,
    principal: dict = Depends(get_admin_principal),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(ToolFilter).where(ToolFilter.tool_id == tool_id, ToolFilter.id == filter_id)
    )
    f = result.scalar_one_or_none()
    if not f:
        raise HTTPException(404, "Filter not found")

    if body.name is not None:
        f.name = body.name
    if body.priority is not None:
        f.priority = body.priority
    if body.scope is not None:
        f.scope = body.scope
    if body.principals is not None:
        f.principals_json = json.dumps(body.principals)
    if body.action is not None:
        f.action = body.action
    if body.transparent is not None:
        f.transparent = body.transparent
    if body.enabled is not None:
        f.enabled = body.enabled
    if body.config is not None:
        config = dict(body.config)
        config.setdefault("action", f.action)
        f.config_json = json.dumps(config)

    await db.commit()
    await db.refresh(f)
    logger.info("Filter %d updated on tool %s by %s", filter_id, tool_id, principal["username"])
    return _filter_out(f)


@router.delete("/{tool_id}/filters/{filter_id}", status_code=204)
async def delete_filter(
    tool_id: str,
    filter_id: int,
    principal: dict = Depends(get_admin_principal),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(ToolFilter).where(ToolFilter.tool_id == tool_id, ToolFilter.id == filter_id)
    )
    f = result.scalar_one_or_none()
    if not f:
        raise HTTPException(404, "Filter not found")
    await db.delete(f)
    await db.commit()
    logger.info("Filter %d deleted from tool %s by %s", filter_id, tool_id, principal["username"])


@router.post("/{tool_id}/filters/{filter_id}/dry-run")
async def dry_run_filter(
    tool_id: str,
    filter_id: int,
    body: FilterDryRunRequest,
    _: dict = Depends(get_admin_principal),
    db: AsyncSession = Depends(get_db),
):
    """Test a filter against a sample payload without executing the tool."""
    result = await db.execute(
        select(ToolFilter).where(ToolFilter.tool_id == tool_id, ToolFilter.id == filter_id)
    )
    f = result.scalar_one_or_none()
    if not f:
        raise HTTPException(404, "Filter not found")

    tool = await db.get(Tool, tool_id)
    tool_name = tool.name if tool else tool_id

    decision, _ = await apply_first_matching_filter(
        filters=[f],
        phase=f.phase,
        payload=body.payload,
        tool_name=tool_name,
        principal_type=body.principal_type,
        principal_id=body.principal_id,
        session_id=body.session_id,
    )

    return {
        "filter_id": filter_id,
        "filter_name": f.name,
        "phase": f.phase,
        "decision": decision.status,
        "reason": decision.reason,
        "output_payload": decision.payload,
        "filter_type": decision.filter_type,
        "transparency_disclosed": decision.transparency_disclosed,
    }
