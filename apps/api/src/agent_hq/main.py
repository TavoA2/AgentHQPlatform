from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from agent_hq import __version__
from agent_hq.api import health
from agent_hq.config import Settings, get_settings
from agent_hq.db import create_engine
from agent_hq.logging import configure_logging


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.engine = create_engine(settings)
        yield
        await app.state.engine.dispose()

    app = FastAPI(
        title=f"{settings.brand_name} Agent HQ API",
        version=__version__,
        lifespan=lifespan,
        # Interactive docs only outside production.
        docs_url=None if settings.environment == "production" else "/docs",
        redoc_url=None,
    )
    app.include_router(health.router)
    return app
