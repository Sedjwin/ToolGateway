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

from app.auth import get_principal
from app.config import settings
from app.database import init_db, get_db, AsyncSessionLocal
from app.models import Tool, ToolExecutionLog, ToolGrant, ToolInstallRequest
from app.routers import builtins, execute, filters, logs, requests, tools
from app.routers.grants import router as grants_router, agents_router
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


# ── Builtin tool seed ─────────────────────────────────────────────────────────

_BUILTIN_TOOLS = [
    {
        "name": "workspace.files",
        "description": "Read, write, and edit files in the agent's session workspace. Paths are relative to the workspace/ folder inside the current session directory.",
        "category": "builtin",
        "kind": "local",
        "state": "active",
        "enabled": True,
        "capabilities_json": '["filesystem_reads", "filesystem_writes"]',
        "skill_md": (
            "Read, write, and edit files in your session workspace using "
            "{tool:workspace.files|operation=read|path=...}, "
            "{tool:workspace.files|operation=write|path=...|content=...}, "
            "{tool:workspace.files|operation=edit|path=...|start_line=N|end_line=M|new_content=...}, "
            "or {tool:workspace.files|operation=list|path=.}. "
            "Paths are relative to your workspace folder."
        ),
    },
]

# First-party HTTP tools — seeded as approved + enabled, but still require per-agent grants.
_FIRSTPARTY_TOOLS = [
    {
        "name": "system.files",
        "description": "Read, write, and edit any file on the host filesystem. Full absolute-path access. Requires explicit admin grant.",
        "category": "first_party",
        "kind": "http",
        "endpoint_url": "http://127.0.0.1:8011/api/execute",
        "method": "POST",
        "state": "active",
        "enabled": True,
        "capabilities_json": '["filesystem_reads", "filesystem_writes"]',
        "skill_md": (
            "Read, write, edit, and search files anywhere on the host using absolute paths.\n"
            "{tool:system.files|operation=read|path=/absolute/path}\n"
            "{tool:system.files|operation=write|path=/absolute/path|content=<text>}\n"
            "{tool:system.files|operation=edit|path=/absolute/path|start_line=N|end_line=M|new_content=<text>}\n"
            "{tool:system.files|operation=list|path=/absolute/dir}\n"
            "{tool:system.files|operation=search|path=/absolute/dir|content=<glob pattern e.g. *.py>}\n"
            "{tool:system.files|operation=grep|path=/absolute/dir|content=<regex pattern>}\n"
            "Always read a file before editing to get correct line numbers. Use \\n for newlines in content."
        ),
    },
    {
        "name": "web.search",
        "description": "Search the web using Google Custom Search. Returns titles, URLs, and snippets. Requires explicit admin grant.",
        "category": "first_party",
        "kind": "http",
        "endpoint_url": "http://127.0.0.1:8012/api/search",
        "method": "POST",
        "state": "active",
        "enabled": True,
        "capabilities_json": '["network_access"]',
        "skill_md": (
            "Search the web with {tool:web.search|query=<search terms>|num=10}.\n"
            "Returns a list of results with title, URL, and snippet. num controls result count (1–10, default 10)."
        ),
    },
    {
        "name": "web.download",
        "description": "Download any file from a URL directly into the agent's workspace/downloads/ folder. Supports all file types. Requires explicit admin grant.",
        "category": "first_party",
        "kind": "http",
        "endpoint_url": "http://127.0.0.1:8012/api/download",
        "method": "POST",
        "state": "active",
        "enabled": True,
        "capabilities_json": '["network_access", "filesystem_writes"]',
        "skill_md": (
            "## web.download\n\n"
            "**MODE 1 — Save a file to your workspace** (images, PDFs, ZIPs, any binary or text):\n"
            "{tool:web.download|url=<direct file URL>|agent_id={current_agent_id}|session_id={current_session_id}}\n"
            "  - `agent_id` and `session_id` are REQUIRED — copy the exact values from your system prompt.\n"
            "  - Optional: add |filename=<name.ext> to override the auto-detected filename.\n"
            "  - Returns: {saved_to, filename, content_type, size_bytes} — use saved_to path with workspace.files or workspace.link.\n\n"
            "**MODE 2 — Browse a web page as text** (read HTML content, no file saved):\n"
            "{tool:web.download|url=<page URL>|fetch_only=true}\n"
            "  - Returns page text inline. Use this to find direct download URLs on a page, then use MODE 1 to download the actual file.\n\n"
            "**IMPORTANT:**\n"
            "- Passing strip_html or any other parameter not listed above will be IGNORED.\n"
            "- Do NOT use fetch_only=true to download images — it only returns text/HTML, not binary data.\n"
            "- If a URL returns 403 (forbidden) or 429 (rate limited), try a different source URL."
        ),
    },
]


async def _seed_builtin_tools() -> None:
    """Upsert builtin and first-party tools on startup.
    New tools are inserted. Existing tools have skill_md and description refreshed
    so changes in code are always reflected without manual DB edits.
    User-controlled fields (state, enabled) are left untouched on existing rows.
    """
    from sqlalchemy import select

    async with AsyncSessionLocal() as db:
        for spec in [*_BUILTIN_TOOLS, *_FIRSTPARTY_TOOLS]:
            result = await db.execute(select(Tool).where(Tool.name == spec["name"]))
            existing = result.scalar_one_or_none()
            if existing is None:
                db.add(Tool(**spec))
                logger.info("Seeded tool: %s", spec["name"])
            else:
                # Always sync skill_md and description — source of truth is main.py
                changed = False
                if existing.skill_md != spec.get("skill_md"):
                    existing.skill_md = spec.get("skill_md")
                    changed = True
                if existing.description != spec.get("description"):
                    existing.description = spec.get("description")
                    changed = True
                if changed:
                    logger.info("Updated skill_md/description for tool: %s", spec["name"])
        await db.commit()


# ── Lifespan ──────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    await init_db()
    await _seed_builtin_tools()
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
app.include_router(grants_router)
app.include_router(agents_router)
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


@app.get("/api/auth/me", tags=["auth"], include_in_schema=False)
async def auth_me(principal: dict = Depends(get_principal)):
    """Validate the current token and return principal info. Used by admin UI on startup."""
    return principal


@app.get("/health", include_in_schema=False)
async def health():
    return {"status": "ok", "service": "ToolGateway", "version": "2.0.0"}


if _STATIC.exists():
    app.mount("/static", StaticFiles(directory=str(_STATIC)), name="static")

    @app.get("/", include_in_schema=False)
    async def admin_ui():
        return FileResponse(str(_STATIC / "admin.html"))
