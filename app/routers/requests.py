"""Tool install request workflow."""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_admin_principal, get_principal
from app.database import get_db
from app.models import ToolInstallRequest
from app.schemas import InstallRequestCreate, InstallRequestOut, InstallRequestResolve

router = APIRouter(prefix="/api/requests", tags=["requests"])
logger = logging.getLogger(__name__)


@router.get("", response_model=list[InstallRequestOut])
async def list_requests(
    status: str | None = None,
    _: dict = Depends(get_admin_principal),
    db: AsyncSession = Depends(get_db),
):
    query = select(ToolInstallRequest).order_by(ToolInstallRequest.created_at.desc())
    if status:
        query = query.where(ToolInstallRequest.status == status)
    result = await db.execute(query)
    return result.scalars().all()


@router.post("", response_model=InstallRequestOut, status_code=201)
async def create_request(
    body: InstallRequestCreate,
    principal: dict = Depends(get_principal),
    db: AsyncSession = Depends(get_db),
):
    """Any authenticated principal can request a tool install."""
    req = ToolInstallRequest(
        requested_by_principal_type=principal["principal_type"],
        requested_by_principal_id=str(principal["user_id"]),
        requested_by_principal_name=principal.get("display_name") or principal.get("username", ""),
        source=body.source,
        proposed_name=body.proposed_name,
        notes=body.notes,
        status="requested",
    )
    db.add(req)
    await db.commit()
    await db.refresh(req)
    logger.info(
        "Install request for '%s' from %s:%s",
        body.proposed_name, principal["principal_type"], principal["user_id"],
    )
    return req


@router.post("/{req_id}/approve", response_model=InstallRequestOut)
async def approve_request(
    req_id: int,
    body: InstallRequestResolve,
    principal: dict = Depends(get_admin_principal),
    db: AsyncSession = Depends(get_db),
):
    req = await db.get(ToolInstallRequest, req_id)
    if not req:
        raise HTTPException(404, "Request not found")
    if req.status != "requested":
        raise HTTPException(400, f"Request is already '{req.status}'")
    req.status = "approved"
    req.admin_notes = body.admin_notes
    req.resolved_by = principal["username"]
    req.resolved_at = datetime.now(timezone.utc).replace(tzinfo=None)
    await db.commit()
    await db.refresh(req)
    logger.info("Install request %d approved by %s", req_id, principal["username"])
    return req


@router.post("/{req_id}/reject", response_model=InstallRequestOut)
async def reject_request(
    req_id: int,
    body: InstallRequestResolve,
    principal: dict = Depends(get_admin_principal),
    db: AsyncSession = Depends(get_db),
):
    req = await db.get(ToolInstallRequest, req_id)
    if not req:
        raise HTTPException(404, "Request not found")
    if req.status != "requested":
        raise HTTPException(400, f"Request is already '{req.status}'")
    req.status = "rejected"
    req.admin_notes = body.admin_notes
    req.resolved_by = principal["username"]
    req.resolved_at = datetime.now(timezone.utc).replace(tzinfo=None)
    await db.commit()
    await db.refresh(req)
    logger.info("Install request %d rejected by %s", req_id, principal["username"])
    return req
