"""Requires real seekdb/OceanBase and a real PowerContext service. No mocks."""
import uuid

import pytest

from sdd_context.common import read_json, write_json
from sdd_context.context import build_context
from sdd_context.ingest import collect, fingerprint
from sdd_context.state import TaskState
from sdd_context.store import EngineeringStore


@pytest.fixture
def indexed(project, tmp_path):
    manifest = read_json(project / "project.json")
    manifest["project_id"] = "integration-" + uuid.uuid4().hex[:12]
    write_json(project / "project.json", manifest)
    store = EngineeringStore(tmp_path / "database.jsonl")
    store.initialize()
    project_id, docs = collect(project)
    store.import_documents(project_id, docs)
    yield store, project_id, project
    # Delete only the randomly named project created by this test, never any database.
    with store.connect() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM sdd_documents WHERE project_id=%s", (project_id,))
            cur.execute("DELETE FROM sdd_projects WHERE project_id=%s", (project_id,))
        conn.commit()


def test_current_context_and_project_isolation(indexed):
    store, project_id, root = indexed
    context = build_context(root, "taskboard status", store)
    ids = {d["doc_id"] for d in context["specs"]}
    assert ids == {"spec:REQ-STATUS", "spec:REQ-COMPAT"}
    assert store.search("nonexistent-project", "status") == []
    assert context["code"] and context["tests"]


def test_idempotent_import_and_revision_update(indexed):
    store, project_id, root = indexed
    _, docs = collect(root)
    again = store.import_documents(project_id, docs)
    assert again["unchanged"] and again["changed"] == []
    path = root / "specs" / "requirements.json"
    specs = read_json(path)
    specs["requirements"][0]["content"] += " Updated contract."
    write_json(path, specs)
    _, docs = collect(root)
    store.import_documents(project_id, docs)
    context = build_context(root, "status", store)
    status = next(d for d in context["specs"] if d["doc_id"] == "spec:REQ-STATUS")
    assert status["revision"] == 2 and "Updated contract" in status["content"]


def test_deleted_specs_are_deactivated(indexed):
    store, project_id, root = indexed
    path = root / "specs" / "requirements.json"
    specs = read_json(path)
    specs["requirements"] = [r for r in specs["requirements"] if r["id"] != "REQ-BILLING"]
    write_json(path, specs)
    _, docs = collect(root)
    store.import_documents(project_id, docs)
    assert store.search(project_id, "invoice") == []
    assert any(d["doc_id"] == "spec:REQ-BILLING" for d in store.history(project_id))


def test_changed_source_requires_reimport(indexed):
    store, project_id, root = indexed
    path = root / "taskboard.py"
    path.write_text(path.read_text(encoding="utf-8") + "\n# changed\n", encoding="utf-8")
    with pytest.raises(ValueError, match="re-import"):
        build_context(root, "status", store)


def test_powercontext_roundtrip_and_no_local_state_copy(indexed, tmp_path):
    _, project_id, root = indexed
    pointer = tmp_path / "pointer.json"
    state = TaskState(pointer)
    assert state.load() is None
    expected = {"completed": ["baseline"], "pending": ["implement"], "checks_passed": False,
                "fingerprint": fingerprint(root)}
    state.save(project_id, expected)
    assert set(read_json(pointer)) == {"task_id", "scope_id", "artifact"}
    restored = TaskState(pointer).load()
    assert all(restored[k] == v for k, v in expected.items())
    with pytest.raises(ValueError, match="different task"):
        state.save("unrelated-task", expected)
