from __future__ import annotations

from pathlib import Path

from .common import digest, inside
from .ingest import collect, fingerprint


def assess_state(state: dict | None, current_fingerprint: str) -> dict:
    if state is None:
        return {"status": "empty", "completed": [], "pending": ["implement", "verify"],
                "validation": "missing", "next_action": "implement"}
    result = dict(state)
    if state.get("fingerprint") != current_fingerprint:
        result.update(validation="stale", next_action="revalidate",
                      pending=list(dict.fromkeys([*state.get("pending", []), "revalidate"])))
    else:
        result["validation"] = "current" if state.get("checks_passed") else "not_passed"
        result["next_action"] = (state.get("pending") or ["complete"])[0]
    return result


def build_context(root: Path, query: str, store, state: dict | None = None) -> dict:
    project_id, _ = collect(root)
    selected = {doc["doc_id"]: doc for doc in store.search(project_id, query)}
    seen = set(selected)
    while True:
        links = sorted({link for doc in selected.values() for link in doc["links"]} - seen)
        if not links:
            break
        seen.update(links)
        selected.update((doc["doc_id"], doc) for doc in store.by_ids(project_id, links))
    sections = {"specs": [], "code": [], "tests": []}
    for doc in sorted(selected.values(), key=lambda item: item["doc_id"]):
        path = inside(root, doc["source_path"])
        if digest(path.read_bytes()) != doc["source_sha256"]:
            raise ValueError(f"Indexed source changed; re-import before building context: {doc['source_path']}")
        item = {key: doc[key] for key in ("doc_id", "revision", "source_path", "symbol", "start_line", "end_line", "content", "sha256", "source_sha256")}
        item["selection_reason"] = "task keyword or explicit source relationship"
        sections[{"spec": "specs", "code": "code", "test": "tests"}[doc["kind"]]].append(item)
    current = fingerprint(root)
    return {"schema": "sdd.context.v1", "project_id": project_id, "task": query,
            "fingerprint": current, **sections, "progress": assess_state(state, current)}
