from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from app.api.deps import DbDep, PcDep
from app.schemas import ProjectCreate
from app.services import projects as project_service
from app.services.projects import ProjectError

router = APIRouter(prefix="/api/projects", tags=["projects"])


@router.post("")
async def create_project(db: DbDep, pc: PcDep, payload: ProjectCreate) -> dict[str, Any]:
    try:
        return await project_service.create_project(
            db,
            pc,
            name=payload.name.strip(),
            description=payload.description,
            research_profile=payload.research_profile,
        )
    except ProjectError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("")
async def list_projects(db: DbDep) -> dict[str, Any]:
    return {"projects": await project_service.list_projects(db)}


@router.get("/{project_id}")
async def get_project(db: DbDep, project_id: str) -> dict[str, Any]:
    project = await project_service.get_project(db, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")
    return project


@router.patch("/{project_id}")
async def update_project(db: DbDep, pc: PcDep, project_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    project = await project_service.update_project(
        db, pc, project_id, name=payload.get("name"), description=payload.get("description")
    )
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")
    return project


@router.delete("/{project_id}")
async def delete_project(db: DbDep, pc: PcDep, project_id: str) -> dict[str, Any]:
    result = await project_service.delete_project(db, pc, project_id)
    if not result["deleted"]:
        raise HTTPException(status_code=404, detail="project not found")
    return {"project_id": project_id, **result}
