"""Initial Taskboard service: sorted pagination, status filtering not implemented."""


def list_tasks(tasks, *, status=None, offset=0, limit=20):
    if offset < 0 or limit <= 0:
        raise ValueError("offset must be >= 0 and limit must be > 0")
    ordered = sorted(tasks, key=lambda task: task["id"])
    return [dict(task) for task in ordered[offset : offset + limit]]
