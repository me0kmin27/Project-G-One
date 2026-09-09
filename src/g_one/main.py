from contextlib import asynccontextmanager

from fastapi import FastAPI

from .api import router
from .config import Settings
from .db import Base, configure_database


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_environment()
    engine, session_factory = configure_database(settings.database_url)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        Base.metadata.create_all(engine)
        yield
        engine.dispose()

    app = FastAPI(
        title="Project G-One Control Plane",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.session_factory = session_factory
    app.include_router(router)
    return app


app = create_app()

