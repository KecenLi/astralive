from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import routes_health, routes_session, websocket
from app.config import get_settings
from app.logging_config import configure_logging
from app.storage.db import ensure_data_dirs


def create_app() -> FastAPI:
    configure_logging()
    settings = get_settings()
    ensure_data_dirs(settings.data_dir)
    app = FastAPI(title=settings.app_name)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.web_origin, "http://127.0.0.1:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(routes_health.router)
    app.include_router(routes_session.router)
    app.include_router(websocket.router)
    return app


app = create_app()

