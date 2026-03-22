import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Tool(Base):
    __tablename__ = "tools"

    tool_id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    kind: Mapped[str] = mapped_column(String, nullable=False, default="http")  # http | echo
    endpoint_url: Mapped[str | None] = mapped_column(String, nullable=True)
    method: Mapped[str] = mapped_column(String, nullable=False, default="POST")
    state: Mapped[str] = mapped_column(String, nullable=False, default="requested")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    requires_approval: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    capabilities_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    variables_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    metadata_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    grants = relationship("ToolGrant", back_populates="tool", cascade="all, delete-orphan")
    filters = relationship("ToolFilter", back_populates="tool", cascade="all, delete-orphan")


class ToolGrant(Base):
    __tablename__ = "tool_grants"
    __table_args__ = (UniqueConstraint("tool_id", "principal_type", "principal_id", name="uq_tool_principal"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tool_id: Mapped[str] = mapped_column(ForeignKey("tools.tool_id", ondelete="CASCADE"), nullable=False)
    principal_type: Mapped[str] = mapped_column(String, nullable=False, default="agent")  # agent | admin
    principal_id: Mapped[str] = mapped_column(String, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    variables_override_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    tool = relationship("Tool", back_populates="grants")


class ToolFilter(Base):
    __tablename__ = "tool_filters"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tool_id: Mapped[str] = mapped_column(ForeignKey("tools.tool_id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    phase: Mapped[str] = mapped_column(String, nullable=False)  # incoming | outgoing
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    scope: Mapped[str] = mapped_column(String, nullable=False, default="all")  # all | selected
    principals_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    filter_type: Mapped[str] = mapped_column(String, nullable=False, default="logical")  # logical | agent
    transparent: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    config_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    tool = relationship("Tool", back_populates="filters")


class ToolExecutionLog(Base):
    __tablename__ = "tool_execution_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    request_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    tool_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    tool_name: Mapped[str] = mapped_column(String, nullable=False)
    principal_type: Mapped[str] = mapped_column(String, nullable=False)
    principal_id: Mapped[str] = mapped_column(String, nullable=False)
    originating_user_id: Mapped[str | None] = mapped_column(String, nullable=True)
    session_id: Mapped[str | None] = mapped_column(String, nullable=True)

    incoming_payload_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    filtered_request_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    raw_tool_response_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    filtered_response_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")

    incoming_filter_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    outgoing_filter_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False, default="completed")
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    evaluator_agent_id: Mapped[str | None] = mapped_column(String, nullable=True)
    evaluator_model: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)


class ToolInstallRequest(Base):
    __tablename__ = "tool_install_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    requested_by_principal_type: Mapped[str] = mapped_column(String, nullable=False)
    requested_by_principal_id: Mapped[str] = mapped_column(String, nullable=False)
    source: Mapped[str] = mapped_column(String, nullable=False, default="manual")
    proposed_name: Mapped[str] = mapped_column(String, nullable=False)
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(String, nullable=False, default="requested")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
