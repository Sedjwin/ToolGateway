"""Tool grant management — who can execute which tool."""
from __future__ import annotations

import json
import logging

import httpx
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_admin_principal, get_principal
from app.config import settings
from app.database import get_db
from app.models import Tool, ToolGrant
from app.schemas import ToolGrantCreate, ToolGrantOut, ToolGrantUpdate

router = APIRouter(prefix="/api/grants", tags=["grants"])
logger = logging.getLogger(__name__)


def _grant_out(grant: ToolGrant) -> ToolGrantOut:
    return ToolGrantOut(
        id=grant.id,
        tool_id=grant.tool_id,
        principal_type=grant.principal_type,
        principal_id=grant.principal_id,
        principal_name=grant.principal_name,
        enabled=grant.enabled,
        variables_override=json.loads(grant.variables_override_json or "{}"),
        granted_by=grant.granted_by,
        created_at=grant.created_at,
    )


@router.get("", response_model=list[ToolGrantOut])
async def list_grants(
    tool_id: str | None = None,
    principal_id: str | None = None,
    principal: dict = Depends(get_principal),
    db: AsyncSession = Depends(get_db),
):
    """List grants. Admins see all; non-admins see only their own grants."""
    query = select(ToolGrant).order_by(ToolGrant.created_at.desc())
    if tool_id:
        query = query.where(ToolGrant.tool_id == tool_id)
    if not principal.get("is_admin"):
        # Non-admins may only see their own grants
        own_id = str(principal.get("user_id", ""))
        query = query.where(ToolGrant.principal_id == own_id)
    elif principal_id:
        query = query.where(ToolGrant.principal_id == principal_id)
    result = await db.execute(query)
    return [_grant_out(g) for g in result.scalars().all()]


@router.post("", response_model=ToolGrantOut, status_code=201)
async def create_grant(
    body: ToolGrantCreate,
    principal: dict = Depends(get_admin_principal),
    db: AsyncSession = Depends(get_db),
):
    """Grant a tool to a principal. 409 if the grant already exists."""
    tool = await db.get(Tool, body.tool_id)
    if not tool:
        raise HTTPException(404, "Tool not found")
    if tool.state not in {"approved", "assignable", "granted", "active"}:
        raise HTTPException(400, f"Tool state '{tool.state}' cannot be granted")

    existing = await db.execute(
        select(ToolGrant).where(
            ToolGrant.tool_id == body.tool_id,
            ToolGrant.principal_type == body.principal_type,
            ToolGrant.principal_id == body.principal_id,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(409, "Grant already exists for this tool and principal")

    grant = ToolGrant(
        tool_id=body.tool_id,
        principal_type=body.principal_type,
        principal_id=body.principal_id,
        principal_name=body.principal_name,
        enabled=body.enabled,
        variables_override_json=json.dumps(body.variables_override),
        granted_by=principal["username"],
    )
    db.add(grant)

    # Advance tool state to 'granted' if it hasn't progressed further
    if tool.state in {"approved", "assignable"}:
        tool.state = "granted"

    await db.commit()
    await db.refresh(grant)
    logger.info(
        "Grant created: tool=%s principal=%s:%s by %s",
        tool.name, body.principal_type, body.principal_id, principal["username"],
    )
    return _grant_out(grant)


@router.patch("/{grant_id}", response_model=ToolGrantOut)
async def update_grant(
    grant_id: int,
    body: ToolGrantUpdate,
    principal: dict = Depends(get_admin_principal),
    db: AsyncSession = Depends(get_db),
):
    """Update a grant's enabled state or variable overrides."""
    grant = await db.get(ToolGrant, grant_id)
    if not grant:
        raise HTTPException(404, "Grant not found")

    if body.enabled is not None:
        grant.enabled = body.enabled
    if body.variables_override is not None:
        grant.variables_override_json = json.dumps(body.variables_override)

    await db.commit()
    await db.refresh(grant)
    logger.info("Grant %d updated by %s", grant_id, principal["username"])
    return _grant_out(grant)


@router.delete("/{grant_id}", status_code=204)
async def revoke_grant(
    grant_id: int,
    principal: dict = Depends(get_admin_principal),
    db: AsyncSession = Depends(get_db),
):
    """Revoke a grant permanently."""
    grant = await db.get(ToolGrant, grant_id)
    if not grant:
        raise HTTPException(404, "Grant not found")
    await db.delete(grant)
    await db.commit()
    logger.info("Grant %d revoked by %s", grant_id, principal["username"])


# ── Agent list proxy (for grant UI dropdown) ──────────────────────────────────

agents_router = APIRouter(prefix="/api", tags=["agents"])


@agents_router.get("/agents")
async def list_agents(_: dict = Depends(get_admin_principal)):
    """Proxy to AgentManager — returns agent list for the grants UI."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(f"{settings.agentmanager_url}/agents")
            r.raise_for_status()
            return r.json()
    except Exception as exc:
        logger.warning("Could not fetch agents from AgentManager: %s", exc)
        return []
