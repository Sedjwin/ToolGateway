"""Tool execution endpoint."""
from __future__ import annotations

import json
import logging
import time
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_admin_principal, get_principal
from app.database import get_db
from app.models import Tool, ToolExecutionLog, ToolFilter, ToolGrant
from app.schemas import ToolCall, ToolResult
from app.services.filter_engine import apply_first_matching_filter
from app.services.tool_runner import run_tool

router = APIRouter(prefix="/api", tags=["execute"])
logger = logging.getLogger(__name__)

EXECUTABLE_STATES = {"approved", "assignable", "granted", "active"}


def _rejected(
    *,
    request_id: str,
    tool_name: str,
    principal: dict,
    reason: str,
    filter_type: str | None = None,
    filter_name: str | None = None,
    metadata: dict | None = None,
) -> ToolResult:
    return ToolResult(
        status="rejected",
        request_id=request_id,
        tool=tool_name,
        principal=f"{principal['principal_type']}:{principal['user_id']}",
        reason=reason,
        filter_type=filter_type,
        filter_name=filter_name,
        metadata=metadata or {},
    )


async def _log(
    db: AsyncSession,
    *,
    request_id: str,
    tool: Tool,
    call: ToolCall,
    principal: dict,
    filtered_request: dict,
    raw_response: dict,
    filtered_response: dict,
    incoming_filter_id: int | None,
    outgoing_filter_id: int | None,
    status: str,
    rejection_reason: str | None = None,
    evaluator_agent_id: str | None = None,
    evaluator_model: str | None = None,
    duration_ms: int | None = None,
) -> None:
    log = ToolExecutionLog(
        request_id=request_id,
        tool_id=tool.tool_id,
        tool_name=tool.name,
        principal_type=principal["principal_type"],
        principal_id=str(principal["user_id"]),
        principal_name=principal.get("display_name") or principal.get("username", ""),
        originating_user_id=call.originating_user_id,
        session_id=call.session_id,
        incoming_payload_json=json.dumps(call.payload),
        filtered_request_json=json.dumps(filtered_request),
        raw_tool_response_json=json.dumps(raw_response),
        filtered_response_json=json.dumps(filtered_response),
        incoming_filter_id=incoming_filter_id,
        outgoing_filter_id=outgoing_filter_id,
        status=status,
        rejection_reason=rejection_reason,
        evaluator_agent_id=evaluator_agent_id,
        evaluator_model=evaluator_model,
        duration_ms=duration_ms,
    )
    db.add(log)
    await db.commit()


@router.post("/execute", response_model=ToolResult)
async def execute_tool(
    call: ToolCall,
    principal: dict = Depends(get_principal),
    db: AsyncSession = Depends(get_db),
):
    """
    Execute a tool on behalf of the authenticated principal.
    Auth: UserManager JWT or agent API key.
    """
    request_id = str(uuid.uuid4())
    started = time.monotonic()

    # Find the tool
    result = await db.execute(select(Tool).where(Tool.name == call.tool_name))
    tool = result.scalar_one_or_none()
    if not tool:
        raise HTTPException(404, f"Tool '{call.tool_name}' not found")

    # Validate tool is executable
    if not tool.enabled or tool.state not in EXECUTABLE_STATES:
        denial = _rejected(
            request_id=request_id, tool_name=call.tool_name, principal=principal,
            reason=f"Tool is not active (state={tool.state}, enabled={tool.enabled})",
        )
        await _log(
            db, request_id=request_id, tool=tool, call=call, principal=principal,
            filtered_request=call.payload, raw_response={},
            filtered_response=denial.model_dump(),
            incoming_filter_id=None, outgoing_filter_id=None,
            status="rejected", rejection_reason=denial.reason,
        )
        return denial

    # Check grant
    grant_result = await db.execute(
        select(ToolGrant).where(
            ToolGrant.tool_id == tool.tool_id,
            ToolGrant.principal_id == str(principal["user_id"]),
            ToolGrant.enabled == True,  # noqa: E712
        )
    )
    grant = grant_result.scalar_one_or_none()
    if not grant:
        denial = _rejected(
            request_id=request_id, tool_name=call.tool_name, principal=principal,
            reason="No active grant for this principal",
        )
        await _log(
            db, request_id=request_id, tool=tool, call=call, principal=principal,
            filtered_request=call.payload, raw_response={},
            filtered_response=denial.model_dump(),
            incoming_filter_id=None, outgoing_filter_id=None,
            status="rejected", rejection_reason=denial.reason,
        )
        return denial

    # Load filters
    filters_result = await db.execute(
        select(ToolFilter)
        .where(ToolFilter.tool_id == tool.tool_id, ToolFilter.enabled == True)  # noqa: E712
        .order_by(ToolFilter.phase.asc(), ToolFilter.priority.asc(), ToolFilter.id.asc())
    )
    filters = filters_result.scalars().all()

    principal_type = principal["principal_type"]
    principal_id = str(principal["user_id"])

    # Incoming filter phase
    incoming_decision, incoming_filter_id = await apply_first_matching_filter(
        filters=filters,
        phase="incoming",
        payload=call.payload,
        tool_name=tool.name,
        principal_type=principal_type,
        principal_id=principal_id,
        session_id=call.session_id,
    )

    if incoming_decision.status == "denied":
        denial = _rejected(
            request_id=request_id, tool_name=call.tool_name, principal=principal,
            reason=incoming_decision.reason or "Denied by incoming filter",
            filter_type=incoming_decision.filter_type,
            filter_name=incoming_decision.filter_name,
            metadata={"filter_disclosed": incoming_decision.transparency_disclosed},
        )
        await _log(
            db, request_id=request_id, tool=tool, call=call, principal=principal,
            filtered_request=incoming_decision.payload, raw_response={},
            filtered_response=denial.model_dump(),
            incoming_filter_id=incoming_filter_id, outgoing_filter_id=None,
            status="rejected", rejection_reason=denial.reason,
            evaluator_agent_id=incoming_decision.evaluator_agent_id,
            evaluator_model=incoming_decision.evaluator_model,
        )
        return denial

    filtered_request = incoming_decision.payload

    # Execute the tool
    try:
        raw_response = await run_tool(tool, filtered_request)
    except Exception as exc:
        duration_ms = int((time.monotonic() - started) * 1000)
        denial = _rejected(
            request_id=request_id, tool_name=call.tool_name, principal=principal,
            reason=f"Tool execution failed: {exc}",
        )
        await _log(
            db, request_id=request_id, tool=tool, call=call, principal=principal,
            filtered_request=filtered_request, raw_response={"error": str(exc)},
            filtered_response=denial.model_dump(),
            incoming_filter_id=incoming_filter_id, outgoing_filter_id=None,
            status="failed", rejection_reason=denial.reason, duration_ms=duration_ms,
        )
        return denial

    # Outgoing filter phase
    outgoing_decision, outgoing_filter_id = await apply_first_matching_filter(
        filters=filters,
        phase="outgoing",
        payload=raw_response,
        tool_name=tool.name,
        principal_type=principal_type,
        principal_id=principal_id,
        session_id=call.session_id,
    )

    if outgoing_decision.status == "denied":
        duration_ms = int((time.monotonic() - started) * 1000)
        denial = _rejected(
            request_id=request_id, tool_name=call.tool_name, principal=principal,
            reason=outgoing_decision.reason or "Output denied by outgoing filter",
            filter_type=outgoing_decision.filter_type,
            filter_name=outgoing_decision.filter_name,
            metadata={"filter_disclosed": outgoing_decision.transparency_disclosed},
        )
        await _log(
            db, request_id=request_id, tool=tool, call=call, principal=principal,
            filtered_request=filtered_request, raw_response=raw_response,
            filtered_response=denial.model_dump(),
            incoming_filter_id=incoming_filter_id, outgoing_filter_id=outgoing_filter_id,
            status="rejected", rejection_reason=denial.reason,
            evaluator_agent_id=outgoing_decision.evaluator_agent_id,
            evaluator_model=outgoing_decision.evaluator_model,
            duration_ms=duration_ms,
        )
        return denial

    duration_ms = int((time.monotonic() - started) * 1000)
    final_payload = outgoing_decision.payload
    result_obj = ToolResult(
        status="ok",
        request_id=request_id,
        tool=call.tool_name,
        principal=f"{principal_type}:{principal_id}",
        data=final_payload,
        metadata={
            "incoming_filter_disclosed": incoming_decision.transparency_disclosed,
            "outgoing_filter_disclosed": outgoing_decision.transparency_disclosed,
            "duration_ms": duration_ms,
        },
    )

    await _log(
        db, request_id=request_id, tool=tool, call=call, principal=principal,
        filtered_request=filtered_request, raw_response=raw_response,
        filtered_response=result_obj.model_dump(),
        incoming_filter_id=incoming_filter_id, outgoing_filter_id=outgoing_filter_id,
        status="completed",
        evaluator_agent_id=outgoing_decision.evaluator_agent_id or incoming_decision.evaluator_agent_id,
        evaluator_model=outgoing_decision.evaluator_model or incoming_decision.evaluator_model,
        duration_ms=duration_ms,
    )
    logger.info(
        "Executed tool=%s principal=%s:%s status=ok duration=%dms",
        call.tool_name, principal_type, principal_id, duration_ms,
    )
    return result_obj


@router.post("/admin/execute", response_model=ToolResult)
async def admin_execute_tool(
    call: ToolCall,
    principal: dict = Depends(get_admin_principal),
    db: AsyncSession = Depends(get_db),
):
    """Admin test execution path — same pipeline, logged as admin."""
    return await execute_tool(call, principal, db)
