import json

import pytest

from sdd_context.agent import generate_edit, parse_edit
from sdd_context.common import digest, inside, read_json, write_json
from sdd_context.context import assess_state
from sdd_context.ingest import collect, fingerprint
from sdd_context.store import EngineeringStore


def test_ingest_real_sources_and_symbols(project):
    project_id, docs = collect(project)
    assert project_id == "taskboard"
    code = next(doc for doc in docs if doc["kind"] == "code")
    assert "list_tasks" in code["symbol"] and code["end_line"] > 1
    assert code["source_sha256"] == digest(inside(project, code["source_path"]).read_bytes())
    assert not next(doc for doc in docs if doc["doc_id"] == "spec:ADR-LEGACY")["active"]


def test_idempotent_collection(project):
    assert collect(project) == collect(project)


@pytest.mark.parametrize("path", ["../escape.py", "missing.py"])
def test_source_boundaries(project, path):
    with pytest.raises(ValueError):
        inside(project, path)


def test_reject_duplicate_requirements(project):
    path = project / "specs" / "requirements.json"
    specs = read_json(path)
    specs["requirements"].append(specs["requirements"][0])
    write_json(path, specs)
    with pytest.raises(ValueError, match="Duplicate"):
        collect(project)


def test_reject_missing_links(project):
    path = project / "specs" / "requirements.json"
    specs = read_json(path)
    specs["requirements"][0]["links"].append("code:missing.py")
    write_json(path, specs)
    with pytest.raises(ValueError, match="Unresolved"):
        collect(project)


def test_fingerprint_changes_with_spec_code_and_tests(project):
    for relative in ("taskboard.py", "tests/test_target.py", "specs/requirements.json"):
        before = fingerprint(project)
        path = project / relative
        if relative.endswith(".py"):
            path.write_text(path.read_text(encoding="utf-8") + "\n# changed\n", encoding="utf-8")
        else:
            specs = read_json(path)
            specs["requirements"][0]["content"] += " updated"
            write_json(path, specs)
        assert fingerprint(project) != before


def test_empty_state_requires_work():
    assert assess_state(None, "new")["next_action"] == "implement"


def test_current_state_controls_next_step():
    state = {"fingerprint": "a", "checks_passed": True, "pending": ["review-result"]}
    result = assess_state(state, "a")
    assert result["validation"] == "current" and result["next_action"] == "review-result"


def test_stale_state_requires_revalidation():
    state = {"fingerprint": "old", "checks_passed": True, "pending": []}
    result = assess_state(state, "new")
    assert result["validation"] == "stale" and result["next_action"] == "revalidate"
    assert state["pending"] == []


def test_failed_checks_are_not_current_validation():
    assert assess_state({"fingerprint": "a", "checks_passed": False}, "a")["validation"] == "not_passed"


@pytest.mark.parametrize("prefix,suffix", [("", ""), ("```json\n", "\n```"), ("<think>private reasoning</think>", "")])
def test_parse_model_edit(prefix, suffix):
    text = prefix + json.dumps({"path": "taskboard.py", "content": "answer = 42\n"}) + suffix
    assert parse_edit(text, {"taskboard.py"})["content"] == "answer = 42\n"


@pytest.mark.parametrize("path", ["tests/test_target.py", "../escape.py", "/etc/passwd"])
def test_model_cannot_edit_outside_allowed_implementation(path):
    with pytest.raises(ValueError):
        parse_edit(json.dumps({"path": path, "content": "x=1"}), {"taskboard.py"})


def test_invalid_model_python_rejected():
    with pytest.raises(SyntaxError):
        parse_edit(json.dumps({"path": "taskboard.py", "content": "def !!!"}), {"taskboard.py"})


def test_missing_credentials_never_fall_back_to_reference(monkeypatch, project, tmp_path):
    monkeypatch.delenv("MINIMAX_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="reference run"):
        generate_edit(project, {}, tmp_path)
    assert not (tmp_path / "response.json").exists()


def test_database_name_is_not_interpolated_unchecked(monkeypatch):
    monkeypatch.setenv("SDD_DB_NAME", "sdd`; DROP DATABASE test")
    with pytest.raises(ValueError):
        EngineeringStore()
