"""SQLAlchemy models for ToolGateway."""
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Tool(Base):
    """A registered tool in the gateway."""
    __tablename__ = "tools"

    tool_id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    category: Mapped[str] = mapped_column(String, nullable=False, default="custom_local")
    # category: first_party | custom_local | external | skill
    kind: Mapped[str] = mapped_column(String, nullable=False, default="http")
    # kind: http | echo
    endpoint_url: Mapped[str | None] = mapped_column(String, nullable=True)
    method: Mapped[str] = mapped_column(String, nullable=False, default="POST")
    state: Mapped[str] = mapped_column(String, nullable=False, default="requested")
    # state: requested | pending_review | quarantined | approved | assignable | granted | active | suspended | blocked | retired
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    capabilities_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    # e.g. ["network_access", "filesystem_reads", "secret_access"]
    variables_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    # e.g. {"allowed_domains": ["ourpersonalemail.com"], "rate_limit_per_hour": 100}
    metadata_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    versions = relationship("ToolVersion", back_populates="tool", cascade="all, delete-orphan")
    grants = relationship("ToolGrant", back_populates="tool", cascade="all, delete-orphan")
    filters = relationship("ToolFilter", back_populates="tool", cascade="all, delete-orphan")


class ToolVersion(Base):
    """A specific versioned snapshot of a tool, requiring individual admin approval."""
    __tablename__ = "tool_versions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tool_id: Mapped[str] = mapped_column(ForeignKey("tools.tool_id", ondelete="CASCADE"), nullable=False)
    version: Mapped[str] = mapped_column(String, nullable=False)
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")
    state: Mapped[str] = mapped_column(String, nullable=False, default="pending_review")
    # state: pending_review | approved | retired
    reviewed_by: Mapped[str | None] = mapped_column(String, nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    tool = relationship("Tool", back_populates="versions")


class ToolGrant(Base):
    """A grant giving a specific principal permission to execute a tool."""
    __tablename__ = "tool_grants"
    __table_args__ = (UniqueConstraint("tool_id", "principal_type", "principal_id", name="uq_tool_principal"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tool_id: Mapped[str] = mapped_column(ForeignKey("tools.tool_id", ondelete="CASCADE"), nullable=False)
    principal_type: Mapped[str] = mapped_column(String, nullable=False, default="agent")
    # principal_type: agent | human
    principal_id: Mapped[str] = mapped_column(String, nullable=False)
    principal_name: Mapped[str] = mapped_column(String, nullable=False, default="")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    variables_override_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    granted_by: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    tool = relationship("Tool", back_populates="grants")


class ToolFilter(Base):
    """A policy filter applied to incoming or outgoing tool calls."""
    __tablename__ = "tool_filters"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tool_id: Mapped[str] = mapped_column(ForeignKey("tools.tool_id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    phase: Mapped[str] = mapped_column(String, nullable=False)
    # phase: incoming | outgoing
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    scope: Mapped[str] = mapped_column(String, nullable=False, default="all")
    # scope: all | selected
    principals_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    filter_type: Mapped[str] = mapped_column(String, nullable=False, default="logical")
    # filter_type: logical | agent
    action: Mapped[str] = mapped_column(String, nullable=False, default="deny")
    # action: pass | modify | redact | summarise | replace | deny
    transparent: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # transparent=True means the modification is NOT disclosed to the agent
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    config_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    tool = relationship("Tool", back_populates="filters")


class ToolExecutionLog(Base):
    """Full audit log entry for every tool call at the ToolGateway boundary."""
    __tablename__ = "tool_execution_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    request_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    tool_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    tool_name: Mapped[str] = mapped_column(String, nullable=False)
    principal_type: Mapped[str] = mapped_column(String, nullable=False)
    principal_id: Mapped[str] = mapped_column(String, nullable=False)
    principal_name: Mapped[str] = mapped_column(String, nullable=False, default="")
    originating_user_id: Mapped[str | None] = mapped_column(String, nullable=True)
    session_id: Mapped[str | None] = mapped_column(String, nullable=True)

    incoming_payload_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    filtered_request_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    raw_tool_response_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    filtered_response_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")

    incoming_filter_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    outgoing_filter_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False, default="completed")
    # status: completed | rejected | failed
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    evaluator_agent_id: Mapped[str | None] = mapped_column(String, nullable=True)
    evaluator_model: Mapped[str | None] = mapped_column(String, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)


class ToolInstallRequest(Base):
    """A request to add a new tool to the registry (from agent or admin)."""
    __tablename__ = "tool_install_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    requested_by_principal_type: Mapped[str] = mapped_column(String, nullable=False)
    requested_by_principal_id: Mapped[str] = mapped_column(String, nullable=False)
    requested_by_principal_name: Mapped[str] = mapped_column(String, nullable=False, default="")
    source: Mapped[str] = mapped_column(String, nullable=False, default="manual")
    proposed_name: Mapped[str] = mapped_column(String, nullable=False)
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(String, nullable=False, default="requested")
    # status: requested | approved | rejected
    admin_notes: Mapped[str] = mapped_column(Text, nullable=False, default="")
    resolved_by: Mapped[str | None] = mapped_column(String, nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
