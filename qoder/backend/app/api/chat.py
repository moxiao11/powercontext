from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from app.api.deps import AssistantDep, DbDep, PcDep
from app.schemas import ChatRequest
from app.services import projects as project_service
from app.services.projects import ProjectError

router = APIRouter(prefix="/api", tags=["assistant"])


@router.post("/chat")
async def chat(db: DbDep, pc: PcDep, assistant: AssistantDep, payload: ChatRequest) -> dict[str, Any]:
    try:
        scope_id = await project_service.require_scope(db, payload.project_id)
    except ProjectError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    history = _sessions.get(payload.session_id or "default", [])
    result = await assistant.answer(
        db,
        pc,
        project_id=payload.project_id,
        scope_id=scope_id,
        message=payload.message,
        history=history,
    )
    history.append({"role": "user", "content": payload.message})
    if result.get("answer"):
        history.append({"role": "assistant", "content": result["answer"]})
    _sessions[payload.session_id or "default"] = history[-20:]

    return {
        "project_id": payload.project_id,
        "session_id": payload.session_id or "default",
        **result,
    }


@router.get("/chat/sessions/{session_id}")
async def get_session(session_id: str) -> dict[str, Any]:
    return {"session_id": session_id, "messages": _sessions.get(session_id, [])}


@router.delete("/chat/sessions/{session_id}")
async def clear_session(session_id: str) -> dict[str, Any]:
    _sessions.pop(session_id, None)
    return {"cleared": True, "session_id": session_id}


# In-process conversation history. Deliberately NOT the cross-session memory store:
# durable research memory lives in PowerContext (see /api/memory/save-progress).
_sessions: dict[str, list[dict[str, str]]] = {}
