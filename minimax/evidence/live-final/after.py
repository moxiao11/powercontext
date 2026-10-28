"""Taskboard service with status filtering, sorting, and pagination."""


def list_tasks(tasks, *, status=None, offset=0, limit=20):
    if offset < 0 or limit <= 0:
        raise ValueError("offset must be >= 0 and limit must be > 0")

    if status is not None and status not in {"todo", "doing", "done"}:
        raise ValueError("status must be one of: todo, doing, done")

    filtered = tasks if status is None else [task for task in tasks if task.get("status") == status]
    ordered = sorted(filtered, key=lambda task: task["id"])
    return [dict(task) for task in ordered[offset : offset + limit]]
