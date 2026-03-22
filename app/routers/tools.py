"""Tool registry, version, and state management."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_admin_principal
from app.database import get_db
from app.models import Tool, ToolVersion
from app.schemas import (
    ToolCreate,
    ToolOut,
    ToolUpdate,
    ToolVersionCreate,
    ToolVersionOut,
)

router = APIRouter(prefix="/api/tools", tags=["tools"])
logger = logging.getLogger(__name__)

VALID_STATES = {
    "requested", "pending_review", "quarantined", "approved",
    "assignable", "granted", "active", "suspended", "blocked", "retired",
}


def _tool_out(tool: Tool) -> ToolOut:
    return ToolOut(
        tool_id=tool.tool_id,
        name=tool.name,
        description=tool.description,
        category=tool.category,
        kind=tool.kind,
        endpoint_url=tool.endpoint_url,
        method=tool.method,
        state=tool.state,
        enabled=tool.enabled,
        capabilities=json.loads(tool.capabilities_json or "[]"),
        variables=json.loads(tool.variables_json or "{}"),
        metadata=json.loads(tool.metadata_json or "{}"),
        created_at=tool.created_at,
        updated_at=tool.updated_at,
    )


def _version_out(v: ToolVersion) -> ToolVersionOut:
    return ToolVersionOut(
        id=v.id,
        tool_id=v.tool_id,
        version=v.version,
        notes=v.notes,
        state=v.state,
        reviewed_by=v.reviewed_by,
        reviewed_at=v.reviewed_at,
        created_at=v.created_at,
    )


# ── Tool CRUD ─────────────────────────────────────────────────────────────────

@router.get("", response_model=list[ToolOut])
async def list_tools(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Tool).order_by(Tool.created_at.desc()))
    return [_tool_out(t) for t in result.scalars().all()]


@router.post("", response_model=ToolOut, status_code=201)
async def create_tool(
    body: ToolCreate,
    principal: dict = Depends(get_admin_principal),
    db: AsyncSession = Depends(get_db),
):
    existing = await db.execute(select(Tool).where(Tool.name == body.name))
    if existing.scalar_one_or_none():
        raise HTTPException(409, "A tool with that name already exists")

    tool = Tool(
        name=body.name,
        description=body.description,
        category=body.category,
        kind=body.kind,
        endpoint_url=body.endpoint_url,
        method=body.method,
        state=body.state,
        enabled=body.enabled,
        capabilities_json=json.dumps(body.capabilities),
        variables_json=json.dumps(body.variables),
        metadata_json=json.dumps(body.metadata),
    )
    db.add(tool)
    await db.commit()
    await db.refresh(tool)
    logger.info("Tool %s registered by %s", tool.name, principal["username"])
    return _tool_out(tool)


@router.get("/{tool_id}", response_model=ToolOut)
async def get_tool(tool_id: str, db: AsyncSession = Depends(get_db)):
    tool = await db.get(Tool, tool_id)
    if not tool:
        raise HTTPException(404, "Tool not found")
    return _tool_out(tool)


@router.patch("/{tool_id}", response_model=ToolOut)
async def update_tool(
    tool_id: str,
    body: ToolUpdate,
    principal: dict = Depends(get_admin_principal),
    db: AsyncSession = Depends(get_db),
):
    tool = await db.get(Tool, tool_id)
    if not tool:
        raise HTTPException(404, "Tool not found")

    if body.description is not None:
        tool.description = body.description
    if body.category is not None:
        tool.category = body.category
    if body.endpoint_url is not None:
        tool.endpoint_url = body.endpoint_url
    if body.method is not None:
        tool.method = body.method
    if body.state is not None:
        if body.state not in VALID_STATES:
            raise HTTPException(400, f"Invalid state. Valid states: {sorted(VALID_STATES)}")
        tool.state = body.state
    if body.enabled is not None:
        tool.enabled = body.enabled
    if body.capabilities is not None:
        tool.capabilities_json = json.dumps(body.capabilities)
    if body.variables is not None:
        tool.variables_json = json.dumps(body.variables)
    if body.metadata is not None:
        tool.metadata_json = json.dumps(body.metadata)

    await db.commit()
    await db.refresh(tool)
    logger.info("Tool %s updated by %s", tool.name, principal["username"])
    return _tool_out(tool)


@router.delete("/{tool_id}", status_code=204)
async def retire_tool(
    tool_id: str,
    principal: dict = Depends(get_admin_principal),
    db: AsyncSession = Depends(get_db),
):
    """Set tool state to 'retired' and disable it."""
    tool = await db.get(Tool, tool_id)
    if not tool:
        raise HTTPException(404, "Tool not found")
    tool.state = "retired"
    tool.enabled = False
    await db.commit()
    logger.info("Tool %s retired by %s", tool.name, principal["username"])


# ── Version management ────────────────────────────────────────────────────────

@router.get("/{tool_id}/versions", response_model=list[ToolVersionOut])
async def list_versions(tool_id: str, db: AsyncSession = Depends(get_db)):
    tool = await db.get(Tool, tool_id)
    if not tool:
        raise HTTPException(404, "Tool not found")
    result = await db.execute(
        select(ToolVersion)
        .where(ToolVersion.tool_id == tool_id)
        .order_by(ToolVersion.created_at.desc())
    )
    return [_version_out(v) for v in result.scalars().all()]


@router.post("/{tool_id}/versions", response_model=ToolVersionOut, status_code=201)
async def add_version(
    tool_id: str,
    body: ToolVersionCreate,
    principal: dict = Depends(get_admin_principal),
    db: AsyncSession = Depends(get_db),
):
    """
    Add a new version record. New versions start in pending_review and
    reset the tool to pending_review state — a human must re-approve.
    """
    tool = await db.get(Tool, tool_id)
    if not tool:
        raise HTTPException(404, "Tool not found")

    version = ToolVersion(
        tool_id=tool_id,
        version=body.version,
        notes=body.notes,
        state="pending_review",
    )
    db.add(version)
    tool.state = "pending_review"
    tool.enabled = False
    await db.commit()
    await db.refresh(version)
    logger.info("Version %s added to tool %s by %s", body.version, tool.name, principal["username"])
    return _version_out(version)


@router.post("/{tool_id}/versions/{version_id}/approve", response_model=ToolVersionOut)
async def approve_version(
    tool_id: str,
    version_id: int,
    principal: dict = Depends(get_admin_principal),
    db: AsyncSession = Depends(get_db),
):
    """Approve a tool version. Also moves the tool state to 'approved'."""
    result = await db.execute(
        select(ToolVersion).where(
            ToolVersion.id == version_id,
            ToolVersion.tool_id == tool_id,
        )
    )
    version = result.scalar_one_or_none()
    if not version:
        raise HTTPException(404, "Version not found")

    version.state = "approved"
    version.reviewed_by = principal["username"]
    version.reviewed_at = datetime.now(timezone.utc).replace(tzinfo=None)

    tool = await db.get(Tool, tool_id)
    if tool and tool.state in {"pending_review", "quarantined", "requested"}:
        tool.state = "approved"

    await db.commit()
    await db.refresh(version)
    logger.info("Version %s of tool %s approved by %s", version.version, tool_id, principal["username"])
    return _version_out(version)
