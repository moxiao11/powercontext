"""Research projects: seekdb metadata row bound to a PowerContext Scope for memory isolation."""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from app.db.seekdb import SeekDB
from app.services.powercontext import PowerContextClient, PowerContextError

logger = logging.getLogger(__name__)


class ProjectError(RuntimeError):
    pass


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


async def create_project(
    db: SeekDB,
    pc: PowerContextClient,
    *,
    name: str,
    description: str | None,
    research_profile: str | None = None,
) -> dict[str, Any]:
    project_id = f"prj_{uuid.uuid4().hex[:16]}"
    now = _now()
    scope_id: str | None = None
    scope_error: str | None = None
    try:
        scope = await pc.create_scope(
            title=name,
            summary=description or f"LabTrace research project {name}",
            idempotency_key=f"labtrace-{project_id}",
        )
        scope_id = scope.get("scope_id")
    except PowerContextError as exc:
        scope_error = str(exc)
        logger.warning("PowerContext scope creation failed for %s: %s", project_id, exc)

    await db.execute(
        "INSERT INTO lt_projects (project_id, name, description, pc_scope_id, created_at, updated_at) "
        "VALUES (%s,%s,%s,%s,%s,%s)",
        (project_id, name, description, scope_id, now, now),
    )

    profile_written = None
    if scope_id and research_profile and research_profile.strip():
        from app.services.memory import write_memory

        try:
            profile_written = await write_memory(
                pc,
                scope_id=scope_id,
                kind="research_profile",
                text=research_profile.strip(),
                reason=f"project {project_id} creation",
                evidence={"project_id": project_id},
            )
        except Exception as exc:  # noqa: BLE001 - profile write is best effort
            logger.warning("research profile write failed: %s", exc)

    return {
        "project_id": project_id,
        "name": name,
        "description": description,
        "pc_scope_id": scope_id,
        "pc_scope_error": scope_error,
        "research_profile": profile_written,
        "created_at": now.isoformat(),
        "updated_at": now.isoformat(),
    }


async def list_projects(db: SeekDB) -> list[dict[str, Any]]:
    rows = await db.query(
        "SELECT p.project_id, p.name, p.description, p.pc_scope_id, p.created_at, p.updated_at, "
        "(SELECT COUNT(*) FROM lt_documents d WHERE d.project_id = p.project_id) AS document_count, "
        "(SELECT COUNT(*) FROM lt_experiments e WHERE e.project_id = p.project_id) AS experiment_count "
        "FROM lt_projects p ORDER BY p.created_at DESC"
    )
    for row in rows:
        for key in ("created_at", "updated_at"):
            if isinstance(row.get(key), datetime):
                row[key] = row[key].isoformat()
    return rows


async def get_project(db: SeekDB, project_id: str) -> dict[str, Any] | None:
    rows = await db.query(
        "SELECT project_id, name, description, pc_scope_id, created_at, updated_at "
        "FROM lt_projects WHERE project_id = %s LIMIT 1",
        (project_id,),
    )
    if not rows:
        return None
    row = rows[0]
    for key in ("created_at", "updated_at"):
        if isinstance(row.get(key), datetime):
            row[key] = row[key].isoformat()
    return row


async def require_scope(db: SeekDB, project_id: str) -> str:
    project = await get_project(db, project_id)
    if project is None:
        raise ProjectError(f"project {project_id} not found")
    if not project.get("pc_scope_id"):
        raise ProjectError(
            f"project {project_id} has no PowerContext scope (Server unreachable at creation time)"
        )
    return str(project["pc_scope_id"])


async def update_project(
    db: SeekDB, pc: PowerContextClient, project_id: str, *, name: str | None, description: str | None
) -> dict[str, Any] | None:
    project = await get_project(db, project_id)
    if project is None:
        return None
    new_name = name if name is not None else project["name"]
    new_description = description if description is not None else project["description"]
    await db.execute(
        "UPDATE lt_projects SET name=%s, description=%s, updated_at=%s WHERE project_id=%s",
        (new_name, new_description, _now(), project_id),
    )
    return await get_project(db, project_id)


async def delete_project(db: SeekDB, pc: PowerContextClient | None, project_id: str) -> dict[str, Any]:
    """Delete a project's seekdb rows and retire its PowerContext memories.

    PowerContext has no scope-deletion API, so memories are retired entry by entry. Retirement
    is best effort: a PowerContext outage must not leave the seekdb rows behind, but the caller
    is told how many memories could not be retired so the residue is never silent.
    """
    project = await get_project(db, project_id)
    scope_id = str(project["pc_scope_id"]) if project and project.get("pc_scope_id") else None

    retired = 0
    memory_errors: list[str] = []
    if scope_id and pc is not None:
        from app.services import memory as memory_service

        try:
            stored = await memory_service.list_memories(pc, scope_id=scope_id)
            for entry in stored.get("entries", []):
                citation = entry.get("citation")
                if not citation:
                    continue
                try:
                    await memory_service.retire_memory(
                        pc,
                        scope_id=scope_id,
                        citation=citation,
                        reason=f"项目 {project_id} 已删除",
                    )
                    retired += 1
                except memory_service.MemoryError as exc:
                    memory_errors.append(str(exc))
        except memory_service.MemoryError as exc:
            memory_errors.append(str(exc))

    await db.execute("DELETE FROM lt_document_chunks WHERE project_id = %s", (project_id,))
    await db.execute("DELETE FROM lt_documents WHERE project_id = %s", (project_id,))
    await db.execute("DELETE FROM lt_experiments WHERE project_id = %s", (project_id,))
    affected = await db.execute("DELETE FROM lt_projects WHERE project_id = %s", (project_id,))
    return {
        "deleted": bool(affected),
        "scope_id": scope_id,
        "retired_memories": retired,
        "memory_errors": memory_errors,
    }
