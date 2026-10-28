from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from app.api.deps import DbDep, PcDep
from app.schemas import (
    MemoryRetireRequest,
    MemoryReviseRequest,
    MemorySearchRequest,
    MemoryWriteRequest,
    SaveProgressRequest,
)
from app.services import memory as memory_service
from app.services import projects as project_service
from app.services.memory import MEMORY_KINDS, MemoryError
from app.services.projects import ProjectError

router = APIRouter(prefix="/api/memory", tags=["memory"])


async def _scope(db: Any, project_id: str) -> tuple[str, dict[str, Any]]:
    try:
        scope_id = await project_service.require_scope(db, project_id)
    except ProjectError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    project = await project_service.get_project(db, project_id)
    return scope_id, project or {}


@router.get("/kinds")
async def memory_kinds() -> dict[str, Any]:
    return {
        "kinds": [
            {"kind": kind, "label": memory_service.KIND_LABELS.get(kind, kind)} for kind in MEMORY_KINDS
        ]
    }


@router.post("")
async def write_memory(db: DbDep, pc: PcDep, payload: MemoryWriteRequest) -> dict[str, Any]:
    scope_id, _ = await _scope(db, payload.project_id)
    try:
        return await memory_service.write_memory(
            pc,
            scope_id=scope_id,
            kind=payload.kind,
            text=payload.text,
            reason=payload.reason,
            evidence=payload.evidence,
        )
    except MemoryError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("")
async def list_memories(
    db: DbDep, pc: PcDep, project_id: str, include_inactive: bool = False
) -> dict[str, Any]:
    scope_id, _ = await _scope(db, project_id)
    try:
        result = await memory_service.list_memories(pc, scope_id=scope_id, include_inactive=include_inactive)
    except MemoryError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"project_id": project_id, "scope_id": scope_id, **result}


@router.post("/search")
async def search_memories(db: DbDep, pc: PcDep, payload: MemorySearchRequest) -> dict[str, Any]:
    scope_id, _ = await _scope(db, payload.project_id)
    try:
        result = await memory_service.search_memories(
            pc, scope_id=scope_id, query=payload.query, limit=payload.limit
        )
    except MemoryError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"project_id": payload.project_id, "scope_id": scope_id, **result}


@router.post("/revise")
async def revise_memory(db: DbDep, pc: PcDep, payload: MemoryReviseRequest) -> dict[str, Any]:
    scope_id, _ = await _scope(db, payload.project_id)
    try:
        return await memory_service.revise_memory(
            pc,
            scope_id=scope_id,
            citation=payload.citation,
            kind=payload.kind,
            text=payload.text,
            reason=payload.reason,
        )
    except MemoryError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/retire")
async def retire_memory(db: DbDep, pc: PcDep, payload: MemoryRetireRequest) -> dict[str, Any]:
    scope_id, _ = await _scope(db, payload.project_id)
    try:
        return await memory_service.retire_memory(
            pc, scope_id=scope_id, citation=payload.citation, reason=payload.reason
        )
    except MemoryError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/save-progress")
async def save_progress(db: DbDep, pc: PcDep, payload: SaveProgressRequest) -> dict[str, Any]:
    scope_id, project = await _scope(db, payload.project_id)
    try:
        return await memory_service.save_progress(
            pc,
            scope_id=scope_id,
            project_name=project.get("name", payload.project_id),
            session_id=payload.session_id,
            summary=payload.summary,
            messages=[message.model_dump() for message in payload.messages],
            completed=payload.completed,
            conclusions=payload.conclusions,
            open_questions=payload.open_questions,
            next_steps=payload.next_steps,
            decisions=payload.decisions,
            failures=payload.failures,
            evidence=payload.evidence or {"project_id": payload.project_id},
        )
    except MemoryError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/restore")
async def restore_progress(db: DbDep, pc: PcDep, project_id: str) -> dict[str, Any]:
    scope_id, project = await _scope(db, project_id)
    result = await memory_service.restore_progress(
        pc, scope_id=scope_id, project_name=project.get("name", project_id)
    )
    return {"project_id": project_id, **result}


@router.post("/context")
async def prepare_context(db: DbDep, pc: PcDep, payload: MemorySearchRequest) -> dict[str, Any]:
    scope_id, _ = await _scope(db, payload.project_id)
    try:
        prepared = await memory_service.prepare_research_context(
            pc, scope_id=scope_id, query=payload.query, max_bytes=8000
        )
    except MemoryError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"project_id": payload.project_id, "scope_id": scope_id, **prepared}
