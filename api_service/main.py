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
    from core import AppTabManager, ListAppsHandler, PastActionsHandler, TimeService, TimeHandler, AlarmService, AlarmScheduler, PastActionsService, NotesManager, NotesCommandHandler, NoteTabHandler, DiaryService, DiaryHandler
    from core.context_window import ContextWindowHandler
    from endpoint import EndpointManager
    from api_service.database import ApiConfigManager
    from api_service.middleware import EncryptionMiddleware
    from api_service.routers import (
        agents_router,
        alarms_router,
        apps_router,
        auth_router,
        base,
        onboarding_router,
        providers_router,
        security_router,
        settings_router,
        stats_router,
        time_router,
        notes_router,
        diary_router,
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        import logging
        from log_service import DbLogHandler

        config_mgr = ApiConfigManager(use_encryption=use_encryption, key_name="db_key")
        app.state.config_mgr = config_mgr
        app.state.endpoint_mgr = EndpointManager(svc=config_mgr._svc)

        log_svc = app.state.endpoint_mgr.log
        logging.getLogger().addHandler(DbLogHandler(log_svc))
        app.state.agent_mgr = AgentManager(svc=config_mgr._svc)

        app_registry = AppRegistry(svc=config_mgr._svc)
        apps_dir = PROJECT_ROOT / "apps"
        app_registry.scan_apps_directory(str(apps_dir))
        app.state.app_registry = app_registry
        app.state.agent_app_mgr = AgentAppManager(svc=config_mgr._svc)

        app.state.past_actions_svc = PastActionsService(svc=config_mgr._svc)

        notes_manager = NotesManager(svc=config_mgr._svc)
        app.state.notes_manager = notes_manager

        app_tab_mgr = AppTabManager(svc=config_mgr._svc, app_registry=app_registry, agent_app_mgr=app.state.agent_app_mgr)
        app_tab_mgr.register_handler("__list_apps__", ListAppsHandler(app_registry, app.state.agent_app_mgr))
        app_tab_mgr.register_handler("__past_actions__", PastActionsHandler(app.state.past_actions_svc))
        app_tab_mgr.register_handler("__context_window__", ContextWindowHandler())
        app_tab_mgr.register_handler("__notes__", NotesCommandHandler())
        app_tab_mgr.register_handler("__note__", NoteTabHandler(notes_manager))
        app_tab_mgr.scan_app_handlers(str(apps_dir))
        app.state.app_tab_mgr = app_tab_mgr

        app.state.diary_svc = DiaryService(svc=config_mgr._svc)
        app.state.time_svc = TimeService(svc=config_mgr._svc)
        app.state.alarm_svc = AlarmService(svc=config_mgr._svc, time_svc=app.state.time_svc)
        app.state.alarm_scheduler = AlarmScheduler(
            svc=config_mgr._svc,
            time_svc=app.state.time_svc,
            agent_mgr=app.state.agent_mgr,
        )
        app.state.alarm_scheduler.start()
        app_tab_mgr.register_handler("__diary__", DiaryHandler(app.state.diary_svc, app.state.time_svc))
        app_tab_mgr.register_handler("__time__", TimeHandler(app.state.time_svc, app.state.alarm_svc))

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

        if app.state.alarm_scheduler.is_running:
            app.state.alarm_scheduler.stop()

    app = FastAPI(
        title="Cognithor API",
        description="REST API for the Cognithor autonomous agent system",
        version="0.1.0",
        lifespan=lifespan,
    )

    app.include_router(base.router)
    app.include_router(auth_router.router)
    app.include_router(alarms_router.router)
    app.include_router(onboarding_router.router)
    app.include_router(security_router.router)
    app.include_router(settings_router.router)
    app.include_router(providers_router.router)
    app.include_router(agents_router.router)
    app.include_router(apps_router.router)
    app.include_router(stats_router.router)
    app.include_router(time_router.router)
    app.include_router(notes_router.router)
    app.include_router(diary_router.router)

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
