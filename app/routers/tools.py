from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Tool, ToolFilter, ToolGrant, ToolInstallRequest
from app.schemas import (
    InstallRequestCreate,
    InstallRequestOut,
    ToolCreate,
    ToolFilterCreate,
    ToolFilterOut,
    ToolGrantOut,
    ToolGrantUpsert,
    ToolOut,
    ToolUpdate,
)
from app.security import require_admin_key

router = APIRouter(prefix="/tools", tags=["tools"], dependencies=[Depends(require_admin_key)])


def _tool_out(tool: Tool) -> ToolOut:
    return ToolOut(
        tool_id=tool.tool_id,
        name=tool.name,
        description=tool.description,
        kind=tool.kind,
        endpoint_url=tool.endpoint_url,
        method=tool.method,
        state=tool.state,
        enabled=tool.enabled,
        requires_approval=tool.requires_approval,
        capabilities=json.loads(tool.capabilities_json or "[]"),
        variables=json.loads(tool.variables_json or "{}"),
        metadata=json.loads(tool.metadata_json or "{}"),
        created_at=tool.created_at,
        updated_at=tool.updated_at,
    )


def _grant_out(grant: ToolGrant) -> ToolGrantOut:
    return ToolGrantOut(
        id=grant.id,
        tool_id=grant.tool_id,
        principal_type=grant.principal_type,
        principal_id=grant.principal_id,
        enabled=grant.enabled,
        variables_override=json.loads(grant.variables_override_json or "{}"),
        created_at=grant.created_at,
    )


def _filter_out(tool_filter: ToolFilter) -> ToolFilterOut:
    return ToolFilterOut(
        id=tool_filter.id,
        tool_id=tool_filter.tool_id,
        name=tool_filter.name,
        phase=tool_filter.phase,
        priority=tool_filter.priority,
        scope=tool_filter.scope,
        principals=json.loads(tool_filter.principals_json or "[]"),
        filter_type=tool_filter.filter_type,
        transparent=tool_filter.transparent,
        enabled=tool_filter.enabled,
        config=json.loads(tool_filter.config_json or "{}"),
        created_at=tool_filter.created_at,
    )


@router.get("", response_model=list[ToolOut])
async def list_tools(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Tool).order_by(Tool.created_at.desc()))
    return [_tool_out(tool) for tool in result.scalars().all()]


@router.post("", response_model=ToolOut, status_code=201)
async def create_tool(body: ToolCreate, db: AsyncSession = Depends(get_db)):
    existing = await db.execute(select(Tool).where(Tool.name == body.name))
    if existing.scalar_one_or_none():
        raise HTTPException(409, "Tool already exists")

    tool = Tool(
        name=body.name,
        description=body.description,
        kind=body.kind,
        endpoint_url=body.endpoint_url,
        method=body.method,
        state=body.state,
        enabled=body.enabled,
        requires_approval=body.requires_approval,
        capabilities_json=json.dumps(body.capabilities),
        variables_json=json.dumps(body.variables),
        metadata_json=json.dumps(body.metadata),
    )
    db.add(tool)
    await db.commit()
    await db.refresh(tool)
    return _tool_out(tool)


@router.get("/{tool_id}", response_model=ToolOut)
async def get_tool(tool_id: str, db: AsyncSession = Depends(get_db)):
    tool = await db.get(Tool, tool_id)
    if not tool:
        raise HTTPException(404, "Tool not found")
    return _tool_out(tool)


@router.put("/{tool_id}", response_model=ToolOut)
async def update_tool(tool_id: str, body: ToolUpdate, db: AsyncSession = Depends(get_db)):
    tool = await db.get(Tool, tool_id)
    if not tool:
        raise HTTPException(404, "Tool not found")

    if body.description is not None:
        tool.description = body.description
    if body.endpoint_url is not None:
        tool.endpoint_url = body.endpoint_url
    if body.method is not None:
        tool.method = body.method
    if body.state is not None:
        tool.state = body.state
    if body.enabled is not None:
        tool.enabled = body.enabled
    if body.requires_approval is not None:
        tool.requires_approval = body.requires_approval
    if body.capabilities is not None:
        tool.capabilities_json = json.dumps(body.capabilities)
    if body.variables is not None:
        tool.variables_json = json.dumps(body.variables)
    if body.metadata is not None:
        tool.metadata_json = json.dumps(body.metadata)

    await db.commit()
    await db.refresh(tool)
    return _tool_out(tool)


@router.delete("/{tool_id}", status_code=204)
async def delete_tool(tool_id: str, db: AsyncSession = Depends(get_db)):
    tool = await db.get(Tool, tool_id)
    if not tool:
        raise HTTPException(404, "Tool not found")
    await db.delete(tool)
    await db.commit()


@router.put("/{tool_id}/grants", response_model=ToolGrantOut)
async def upsert_grant(tool_id: str, body: ToolGrantUpsert, db: AsyncSession = Depends(get_db)):
    tool = await db.get(Tool, tool_id)
    if not tool:
        raise HTTPException(404, "Tool not found")

    result = await db.execute(
        select(ToolGrant).where(
            ToolGrant.tool_id == tool_id,
            ToolGrant.principal_type == body.principal_type,
            ToolGrant.principal_id == body.principal_id,
        )
    )
    grant = result.scalar_one_or_none()
    if not grant:
        grant = ToolGrant(
            tool_id=tool_id,
            principal_type=body.principal_type,
            principal_id=body.principal_id,
            enabled=body.enabled,
            variables_override_json=json.dumps(body.variables_override),
        )
        db.add(grant)
    else:
        grant.enabled = body.enabled
        grant.variables_override_json = json.dumps(body.variables_override)

    await db.commit()
    await db.refresh(grant)
    return _grant_out(grant)


@router.get("/{tool_id}/grants", response_model=list[ToolGrantOut])
async def list_grants(tool_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(ToolGrant).where(ToolGrant.tool_id == tool_id).order_by(ToolGrant.id))
    return [_grant_out(g) for g in result.scalars().all()]


@router.post("/{tool_id}/filters", response_model=ToolFilterOut, status_code=201)
async def create_filter(tool_id: str, body: ToolFilterCreate, db: AsyncSession = Depends(get_db)):
    tool = await db.get(Tool, tool_id)
    if not tool:
        raise HTTPException(404, "Tool not found")

    tool_filter = ToolFilter(
        tool_id=tool_id,
        name=body.name,
        phase=body.phase,
        priority=body.priority,
        scope=body.scope,
        principals_json=json.dumps(body.principals),
        filter_type=body.filter_type,
        transparent=body.transparent,
        enabled=body.enabled,
        config_json=json.dumps(body.config),
    )
    db.add(tool_filter)
    await db.commit()
    await db.refresh(tool_filter)
    return _filter_out(tool_filter)


@router.get("/{tool_id}/filters", response_model=list[ToolFilterOut])
async def list_filters(tool_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(ToolFilter)
        .where(ToolFilter.tool_id == tool_id)
        .order_by(ToolFilter.phase.asc(), ToolFilter.priority.asc(), ToolFilter.id.asc())
    )
    return [_filter_out(f) for f in result.scalars().all()]


@router.delete("/{tool_id}/filters/{filter_id}", status_code=204)
async def delete_filter(tool_id: str, filter_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(ToolFilter).where(ToolFilter.tool_id == tool_id, ToolFilter.id == filter_id))
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(404, "Filter not found")
    await db.delete(item)
    await db.commit()


@router.post("/requests", response_model=InstallRequestOut, status_code=201)
async def create_install_request(body: InstallRequestCreate, db: AsyncSession = Depends(get_db)):
    req = ToolInstallRequest(
        requested_by_principal_type=body.requested_by_principal_type,
        requested_by_principal_id=body.requested_by_principal_id,
        source=body.source,
        proposed_name=body.proposed_name,
        notes=body.notes,
        status="requested",
    )
    db.add(req)
    await db.commit()
    await db.refresh(req)
    return req


@router.get("/requests", response_model=list[InstallRequestOut])
async def list_install_requests(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(ToolInstallRequest).order_by(ToolInstallRequest.created_at.desc()))
    return result.scalars().all()
