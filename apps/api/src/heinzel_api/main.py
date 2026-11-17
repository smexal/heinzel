from contextlib import asynccontextmanager

from fastapi import FastAPI

from heinzel_api import __version__
from heinzel_api.config import Settings, get_settings
from heinzel_api.manifests import load_manifests
from heinzel_api.routes import health, shell
from heinzel_api.tenants import load_tenants


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.settings = settings
        app.state.manifests = load_manifests(settings.modules_dir)
        app.state.tenants = load_tenants(settings.tenants_dir)
        yield

    app = FastAPI(title="Heinzel API", version=__version__, lifespan=lifespan)
    app.include_router(health.router)
    app.include_router(shell.router)
    return app


app = create_app()
