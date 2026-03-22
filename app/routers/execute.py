from __future__ import annotations

import json
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Tool, ToolExecutionLog, ToolFilter, ToolGrant
from app.schemas import ToolCall, ToolResult
from app.security import require_admin_key, require_service_key
from app.services.filter_engine import apply_first_matching_filter
from app.services.tool_runner import run_tool

router = APIRouter(tags=["execute"])


def _make_rejected(
    *,
    request_id: str,
    tool_name: str,
    principal_type: str,
    principal_id: str,
    reason: str,
    filter_type: str | None = None,
    filter_name: str | None = None,
    metadata: dict | None = None,
) -> ToolResult:
    return ToolResult(
        status="rejected",
        request_id=request_id,
        tool=tool_name,
        principal=f"{principal_type}:{principal_id}",
        reason=reason,
        filter_type=filter_type,
        filter_name=filter_name,
        metadata=metadata or {},
    )


async def _find_tool(db: AsyncSession, tool_name: str) -> Tool:
    result = await db.execute(select(Tool).where(Tool.name == tool_name))
    tool = result.scalar_one_or_none()
    if not tool:
        raise HTTPException(404, "Tool not found")
    return tool


async def _find_grant(db: AsyncSession, tool_id: str, principal_type: str, principal_id: str) -> ToolGrant | None:
    result = await db.execute(
        select(ToolGrant).where(
            ToolGrant.tool_id == tool_id,
            ToolGrant.principal_type == principal_type,
            ToolGrant.principal_id == principal_id,
            ToolGrant.enabled == True,  # noqa: E712
        )
    )
    return result.scalar_one_or_none()


async def _load_filters(db: AsyncSession, tool_id: str) -> list[ToolFilter]:
    result = await db.execute(
        select(ToolFilter)
        .where(ToolFilter.tool_id == tool_id, ToolFilter.enabled == True)  # noqa: E712
        .order_by(ToolFilter.phase.asc(), ToolFilter.priority.asc(), ToolFilter.id.asc())
    )
    return result.scalars().all()


async def _log_execution(
    db: AsyncSession,
    *,
    request_id: str,
    tool: Tool,
    call: ToolCall,
    filtered_request: dict,
    raw_response: dict,
    filtered_response: dict,
    incoming_filter_id: int | None,
    outgoing_filter_id: int | None,
    status: str,
    rejection_reason: str | None = None,
    evaluator_agent_id: str | None = None,
    evaluator_model: str | None = None,
) -> None:
    log = ToolExecutionLog(
        request_id=request_id,
        tool_id=tool.tool_id,
        tool_name=tool.name,
        principal_type=call.principal_type,
        principal_id=call.principal_id,
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
    )
    db.add(log)
    await db.commit()


@router.post("/execute", response_model=ToolResult, dependencies=[Depends(require_service_key)])
async def execute_tool(call: ToolCall, db: AsyncSession = Depends(get_db)):
    request_id = str(uuid.uuid4())
    tool = await _find_tool(db, call.tool_name)

    if not tool.enabled or tool.state not in {"approved", "assignable", "granted", "active"}:
        result = _make_rejected(
            request_id=request_id,
            tool_name=call.tool_name,
            principal_type=call.principal_type,
            principal_id=call.principal_id,
            reason="ToolGateway ERROR: Tool is not active",
        )
        await _log_execution(
            db,
            request_id=request_id,
            tool=tool,
            call=call,
            filtered_request=call.payload,
            raw_response={},
            filtered_response=result.model_dump(),
            incoming_filter_id=None,
            outgoing_filter_id=None,
            status="rejected",
            rejection_reason=result.reason,
        )
        return result

    grant = await _find_grant(db, tool.tool_id, call.principal_type, call.principal_id)
    if not grant:
        result = _make_rejected(
            request_id=request_id,
            tool_name=call.tool_name,
            principal_type=call.principal_type,
            principal_id=call.principal_id,
            reason="ToolGateway ERROR: Agent denied access",
        )
        await _log_execution(
            db,
            request_id=request_id,
            tool=tool,
            call=call,
            filtered_request=call.payload,
            raw_response={},
            filtered_response=result.model_dump(),
            incoming_filter_id=None,
            outgoing_filter_id=None,
            status="rejected",
            rejection_reason=result.reason,
        )
        return result

    filters = await _load_filters(db, tool.tool_id)

    incoming_decision, incoming_filter_id = await apply_first_matching_filter(
        filters=filters,
        phase="incoming",
        payload=call.payload,
        tool_name=tool.name,
        principal_type=call.principal_type,
        principal_id=call.principal_id,
        session_id=call.session_id,
    )

    if incoming_decision.status == "denied":
        result = _make_rejected(
            request_id=request_id,
            tool_name=call.tool_name,
            principal_type=call.principal_type,
            principal_id=call.principal_id,
            reason=incoming_decision.reason or "Denied by filter",
            filter_type=incoming_decision.filter_type,
            filter_name=incoming_decision.filter_name,
            metadata={"filter_disclosed": incoming_decision.transparency_disclosed},
        )
        await _log_execution(
            db,
            request_id=request_id,
            tool=tool,
            call=call,
            filtered_request=incoming_decision.payload,
            raw_response={},
            filtered_response=result.model_dump(),
            incoming_filter_id=incoming_filter_id,
            outgoing_filter_id=None,
            status="rejected",
            rejection_reason=result.reason,
            evaluator_agent_id=incoming_decision.evaluator_agent_id,
            evaluator_model=incoming_decision.evaluator_model,
        )
        return result

    filtered_request = incoming_decision.payload

    try:
        raw_response = await run_tool(tool, filtered_request)
    except Exception as exc:
        result = _make_rejected(
            request_id=request_id,
            tool_name=call.tool_name,
            principal_type=call.principal_type,
            principal_id=call.principal_id,
            reason=f"Tool execution failed: {exc}",
        )
        await _log_execution(
            db,
            request_id=request_id,
            tool=tool,
            call=call,
            filtered_request=filtered_request,
            raw_response={"error": str(exc)},
            filtered_response=result.model_dump(),
            incoming_filter_id=incoming_filter_id,
            outgoing_filter_id=None,
            status="failed",
            rejection_reason=result.reason,
        )
        return result

    outgoing_decision, outgoing_filter_id = await apply_first_matching_filter(
        filters=filters,
        phase="outgoing",
        payload=raw_response,
        tool_name=tool.name,
        principal_type=call.principal_type,
        principal_id=call.principal_id,
        session_id=call.session_id,
    )

    if outgoing_decision.status == "denied":
        result = _make_rejected(
            request_id=request_id,
            tool_name=call.tool_name,
            principal_type=call.principal_type,
            principal_id=call.principal_id,
            reason=outgoing_decision.reason or "Output denied by filter",
            filter_type=outgoing_decision.filter_type,
            filter_name=outgoing_decision.filter_name,
            metadata={"filter_disclosed": outgoing_decision.transparency_disclosed},
        )
        await _log_execution(
            db,
            request_id=request_id,
            tool=tool,
            call=call,
            filtered_request=filtered_request,
            raw_response=raw_response,
            filtered_response=result.model_dump(),
            incoming_filter_id=incoming_filter_id,
            outgoing_filter_id=outgoing_filter_id,
            status="rejected",
            rejection_reason=result.reason,
            evaluator_agent_id=outgoing_decision.evaluator_agent_id,
            evaluator_model=outgoing_decision.evaluator_model,
        )
        return result

    final_payload = outgoing_decision.payload
    metadata = {
        "incoming_filter_disclosed": incoming_decision.transparency_disclosed,
        "outgoing_filter_disclosed": outgoing_decision.transparency_disclosed,
    }
    result = ToolResult(
        status="ok",
        request_id=request_id,
        tool=call.tool_name,
        principal=f"{call.principal_type}:{call.principal_id}",
        data=final_payload,
        metadata=metadata,
    )

    await _log_execution(
        db,
        request_id=request_id,
        tool=tool,
        call=call,
        filtered_request=filtered_request,
        raw_response=raw_response,
        filtered_response=result.model_dump(),
        incoming_filter_id=incoming_filter_id,
        outgoing_filter_id=outgoing_filter_id,
        status="completed",
        evaluator_agent_id=outgoing_decision.evaluator_agent_id or incoming_decision.evaluator_agent_id,
        evaluator_model=outgoing_decision.evaluator_model or incoming_decision.evaluator_model,
    )
    return result


@router.post("/admin/execute", response_model=ToolResult, dependencies=[Depends(require_admin_key)])
async def admin_execute_tool(call: ToolCall, db: AsyncSession = Depends(get_db)):
    if call.principal_type != "admin":
        call.principal_type = "admin"
    return await execute_tool(call, db)
