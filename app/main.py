"""ToolGateway — FastAPI entry point."""
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
from fastapi import Depends, FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import init_db, get_db
from app.models import Tool, ToolExecutionLog, ToolGrant, ToolInstallRequest
from app.routers import builtins, execute, filters, grants, logs, requests, tools
from app.schemas import StatsOut

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(name)s  %(message)s",
)
logger = logging.getLogger(__name__)

_STATIC = Path(__file__).parent / "static"
DATA_DIR = Path(__file__).parent.parent / "data"


# ── Stats helper ──────────────────────────────────────────────────────────────

async def get_stats(db: AsyncSession) -> StatsOut:
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_ago = now - timedelta(days=7)

    tools_total = await db.scalar(select(func.count()).select_from(Tool))
    tools_active = await db.scalar(
        select(func.count()).select_from(Tool).where(Tool.enabled == True)  # noqa: E712
    )
    tools_pending = await db.scalar(
        select(func.count()).select_from(Tool)
        .where(Tool.state.in_(["pending_review", "quarantined", "requested"]))
    )
    grants_total = await db.scalar(select(func.count()).select_from(ToolGrant))
    execs_today = await db.scalar(
        select(func.count()).select_from(ToolExecutionLog)
        .where(ToolExecutionLog.created_at >= today)
    )
    execs_7d = await db.scalar(
        select(func.count()).select_from(ToolExecutionLog)
        .where(ToolExecutionLog.created_at >= week_ago)
    )
    rejections_7d = await db.scalar(
        select(func.count()).select_from(ToolExecutionLog)
        .where(
            ToolExecutionLog.created_at >= week_ago,
            ToolExecutionLog.status == "rejected",
        )
    )
    requests_pending = await db.scalar(
        select(func.count()).select_from(ToolInstallRequest)
        .where(ToolInstallRequest.status == "requested")
    )

    return StatsOut(
        tools_total=tools_total or 0,
        tools_active=tools_active or 0,
        tools_pending_review=tools_pending or 0,
        grants_total=grants_total or 0,
        executions_today=execs_today or 0,
        executions_7d=execs_7d or 0,
        rejections_7d=rejections_7d or 0,
        install_requests_pending=requests_pending or 0,
    )


# ── Lifespan ──────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    await init_db()
    logger.info("ToolGateway starting on %s:%d", settings.host, settings.port)
    yield
    logger.info("ToolGateway shutting down.")


# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="ToolGateway",
    description="Tool control plane for the local AI stack.",
    version="2.0.0",
    lifespan=lifespan,
)

app.include_router(tools.router)
app.include_router(grants.router)
app.include_router(builtins.router)
app.include_router(filters.router)
app.include_router(execute.router)
app.include_router(logs.router)
app.include_router(requests.router)


@app.get("/api/stats", response_model=StatsOut, tags=["stats"])
async def stats(db: AsyncSession = Depends(get_db)):
    return await get_stats(db)


@app.post("/api/auth/login", tags=["auth"], include_in_schema=False)
async def proxy_login(body: dict):
    """Proxy UserManager login for the admin panel."""
    try:
        async with httpx.AsyncClient() as client:
            r = await client.post(
                f"{settings.usermanager_url}/auth/login",
                json=body,
                timeout=5.0,
            )
        return r.json()
    except Exception as exc:
        from fastapi import HTTPException
        raise HTTPException(503, f"UserManager unavailable: {exc}")


@app.get("/health", include_in_schema=False)
async def health():
    return {"status": "ok", "service": "ToolGateway", "version": "2.0.0"}


if _STATIC.exists():
    app.mount("/static", StaticFiles(directory=str(_STATIC)), name="static")

    @app.get("/", include_in_schema=False)
    async def admin_ui():
        return FileResponse(str(_STATIC / "admin.html"))
