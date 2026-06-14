import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import routes_health, routes_session, websocket
from app.config import get_settings
from app.logging_config import configure_logging
from app.providers.provider_container import ProviderContainer, PROVIDER_CONTAINER_STATE_KEY
from app.storage.db import ensure_data_dirs


logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    configure_logging()
    settings = get_settings()
    ensure_data_dirs(settings.data_dir)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        container = ProviderContainer(settings)
        setattr(app.state, PROVIDER_CONTAINER_STATE_KEY, container)
        if settings.audio_prewarm_enabled:
            try:
                await container.prewarm_audio()
            except Exception:  # noqa: BLE001
                logger.exception("audio provider prewarm failed during startup")
        try:
            yield
        finally:
            await container.close()

    app = FastAPI(title=settings.app_name, lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.web_origin, "http://127.0.0.1:5173"],
        allow_origin_regex=r"^(https?://(127\.0\.0\.1|localhost)(:\d+)?|file://|null)$",
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(routes_health.router)
    app.include_router(routes_session.router)
    app.include_router(websocket.router)
    return app


app = create_app()
