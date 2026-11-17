from contextlib import asynccontextmanager
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from heinzel_api import __version__
from heinzel_api.config import Settings, get_settings
from heinzel_api.db import make_sessionmaker
from heinzel_api.manifests import load_manifests
from heinzel_api.routes import auth, health, me, shell
from heinzel_api.tenants import load_tenants

UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    settings.check()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.settings = settings
        app.state.manifests = load_manifests(settings.modules_dir)
        app.state.tenants = load_tenants(settings.tenants_dir)
        app.state.tenant_ids = {}
        app.state.db = make_sessionmaker(settings.database_url)
        yield

    app = FastAPI(title="Heinzel API", version=__version__, lifespan=lifespan)

    @app.middleware("http")
    async def same_origin_writes(request: Request, call_next):
        """CSRF defence in depth (cookies are SameSite=Lax): a browser that sends an Origin
        header on a write must come from the host it is talking to."""
        origin = request.headers.get("origin")
        if request.method in UNSAFE_METHODS and origin:
            host = request.headers.get("x-forwarded-host") or request.headers.get("host")
            if urlsplit(origin).netloc != host:
                return JSONResponse({"detail": "cross_origin"}, status_code=403)
        return await call_next(request)

    app.include_router(health.router)
    app.include_router(shell.router)
    app.include_router(auth.router)
    app.include_router(me.router)
    return app


app = create_app()
