from fastapi import Header, HTTPException

from app.config import settings


def require_service_key(x_service_key: str | None = Header(default=None)) -> None:
    if not x_service_key or x_service_key != settings.service_key:
        raise HTTPException(status_code=401, detail="Invalid service key")


def require_admin_key(x_admin_key: str | None = Header(default=None)) -> None:
    if not x_admin_key or x_admin_key != settings.admin_key:
        raise HTTPException(status_code=401, detail="Invalid admin key")
