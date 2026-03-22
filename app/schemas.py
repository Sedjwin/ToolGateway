from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class ToolCreate(BaseModel):
    name: str
    description: str = ""
    kind: Literal["http", "echo"] = "http"
    endpoint_url: str | None = None
    method: str = "POST"
    state: str = "requested"
    enabled: bool = False
    requires_approval: bool = False
    capabilities: list[str] = []
    variables: dict[str, Any] = {}
    metadata: dict[str, Any] = {}


class ToolUpdate(BaseModel):
    description: str | None = None
    endpoint_url: str | None = None
    method: str | None = None
    state: str | None = None
    enabled: bool | None = None
    requires_approval: bool | None = None
    capabilities: list[str] | None = None
    variables: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None


class ToolOut(BaseModel):
    tool_id: str
    name: str
    description: str
    kind: str
    endpoint_url: str | None
    method: str
    state: str
    enabled: bool
    requires_approval: bool
    capabilities: list[str]
    variables: dict[str, Any]
    metadata: dict[str, Any]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ToolGrantUpsert(BaseModel):
    principal_type: Literal["agent", "admin"] = "agent"
    principal_id: str
    enabled: bool = True
    variables_override: dict[str, Any] = {}


class ToolGrantOut(BaseModel):
    id: int
    tool_id: str
    principal_type: str
    principal_id: str
    enabled: bool
    variables_override: dict[str, Any]
    created_at: datetime

    model_config = {"from_attributes": True}


class FilterCondition(BaseModel):
    target: str
    operator: Literal[
        "contains",
        "not_contains",
        "matches",
        "equals",
        "in_list",
        "not_in_list",
        "starts_with",
        "ends_with",
    ]
    value: Any


class ToolFilterCreate(BaseModel):
    name: str
    phase: Literal["incoming", "outgoing"]
    priority: int = 100
    scope: Literal["all", "selected"] = "all"
    principals: list[str] = []
    filter_type: Literal["logical", "agent"] = "logical"
    transparent: bool = True
    enabled: bool = True
    config: dict[str, Any] = {}


class ToolFilterOut(BaseModel):
    id: int
    tool_id: str
    name: str
    phase: str
    priority: int
    scope: str
    principals: list[str]
    filter_type: str
    transparent: bool
    enabled: bool
    config: dict[str, Any]
    created_at: datetime

    model_config = {"from_attributes": True}


class ToolCall(BaseModel):
    tool_name: str
    principal_type: Literal["agent", "admin"] = "agent"
    principal_id: str
    payload: dict[str, Any] = {}
    session_id: str | None = None
    originating_user_id: str | None = None


class ToolResult(BaseModel):
    status: str
    request_id: str
    tool: str
    principal: str
    data: dict[str, Any] | None = None
    reason: str | None = None
    filter_type: str | None = None
    filter_name: str | None = None
    metadata: dict[str, Any] = {}


class InstallRequestCreate(BaseModel):
    requested_by_principal_type: Literal["agent", "admin"] = "agent"
    requested_by_principal_id: str
    source: str = "manual"
    proposed_name: str
    notes: str = ""


class InstallRequestOut(BaseModel):
    id: int
    requested_by_principal_type: str
    requested_by_principal_id: str
    source: str
    proposed_name: str
    notes: str
    status: str
    created_at: datetime

    model_config = {"from_attributes": True}


class ExecutionLogOut(BaseModel):
    id: int
    request_id: str
    tool_id: str
    tool_name: str
    principal_type: str
    principal_id: str
    originating_user_id: str | None
    session_id: str | None
    incoming_payload_json: str
    filtered_request_json: str
    raw_tool_response_json: str
    filtered_response_json: str
    incoming_filter_id: int | None
    outgoing_filter_id: int | None
    status: str
    rejection_reason: str | None
    evaluator_agent_id: str | None
    evaluator_model: str | None
    created_at: datetime

    model_config = {"from_attributes": True}
