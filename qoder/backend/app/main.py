from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import chat, documents, experiments, health, memory, projects, reports
from app.config import get_settings
from app.db.seekdb import SeekDBError, close_db, init_db
from app.services.assistant import Assistant
from app.services.embeddings import EmbeddingError, EmbeddingService
from app.services.powercontext import PowerContextError, close_powercontext, init_powercontext

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("labtrace")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    app.state.settings = settings
    app.state.db = await init_db(settings)
    app.state.pc = await init_powercontext(settings)
    app.state.embeddings = EmbeddingService(settings)
    app.state.assistant = Assistant(settings, app.state.embeddings)
    pc_status = await app.state.pc.status()
    logger.info(
        "LabTrace backend ready | seekdb=%s | powercontext ready=%s | llm=%s | embeddings=%s",
        app.state.db.version,
        pc_status.get("ready"),
        settings.llm_enabled,
        app.state.embeddings.provider,
    )
    try:
        yield
    finally:
        await app.state.assistant.close()
        await app.state.embeddings.close()
        await close_powercontext()
        await close_db()


app = FastAPI(
    title="LabTrace API",
    version="0.1.0",
    description="AI research memory and knowledge workbench on OceanBase seekdb + PowerContext",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(SeekDBError)
async def seekdb_error_handler(request: Request, exc: SeekDBError) -> JSONResponse:
    logger.error("seekdb error on %s: %s", request.url.path, exc)
    return JSONResponse(status_code=503, content={"detail": f"seekdb error: {exc}"})


@app.exception_handler(PowerContextError)
async def powercontext_error_handler(request: Request, exc: PowerContextError) -> JSONResponse:
    logger.error("powercontext error on %s: %s", request.url.path, exc)
    return JSONResponse(status_code=502, content={"detail": f"PowerContext error: {exc}"})


@app.exception_handler(EmbeddingError)
async def embedding_error_handler(request: Request, exc: EmbeddingError) -> JSONResponse:
    logger.warning("embedding error on %s: %s", request.url.path, exc)
    return JSONResponse(status_code=503, content={"detail": str(exc)})


for router in (
    health.router,
    projects.router,
    documents.router,
    experiments.router,
    memory.router,
    chat.router,
    reports.router,
):
    app.include_router(router)


@app.get("/")
async def root() -> dict[str, str]:
    return {"app": "LabTrace", "docs": "/docs", "health": "/api/health"}
