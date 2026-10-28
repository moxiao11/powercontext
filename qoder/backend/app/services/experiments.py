"""Experiment records stored in seekdb, with full-text search and comparison helpers."""

from __future__ import annotations

import json
import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from app.db.seekdb import SeekDB

logger = logging.getLogger(__name__)

_COLUMNS = (
    "experiment_id, project_id, name, objective, hypothesis, method, model_config, dataset, "
    "result_summary, metrics, issues, failure_reason, next_steps, status, log_markdown, "
    "searchable_text, created_at, updated_at"
)


class ExperimentError(ValueError):
    pass


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _searchable_text(values: dict[str, Any]) -> str:
    parts = [
        str(values.get("name") or ""),
        str(values.get("objective") or ""),
        str(values.get("hypothesis") or ""),
        str(values.get("method") or ""),
        str(values.get("dataset") or ""),
        str(values.get("result_summary") or ""),
        str(values.get("issues") or ""),
        str(values.get("failure_reason") or ""),
        str(values.get("next_steps") or ""),
        str(values.get("log_markdown") or ""),
    ]
    config = values.get("model_config")
    if config:
        parts.append(config if isinstance(config, str) else json.dumps(config, ensure_ascii=False))
    return "\n".join(part for part in parts if part and part != "None")


def _row_to_dict(row: dict[str, Any]) -> dict[str, Any]:
    out = dict(row)
    for key in ("metrics", "model_config"):
        raw = out.get(key)
        if isinstance(raw, str) and raw:
            try:
                out[key] = json.loads(raw)
            except json.JSONDecodeError:
                pass
    for key in ("created_at", "updated_at"):
        value = out.get(key)
        if isinstance(value, datetime):
            out[key] = value.isoformat()
    out.pop("searchable_text", None)
    return out


async def create_experiment(db: SeekDB, payload: dict[str, Any]) -> dict[str, Any]:
    experiment_id = f"exp_{uuid.uuid4().hex[:16]}"
    now = _now()
    values = {
        "experiment_id": experiment_id,
        "project_id": payload["project_id"],
        "name": payload["name"],
        "objective": payload.get("objective"),
        "hypothesis": payload.get("hypothesis"),
        "method": payload.get("method"),
        "model_config": json.dumps(payload.get("model_config"), ensure_ascii=False)
        if payload.get("model_config")
        else None,
        "dataset": payload.get("dataset"),
        "result_summary": payload.get("result_summary"),
        "metrics": json.dumps(payload["metrics"], ensure_ascii=False) if payload.get("metrics") else None,
        "issues": payload.get("issues"),
        "failure_reason": payload.get("failure_reason"),
        "next_steps": payload.get("next_steps"),
        "status": payload.get("status") or "planned",
        "log_markdown": payload.get("log_markdown"),
    }
    searchable = _searchable_text(values)
    await db.execute(
        "INSERT INTO lt_experiments (experiment_id, project_id, name, objective, hypothesis, method, "
        "model_config, dataset, result_summary, metrics, issues, failure_reason, next_steps, status, "
        "log_markdown, searchable_text, created_at, updated_at) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        (
            experiment_id,
            values["project_id"],
            values["name"],
            values["objective"],
            values["hypothesis"],
            values["method"],
            values["model_config"],
            values["dataset"],
            values["result_summary"],
            values["metrics"],
            values["issues"],
            values["failure_reason"],
            values["next_steps"],
            values["status"],
            values["log_markdown"],
            searchable,
            now,
            now,
        ),
    )
    logger.info("created experiment %s in project %s", experiment_id, values["project_id"])
    return _row_to_dict({**values, "searchable_text": searchable, "created_at": now, "updated_at": now})


_UPDATABLE = (
    "name",
    "objective",
    "hypothesis",
    "method",
    "dataset",
    "result_summary",
    "issues",
    "failure_reason",
    "next_steps",
    "status",
    "log_markdown",
)


async def update_experiment(
    db: SeekDB, experiment_id: str, project_id: str, payload: dict[str, Any]
) -> dict[str, Any] | None:
    existing = await get_experiment(db, experiment_id, project_id)
    if existing is None:
        return None
    merged = {**existing}
    for key in _UPDATABLE:
        if payload.get(key) is not None:
            merged[key] = payload[key]
    if payload.get("model_config") is not None:
        merged["model_config"] = payload["model_config"]
    if payload.get("metrics") is not None:
        merged["metrics"] = payload["metrics"]

    await db.execute(
        "UPDATE lt_experiments SET name=%s, objective=%s, hypothesis=%s, method=%s, model_config=%s, "
        "dataset=%s, result_summary=%s, metrics=%s, issues=%s, failure_reason=%s, next_steps=%s, "
        "status=%s, log_markdown=%s, searchable_text=%s, updated_at=%s "
        "WHERE experiment_id=%s AND project_id=%s",
        (
            merged["name"],
            merged.get("objective"),
            merged.get("hypothesis"),
            merged.get("method"),
            json.dumps(merged["model_config"], ensure_ascii=False) if merged.get("model_config") else None,
            merged.get("dataset"),
            merged.get("result_summary"),
            json.dumps(merged["metrics"], ensure_ascii=False) if merged.get("metrics") else None,
            merged.get("issues"),
            merged.get("failure_reason"),
            merged.get("next_steps"),
            merged.get("status") or "planned",
            merged.get("log_markdown"),
            _searchable_text(merged),
            _now(),
            experiment_id,
            project_id,
        ),
    )
    return await get_experiment(db, experiment_id, project_id)


async def get_experiment(db: SeekDB, experiment_id: str, project_id: str) -> dict[str, Any] | None:
    rows = await db.query(
        f"SELECT {_COLUMNS} FROM lt_experiments WHERE experiment_id = %s AND project_id = %s LIMIT 1",
        (experiment_id, project_id),
    )
    return _row_to_dict(rows[0]) if rows else None


async def list_experiments(
    db: SeekDB,
    project_id: str,
    *,
    dataset: str | None = None,
    status: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    sql = f"SELECT {_COLUMNS} FROM lt_experiments WHERE project_id = %s"
    params: list[Any] = [project_id]
    if dataset:
        sql += " AND dataset = %s"
        params.append(dataset)
    if status:
        sql += " AND status = %s"
        params.append(status)
    sql += f" ORDER BY created_at DESC LIMIT {max(1, min(limit, 500))}"
    return [_row_to_dict(row) for row in await db.query(sql, params)]


async def search_experiments(db: SeekDB, project_id: str, query: str, limit: int = 8) -> list[dict[str, Any]]:
    match_expr = "MATCH(searchable_text) AGAINST (%s IN NATURAL LANGUAGE MODE)"
    rows = await db.query(
        f"SELECT {_COLUMNS}, {match_expr} AS relevance FROM lt_experiments "
        f"WHERE project_id = %s AND {match_expr} "
        f"ORDER BY relevance DESC, created_at DESC LIMIT {max(1, min(limit, 50))}",
        (query.strip(), project_id, query.strip()),
    )
    results = [_row_to_dict(row) for row in rows]
    for item in results:
        item["relevance"] = round(float(item.get("relevance") or 0.0), 6)
    return results


async def delete_experiment(db: SeekDB, experiment_id: str, project_id: str) -> bool:
    affected = await db.execute(
        "DELETE FROM lt_experiments WHERE experiment_id = %s AND project_id = %s",
        (experiment_id, project_id),
    )
    return bool(affected)


async def import_metrics_json(
    db: SeekDB, project_id: str, payload: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    created = []
    for item in payload:
        if not isinstance(item, dict) or not item.get("name"):
            raise ExperimentError("every imported record needs at least a 'name' field")
        item.setdefault("project_id", project_id)
        if item["project_id"] != project_id:
            raise ExperimentError("imported records must belong to the target project")
        created.append(await create_experiment(db, item))
    return created


def compare_experiments(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    """Field-by-field diff of two experiment records, including metric deltas."""
    fields = (
        "name",
        "objective",
        "hypothesis",
        "method",
        "model_config",
        "dataset",
        "result_summary",
        "issues",
        "failure_reason",
        "next_steps",
        "status",
    )
    differences = []
    for field in fields:
        lv, rv = left.get(field), right.get(field)
        if lv != rv:
            differences.append({"field": field, "left": lv, "right": rv})

    metric_deltas = []
    lm = left.get("metrics") or {}
    rm = right.get("metrics") or {}
    for key in sorted(set(lm) | set(rm)):
        lv, rv = lm.get(key), rm.get(key)
        delta = round(rv - lv, 6) if isinstance(lv, (int, float)) and isinstance(rv, (int, float)) else None
        metric_deltas.append({"metric": key, "left": lv, "right": rv, "delta": delta})

    return {
        "left": {"experiment_id": left["experiment_id"], "name": left.get("name")},
        "right": {"experiment_id": right["experiment_id"], "name": right.get("name")},
        "differences": differences,
        "metric_deltas": metric_deltas,
    }


def best_experiment(
    experiments: list[dict[str, Any]], metric: str, higher_is_better: bool = True
) -> dict[str, Any] | None:
    scored = [
        item
        for item in experiments
        if isinstance(item.get("metrics"), dict) and isinstance(item["metrics"].get(metric), (int, float))
    ]
    if not scored:
        return None
    return max(scored, key=lambda item: item["metrics"][metric] * (1 if higher_is_better else -1))


async def experiments_in_range(
    db: SeekDB, project_id: str, start: datetime, end: datetime
) -> list[dict[str, Any]]:
    rows = await db.query(
        f"SELECT {_COLUMNS} FROM lt_experiments "
        "WHERE project_id = %s AND (created_at BETWEEN %s AND %s OR updated_at BETWEEN %s AND %s) "
        "ORDER BY created_at",
        (project_id, start, end, start, end),
    )
    return [_row_to_dict(row) for row in rows]


async def documents_in_range(
    db: SeekDB, project_id: str, start: datetime, end: datetime
) -> list[dict[str, Any]]:
    rows = await db.query(
        "SELECT doc_id, title, topic, file_name, file_type, page_count, chunk_count, created_at "
        "FROM lt_documents WHERE project_id = %s AND created_at BETWEEN %s AND %s ORDER BY created_at",
        (project_id, start, end),
    )
    for row in rows:
        if isinstance(row.get("created_at"), datetime):
            row["created_at"] = row["created_at"].isoformat()
    return rows
