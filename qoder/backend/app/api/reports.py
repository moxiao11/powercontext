from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from app.api.deps import AssistantDep, DbDep, PcDep
from app.schemas import ReportRequest
from app.services import projects as project_service
from app.services import reports as report_service

router = APIRouter(prefix="/api/reports", tags=["reports"])


@router.post("/generate")
async def generate_report(
    db: DbDep, pc: PcDep, assistant: AssistantDep, payload: ReportRequest
) -> dict[str, Any]:
    project = await project_service.get_project(db, payload.project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")
    try:
        return await report_service.generate_report(
            db,
            pc,
            assistant,
            project_id=payload.project_id,
            project_name=project.get("name", payload.project_id),
            scope_id=project.get("pc_scope_id"),
            start=payload.start_date,
            end=payload.end_date,
            title=payload.title,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/default-range")
async def default_range() -> dict[str, Any]:
    start, end = report_service.default_report_range()
    return {"start_date": start.isoformat(), "end_date": end.isoformat()}
