from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from endpoint import EndpointManager

from .database import ApiConfigManager
from .middleware import CryptoMiddleware
from .routers import (
    auth_router,
    base,
    onboarding_router,
    providers_router,
    security_router,
    settings_router,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.config_mgr = ApiConfigManager()
    app.state.endpoint_mgr = EndpointManager()
    yield


app = FastAPI(
    title="Cognithor API",
    description="REST API for the Cognithor autonomous agent system",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(CryptoMiddleware)

app.include_router(base.router)
app.include_router(auth_router.router)
app.include_router(onboarding_router.router)
app.include_router(security_router.router)
app.include_router(settings_router.router)
app.include_router(providers_router.router)


def main():
    import uvicorn

    config_mgr = ApiConfigManager()
    config = config_mgr.get_all_config()
    host = config.get("api_host", "0.0.0.0")
    port = int(config.get("api_port", "8000"))

    uvicorn.run(
        "api_service.main:app",
        host=host,
        port=port,
    )


if __name__ == "__main__":
    main()
