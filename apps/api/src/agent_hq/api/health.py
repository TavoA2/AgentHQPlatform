import logging
from typing import Literal

from fastapi import APIRouter, Request, Response, status
from pydantic import BaseModel

from agent_hq import __version__
from agent_hq.db import check_database

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/health", tags=["health"])


class HealthStatus(BaseModel):
    status: Literal["ok", "unavailable"]
    version: str
    checks: dict[str, Literal["ok", "fail"]] = {}


@router.get("/live")
async def live() -> HealthStatus:
    return HealthStatus(status="ok", version=__version__)


@router.get("/ready")
async def ready(request: Request, response: Response) -> HealthStatus:
    try:
        await check_database(request.app.state.engine)
    except Exception:
        logger.exception("readiness check failed", extra={"check": "database"})
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return HealthStatus(status="unavailable", version=__version__, checks={"database": "fail"})
    return HealthStatus(status="ok", version=__version__, checks={"database": "ok"})
