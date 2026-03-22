from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


# ── Tool ──────────────────────────────────────────────────────────────────────

class ToolCreate(BaseModel):
    name: str
    description: str = ""
    category: Literal["first_party", "custom_local", "external", "skill"] = "custom_local"
    kind: Literal["http", "echo"] = "http"
    endpoint_url: Optional[str] = None
    method: str = "POST"
    state: str = "requested"
    enabled: bool = False
    capabilities: list[str] = []
    variables: dict[str, Any] = {}
    metadata: dict[str, Any] = {}


class ToolUpdate(BaseModel):
    description: Optional[str] = None
    category: Optional[str] = None
    endpoint_url: Optional[str] = None
    method: Optional[str] = None
    state: Optional[str] = None
    enabled: Optional[bool] = None
    capabilities: Optional[list[str]] = None
    variables: Optional[dict[str, Any]] = None
    metadata: Optional[dict[str, Any]] = None


class ToolOut(BaseModel):
    tool_id: str
    name: str
    description: str
    category: str
    kind: str
    endpoint_url: Optional[str]
    method: str
    state: str
    enabled: bool
    capabilities: list[str]
    variables: dict[str, Any]
    metadata: dict[str, Any]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ── ToolVersion ───────────────────────────────────────────────────────────────

class ToolVersionCreate(BaseModel):
    version: str
    notes: str = ""


class ToolVersionOut(BaseModel):
    id: int
    tool_id: str
    version: str
    notes: str
    state: str
    reviewed_by: Optional[str]
    reviewed_at: Optional[datetime]
    created_at: datetime

    model_config = {"from_attributes": True}


# ── ToolGrant ─────────────────────────────────────────────────────────────────

class ToolGrantCreate(BaseModel):
    tool_id: str
    principal_type: Literal["agent", "human"] = "agent"
    principal_id: str
    principal_name: str = ""
    enabled: bool = True
    variables_override: dict[str, Any] = {}


class ToolGrantUpdate(BaseModel):
    enabled: Optional[bool] = None
    variables_override: Optional[dict[str, Any]] = None


class ToolGrantOut(BaseModel):
    id: int
    tool_id: str
    principal_type: str
    principal_id: str
    principal_name: str
    enabled: bool
    variables_override: dict[str, Any]
    granted_by: Optional[str]
    created_at: datetime

    model_config = {"from_attributes": True}


# ── ToolFilter ────────────────────────────────────────────────────────────────

class ToolFilterCreate(BaseModel):
    name: str
    phase: Literal["incoming", "outgoing"]
    priority: int = 100
    scope: Literal["all", "selected"] = "all"
    principals: list[str] = []
    filter_type: Literal["logical", "agent"] = "logical"
    action: Literal["pass", "modify", "redact", "summarise", "replace", "deny"] = "deny"
    transparent: bool = True
    enabled: bool = True
    config: dict[str, Any] = {}


class ToolFilterUpdate(BaseModel):
    name: Optional[str] = None
    priority: Optional[int] = None
    scope: Optional[str] = None
    principals: Optional[list[str]] = None
    action: Optional[str] = None
    transparent: Optional[bool] = None
    enabled: Optional[bool] = None
    config: Optional[dict[str, Any]] = None


class ToolFilterOut(BaseModel):
    id: int
    tool_id: str
    name: str
    phase: str
    priority: int
    scope: str
    principals: list[str]
    filter_type: str
    action: str
    transparent: bool
    enabled: bool
    config: dict[str, Any]
    created_at: datetime

    model_config = {"from_attributes": True}


class FilterDryRunRequest(BaseModel):
    payload: dict[str, Any]
    principal_type: str = "agent"
    principal_id: str = "test"
    session_id: Optional[str] = None


# ── Execution ─────────────────────────────────────────────────────────────────

class ToolCall(BaseModel):
    tool_name: str
    payload: dict[str, Any] = {}
    session_id: Optional[str] = None
    originating_user_id: Optional[str] = None


class ToolResult(BaseModel):
    status: str
    request_id: str
    tool: str
    principal: str
    data: Optional[dict[str, Any]] = None
    reason: Optional[str] = None
    filter_type: Optional[str] = None
    filter_name: Optional[str] = None
    metadata: dict[str, Any] = {}


# ── Install Requests ──────────────────────────────────────────────────────────

class InstallRequestCreate(BaseModel):
    proposed_name: str
    source: str = "manual"
    notes: str = ""


class InstallRequestResolve(BaseModel):
    admin_notes: str = ""


class InstallRequestOut(BaseModel):
    id: int
    requested_by_principal_type: str
    requested_by_principal_id: str
    requested_by_principal_name: str
    source: str
    proposed_name: str
    notes: str
    status: str
    admin_notes: str
    resolved_by: Optional[str]
    resolved_at: Optional[datetime]
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Logs ──────────────────────────────────────────────────────────────────────

class ExecutionLogOut(BaseModel):
    id: int
    request_id: str
    tool_id: str
    tool_name: str
    principal_type: str
    principal_id: str
    principal_name: str
    originating_user_id: Optional[str]
    session_id: Optional[str]
    incoming_payload_json: str
    filtered_request_json: str
    raw_tool_response_json: str
    filtered_response_json: str
    incoming_filter_id: Optional[int]
    outgoing_filter_id: Optional[int]
    status: str
    rejection_reason: Optional[str]
    evaluator_agent_id: Optional[str]
    evaluator_model: Optional[str]
    duration_ms: Optional[int]
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Stats ─────────────────────────────────────────────────────────────────────

class StatsOut(BaseModel):
    tools_total: int
    tools_active: int
    tools_pending_review: int
    grants_total: int
    executions_today: int
    executions_7d: int
    rejections_7d: int
    install_requests_pending: int
