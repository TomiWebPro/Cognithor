"""FastAPI server entry point for Cognithor.

create_app() builds the FastAPI application with routers and middleware.
Module-level app variable supports uvicorn imports.
CLI functions (main, detect_db_encryption, recovery) moved to cli_service/.
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

DB_PATH = PROJECT_ROOT / "data" / "cognithor.db"

PYSQLCIPHER_AVAILABLE = False
try:
    from pysqlcipher3 import dbapi2 as _pysqlcipher
    PYSQLCIPHER_AVAILABLE = True
except ImportError:
    pass


def create_app(use_encryption: bool = False):
    from contextlib import asynccontextmanager
    from fastapi import FastAPI
    from agents_service import AgentManager
    from apps_service import AppRegistry, AgentAppManager
    from core import AppTabManager, ListAppsHandler, TimeService, PastActionsService
    from apps.list_directory.handler import ListDirectoryHandler
    from endpoint import EndpointManager
    from api_service.database import ApiConfigManager
    from api_service.middleware import EncryptionMiddleware
    from api_service.routers import (
        agents_router,
        apps_router,
        auth_router,
        base,
        onboarding_router,
        providers_router,
        security_router,
        settings_router,
        time_router,
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        config_mgr = ApiConfigManager(use_encryption=use_encryption, key_name="db_key")
        app.state.config_mgr = config_mgr
        app.state.endpoint_mgr = EndpointManager(svc=config_mgr._svc)
        app.state.agent_mgr = AgentManager(svc=config_mgr._svc)

        app_registry = AppRegistry(svc=config_mgr._svc)
        apps_dir = PROJECT_ROOT / "apps"
        app_registry.scan_apps_directory(str(apps_dir))
        app.state.app_registry = app_registry
        app.state.agent_app_mgr = AgentAppManager(svc=config_mgr._svc)

        app_tab_mgr = AppTabManager(svc=config_mgr._svc, app_registry=app_registry)
        app_tab_mgr.register_handler("list_directory", ListDirectoryHandler())
        app_tab_mgr.register_handler("__list_apps__", ListAppsHandler(app_registry))

        app.state.time_svc = TimeService(svc=config_mgr._svc)
        app.state.past_actions_svc = PastActionsService(svc=config_mgr._svc)

        app.state.encryption_in_progress = False

        degraded = []
        if config_mgr._svc.is_degraded():
            degraded.append(("ApiConfig", config_mgr._svc.degraded_reason))
        if app.state.endpoint_mgr.tracker._svc.is_degraded():
            degraded.append(("Tracker", app.state.endpoint_mgr.tracker._svc.degraded_reason))
        if degraded:
            from cli_service.server import _recovery_prompt
            _recovery_prompt(degraded)

        yield

    app = FastAPI(
        title="Cognithor API",
        description="REST API for the Cognithor autonomous agent system",
        version="0.1.0",
        lifespan=lifespan,
    )

    app.include_router(base.router)
    app.include_router(auth_router.router)
    app.include_router(onboarding_router.router)
    app.include_router(security_router.router)
    app.include_router(settings_router.router)
    app.include_router(providers_router.router)
    app.include_router(agents_router.router)
    app.include_router(apps_router.router)
    app.include_router(time_router.router)

    app.add_middleware(EncryptionMiddleware)

    return app


app = None

if __name__ != "__main__":
    try:
        from cli_service.server import detect_db_encryption
        use_enc = detect_db_encryption()
        app = create_app(use_encryption=use_enc)
    except SystemExit:
        app = create_app(use_encryption=False)


def main():
    from cli_service.server import main as server_main
    server_main()


if __name__ == "__main__":
    main()
