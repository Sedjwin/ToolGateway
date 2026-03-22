from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import ToolExecutionLog
from app.schemas import ExecutionLogOut
from app.security import require_admin_key

router = APIRouter(prefix="/logs", tags=["logs"], dependencies=[Depends(require_admin_key)])


@router.get("/executions", response_model=list[ExecutionLogOut])
async def list_execution_logs(limit: int = 100, db: AsyncSession = Depends(get_db)):
    safe_limit = max(1, min(limit, 1000))
    result = await db.execute(
        select(ToolExecutionLog).order_by(ToolExecutionLog.created_at.desc()).limit(safe_limit)
    )
    return result.scalars().all()
