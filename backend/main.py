"""Masar AI — FastAPI application entrypoint.

Startup is deliberately non-fatal on missing optional credentials. The
capability report is logged once, naming exactly which capability each absent
key degrades, and the process continues (§4.3). A demo that dies because a free
tier expired is a failed demo.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.api.routes import health
from backend.config.settings import get_settings
from backend.services.logging import configure_logging, get_logger

log = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    configure_logging()
    settings = get_settings()
    report = settings.capability_report()

    log.info(
        "masar.startup",
        environment=settings.app_env,
        providers=report["providers_available"],
        degraded_mode=report["degraded_mode"],
    )
    for note in report["degradations"]:
        log.warning("masar.capability_degraded", detail=note)

    if report["degraded_mode"]:
        log.warning(
            "masar.degraded_mode",
            detail="No cloud LLM provider configured — all inference runs locally on Ollama. "
            "Responses will carry degraded_mode=true so the UI can badge them honestly.",
        )

    yield

    log.info("masar.shutdown")


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="Masar AI",
        description=(
            "Agentic RAG over Dubai RTA open data. Independent academic project — "
            "not affiliated with or endorsed by the Roads and Transport Authority."
        ),
        version="0.1.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
    )

    app.include_router(health.router)

    return app


app = create_app()
