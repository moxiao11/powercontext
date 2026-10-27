"""Reference implementation, written locally; not a MiniMax generation record."""


def list_tasks(tasks, *, status=None, offset=0, limit=20):
    if offset < 0 or limit <= 0:
        raise ValueError("offset must be >= 0 and limit must be > 0")
    if status is not None and status not in {"todo", "doing", "done"}:
        raise ValueError("status must be todo, doing, or done")
    selected = [task for task in tasks if status is None or task["status"] == status]
    ordered = sorted(selected, key=lambda task: task["id"])
    return [dict(task) for task in ordered[offset : offset + limit]]
