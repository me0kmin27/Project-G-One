from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select

from .api import router
from .config import Settings
from .db import configure_database
from .migrations import upgrade_database
from .models import VpnNetwork, VpnPeer
from .wireguard import apply_config, render_server_config


def restore_wireguard(session_factory, settings: Settings) -> None:
    """Rebuild the runtime interface from database state after a container restart."""
    if not settings.wireguard_private_key:
        return
    with session_factory() as session:
        network = session.scalar(
            select(VpnNetwork).order_by(VpnNetwork.updated_at.desc()).limit(1)
        )
        if network is None:
            return
        peers = session.scalars(select(VpnPeer).where(VpnPeer.network_id == network.id)).all()
        apply_config(
            render_server_config(network, peers, settings.wireguard_private_key), settings
        )


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_environment()
    engine, session_factory = configure_database(settings.database_url)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Schema changes must be explicit and repeatable in every environment.
        # Running this before accepting traffic also keeps a newly deployed API
        # from serving against an older schema.
        upgrade_database(settings.database_url)
        restore_wireguard(session_factory, settings)
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
    web_dir = Path(__file__).parent / "web"
    app.mount("/assets", StaticFiles(directory=web_dir), name="assets")

    @app.get("/", include_in_schema=False)
    def admin_console() -> FileResponse:
        return FileResponse(web_dir / "index.html")

    return app


app = create_app()
