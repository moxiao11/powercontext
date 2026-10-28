from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from app.api.deps import DbDep, EmbeddingsDep, PcDep
from app.config import get_settings

router = APIRouter(tags=["health"])


@router.get("/api/health")
async def health(db: DbDep, pc: PcDep, embeddings: EmbeddingsDep) -> dict[str, Any]:
    settings = get_settings()
    pc_status = await pc.status()
    return {
        "status": "ok" if pc_status.get("ready") else "degraded",
        "seekdb": {"connected": True, "mode": db.mode, "version": db.version},
        "powercontext": {
            "url": pc.base_url,
            "reachable": pc_status.get("reachable", False),
            "ready": pc_status.get("ready", False),
        },
        "llm": {
            "configured": settings.llm_enabled,
            "model": settings.chat_model or None,
            "base_url": settings.openai_base_url or None,
        },
        "embedding": {"provider": embeddings.provider, "dimension": embeddings.dimension},
    }


@router.get("/api/meta")
async def meta() -> dict[str, Any]:
    settings = get_settings()
    return {
        "app": "LabTrace",
        "version": "0.1.0",
        "seekdb_mode": settings.seekdb_mode,
        "llm_enabled": settings.llm_enabled,
        "embedding_provider": "openai-compatible"
        if settings.embedding_api_enabled
        else "local-hash-fallback",
        "embedding_dimension": settings.embedding_dimension,
        "powercontext_url": settings.powercontext_url,
        "max_upload_mb": settings.labtrace_max_upload_mb,
    }
