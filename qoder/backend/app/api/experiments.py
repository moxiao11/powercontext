from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from app.api.deps import DbDep, PcDep
from app.schemas import (
    ExperimentCreate,
    ExperimentMemoryRequest,
    ExperimentQueryRequest,
    ExperimentUpdate,
)
from app.services import experiments as exp_service
from app.services import memory as memory_service
from app.services.experiments import ExperimentError
from app.services.memory import MemoryError
from app.services.projects import ProjectError

router = APIRouter(prefix="/api/experiments", tags=["experiments"])


@router.post("")
async def create_experiment(db: DbDep, payload: ExperimentCreate) -> dict[str, Any]:
    # by_alias keeps the `model_config` key the service layer (and the UI) expects; dumping by
    # field name would emit `model_config_json` and silently drop the whole configuration.
    return await exp_service.create_experiment(db, payload.model_dump(by_alias=True))


@router.get("")
async def list_experiments(
    db: DbDep, project_id: str, dataset: str | None = None, status: str | None = None, limit: int = 100
) -> dict[str, Any]:
    rows = await exp_service.list_experiments(db, project_id, dataset=dataset, status=status, limit=limit)
    return {"experiments": rows, "total": len(rows)}


@router.post("/search")
async def search_experiments(db: DbDep, payload: ExperimentQueryRequest) -> dict[str, Any]:
    rows = await exp_service.search_experiments(db, payload.project_id, payload.query, payload.limit)
    return {
        "query": payload.query,
        "engine": f"OceanBase seekdb {db.version}",
        "sql_mode": "FULLTEXT MATCH ... AGAINST",
        "experiments": rows,
        "total": len(rows),
    }


@router.post("/import")
async def import_experiments(db: DbDep, project_id: str, payload: list[dict[str, Any]]) -> dict[str, Any]:
    try:
        created = await exp_service.import_metrics_json(db, project_id, payload)
    except ExperimentError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"imported": len(created), "experiments": created}


@router.get("/compare")
async def compare_experiments(db: DbDep, project_id: str, left: str, right: str) -> dict[str, Any]:
    left_row = await exp_service.get_experiment(db, left, project_id)
    right_row = await exp_service.get_experiment(db, right, project_id)
    if left_row is None or right_row is None:
        raise HTTPException(status_code=404, detail="one of the experiments was not found in this project")
    return exp_service.compare_experiments(left_row, right_row)


@router.get("/best")
async def best_experiment(
    db: DbDep, project_id: str, metric: str, higher_is_better: bool = True
) -> dict[str, Any]:
    rows = await exp_service.list_experiments(db, project_id, limit=500)
    best = exp_service.best_experiment(rows, metric, higher_is_better)
    if best is None:
        return {"metric": metric, "best": None, "note": f"没有实验记录了指标 {metric}"}
    return {"metric": metric, "higher_is_better": higher_is_better, "best": best}


@router.post("/{experiment_id}/to-memory")
async def experiment_to_memory(
    db: DbDep, pc: PcDep, experiment_id: str, payload: ExperimentMemoryRequest
) -> dict[str, Any]:
    """Persist this experiment's conclusion, decision, failure and plan into PowerContext."""
    try:
        return await memory_service.sync_experiment_to_memory(
            db,
            pc,
            project_id=payload.project_id,
            experiment_id=experiment_id,
            conclusion=payload.conclusion,
            decision=payload.decision,
            next_steps=payload.next_steps,
            include_failure=payload.include_failure,
        )
    except ProjectError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except MemoryError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/{experiment_id}")
async def get_experiment(db: DbDep, experiment_id: str, project_id: str) -> dict[str, Any]:
    row = await exp_service.get_experiment(db, experiment_id, project_id)
    if row is None:
        raise HTTPException(status_code=404, detail="experiment not found")
    return row


@router.patch("/{experiment_id}")
async def update_experiment(
    db: DbDep, experiment_id: str, project_id: str, payload: ExperimentUpdate
) -> dict[str, Any]:
    row = await exp_service.update_experiment(
        db, experiment_id, project_id, payload.model_dump(exclude_unset=True, by_alias=True)
    )
    if row is None:
        raise HTTPException(status_code=404, detail="experiment not found")
    return row


@router.delete("/{experiment_id}")
async def delete_experiment(db: DbDep, experiment_id: str, project_id: str) -> dict[str, Any]:
    deleted = await exp_service.delete_experiment(db, experiment_id, project_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="experiment not found")
    return {"deleted": True, "experiment_id": experiment_id}
