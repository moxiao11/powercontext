from __future__ import annotations

import difflib
import importlib.metadata
import os
import shutil
import subprocess
import sys
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path

from .agent import generate_edit
from .common import digest, now, read_json, write_json
from .context import build_context
from .ingest import collect, fingerprint
from .state import TaskState
from .store import EngineeringStore

TASK = "taskboard 任务列表增加 status filter，保持 pagination compatibility"
BASE = Path(__file__).resolve().parents[1]


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def run_tests(root: Path, output: Path, label: str, suite: str) -> dict:
    xml = output / (label + ".xml")
    command = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
               "tests/" + suite, "--junitxml=" + str(xml)]
    result = subprocess.run(command, cwd=root, capture_output=True, text=True, encoding="utf-8",
                            errors="replace", timeout=120, env={**os.environ, "PYTHONUTF8": "1"})
    (output / (label + ".log")).write_text(result.stdout + result.stderr, encoding="utf-8")
    counts = dict(tests=0, failures=0, errors=0, skipped=0)
    if xml.is_file():
        for suite_element in ET.parse(xml).getroot().iter("testsuite"):
            for key in counts:
                counts[key] += int(suite_element.attrib.get(key, 0))
    record = {"command": command, "cwd": str(root), "timestamp": now(), "exit_code": result.returncode,
              "code_sha256": digest((root / "taskboard.py").read_bytes()),
              "test_sha256": digest((root / "tests" / suite).read_bytes()),
              "test_tree_sha256": digest({str(path.relative_to(root)): digest(path.read_bytes())
                                          for path in sorted((root / "tests").glob("*.py"))}),
              "project_fingerprint": fingerprint(root), **counts}
    write_json(output / (label + ".json"), record)
    return record


def child_resume(root: Path, output: Path, label: str, pointer: Path) -> dict:
    path = output / (label + ".json")
    command = [sys.executable, "-m", "sdd_context", "resume", "--project", str(root),
               "--task", TASK, "--pointer", str(pointer), "--output", str(path), "--audit-dir", str(output)]
    result = subprocess.run(command, cwd=BASE, capture_output=True, text=True, encoding="utf-8",
                            errors="replace", timeout=90, env={**os.environ, "PYTHONUTF8": "1"})
    write_json(output / (label + "-process.json"), {"command": command, "exit_code": result.returncode,
                                                    "stdout": result.stdout, "stderr": result.stderr})
    if result.returncode:
        raise RuntimeError(f"Fresh-process state restore failed; see {label}-process.json")
    return read_json(path)


def run_demo(mode: str, output: Path | None = None, attempts: int = 3) -> dict:
    if not 1 <= attempts <= 3:
        raise ValueError("Generation attempts must be between 1 and 3")
    run_id = "taskboard-" + mode + "-" + uuid.uuid4().hex[:12]
    output = (output or BASE / "runtime" / "runs" / run_id).resolve()
    if output.exists():
        raise ValueError("Use a new output directory; existing evidence is never overwritten")
    output.mkdir(parents=True)
    if mode == "live" and not os.getenv("MINIMAX_API_KEY"):
        write_json(output / "blocked.json", {"status": "blocked", "reason": "MINIMAX_API_KEY not configured",
                                               "minimax_participation": False, "submission_ready": False})
        raise RuntimeError(f"MiniMax credentials are required for --mode live. Details: {output}")
    root = output / "project"
    shutil.copytree(BASE / "examples" / "taskboard" / "project", root,
                    ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache", "*.pyc"))
    manifest = read_json(root / "project.json")
    manifest["project_id"] = run_id
    write_json(root / "project.json", manifest)
    store = EngineeringStore(output / "database.jsonl")
    store.initialize()
    with store.connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT VERSION() AS version")
            database_version = cursor.fetchone()["version"]
    pointer = output / "state-pointer.json"
    state = TaskState(pointer, output / "powercontext.jsonl")
    require(state.load() is None, "The demonstration must start from empty task state")

    current_specs = read_json(root / "specs" / "requirements.json")
    write_json(root / "specs" / "requirements.json", read_json(root / "specs" / "history-v1.json"))
    project_id, docs = collect(root)
    write_json(output / "import-v1.json", store.import_documents(project_id, docs))
    old_context = build_context(root, TASK, store)
    write_json(output / "context-v1.json", old_context)
    require(any(doc["doc_id"] == "spec:ADR-LEGACY" for doc in old_context["specs"]), "Old specification import did not take effect")
    write_json(root / "specs" / "requirements.json", current_specs)
    project_id, docs = collect(root)
    write_json(output / "import-v2.json", store.import_documents(project_id, docs))
    context = build_context(root, TASK, store)
    write_json(output / "context-v2.json", context)
    ids = {item["doc_id"] for section in ("specs", "code", "tests") for item in context[section]}
    required = {"spec:REQ-STATUS", "spec:REQ-COMPAT", "code:taskboard.py",
                "test:tests/test_target.py", "test:tests/test_regression.py", "test:tests/conftest.py"}
    require(required <= ids, "Context is missing required specification, implementation or test sources")
    require(not {"spec:ADR-LEGACY", "spec:REQ-BILLING"} & ids, "Retired or unrelated sources entered the task context")
    require("doing" in next(doc["content"] for doc in context["specs"] if doc["doc_id"] == "spec:REQ-STATUS"), "Updated contract was not retrieved")
    write_json(output / "source-expectations.json", {"required": sorted(required), "actual": sorted(ids)})

    target_before = run_tests(root, output, "target-before", "test_target.py")
    regression_before = run_tests(root, output, "regression-before", "test_regression.py")
    require(target_before["exit_code"] == 1 and target_before["failures"] > 0, "Baseline did not demonstrate a target behavior failure")
    require(target_before["errors"] == target_before["skipped"] == 0, "Environment errors or skipped tests cannot stand in for functional failures")
    require(regression_before["exit_code"] == regression_before["failures"] == regression_before["errors"] == 0, "Baseline regression tests did not pass")
    before = (root / "taskboard.py").read_text(encoding="utf-8")
    shutil.copyfile(root / "taskboard.py", output / "before.py")
    require(digest((output / "before.py").read_bytes()) == target_before["code_sha256"], "Before snapshot does not match tested source bytes")
    state.save(run_id, {"completed": ["import", "select-context", "baseline-tests"],
                        "pending": ["implement", "verify"], "checks_passed": False,
                        "fingerprint": fingerprint(root), "baseline_failures": target_before["failures"]})
    resumed_before = child_resume(root, output, "resume-before", pointer)
    require(resumed_before["progress"]["next_action"] == "implement", "Saved pending work did not control the fresh process")

    minimax_live = False
    feedback = ""
    for attempt in range(1, (attempts if mode == "live" else 1) + 1):
        if mode == "reference":
            shutil.copyfile(BASE / "examples" / "taskboard" / "reference" / "taskboard.py", root / "taskboard.py")
            write_json(output / "generation-status.json", {
                "provider": "local-reference", "live": False, "minimax_participation": False,
                "reason": "No MiniMax credentials. This run verifies implementation, not model participation."})
        else:
            _, docs = collect(root)
            store.import_documents(project_id, docs)
            context = build_context(root, TASK, store, state.load())
            generate_edit(root, context, output / f"minimax-attempt-{attempt}", feedback)
            minimax_live = True
        target_after = run_tests(root, output, f"target-after-{attempt}", "test_target.py")
        regression_after = run_tests(root, output, f"regression-after-{attempt}", "test_regression.py")
        # The target and regression test files must be byte-identical on both sides.
        require(target_before["test_sha256"] == target_after["test_sha256"], "Target tests changed between before and after")
        require(regression_before["test_sha256"] == regression_after["test_sha256"], "Regression tests changed between before and after")
        require(target_before["test_tree_sha256"] == target_after["test_tree_sha256"] == regression_after["test_tree_sha256"], "Test files or fixtures changed during implementation")
        valid_change = all(after_check["exit_code"] == 0 and after_check["tests"] == before_check["tests"]
                           and after_check["failures"] == after_check["errors"] == after_check["skipped"] == 0
                           for before_check, after_check in ((target_before, target_after), (regression_before, regression_after)))
        if valid_change:
            break
        feedback = (output / f"target-after-{attempt}.log").read_text(encoding="utf-8") + (output / f"regression-after-{attempt}.log").read_text(encoding="utf-8")
    after = (root / "taskboard.py").read_text(encoding="utf-8")
    shutil.copyfile(root / "taskboard.py", output / "after.py")
    require(digest((output / "after.py").read_bytes()) == target_after["code_sha256"] == regression_after["code_sha256"], "After snapshot does not match tested source bytes")
    (output / "change.diff").write_text("".join(difflib.unified_diff(before.splitlines(True), after.splitlines(True),
                                                                                fromfile="before/taskboard.py", tofile="after/taskboard.py")), encoding="utf-8")
    if not valid_change:
        raise RuntimeError("Generated change failed tests; logs and model records were preserved")
    _, docs = collect(root)
    store.import_documents(project_id, docs)
    state.save(run_id, {"completed": ["implement", "target-tests", "regression-tests"],
                        "pending": ["review-result"], "checks_passed": True,
                        "fingerprint": fingerprint(root), "code_sha256": target_after["code_sha256"],
                        "target_tests": target_after["tests"], "regression_tests": regression_after["tests"],
                        "minimax_participation": minimax_live})
    resumed = child_resume(root, output, "resume-after", pointer)
    require(resumed["progress"]["next_action"] == "review-result" and resumed["progress"]["validation"] == "current", "Fresh-process state did not preserve next action and current validation")

    current_specs["version"] = 3
    current_specs["requirements"][0]["content"] += " 规格更新标记：revision-3。"
    write_json(root / "specs" / "requirements.json", current_specs)
    _, docs = collect(root)
    write_json(output / "import-v3.json", store.import_documents(project_id, docs))
    updated = child_resume(root, output, "resume-spec-updated", pointer)
    require("revision-3" in next(doc["content"] for doc in updated["specs"] if doc["doc_id"] == "spec:REQ-STATUS"), "Re-imported specification update is absent")
    require(updated["progress"]["validation"] == "stale" and updated["progress"]["next_action"] == "revalidate", "Updated sources did not invalidate previous test evidence")
    target_revalidated = run_tests(root, output, "target-revalidated", "test_target.py")
    regression_revalidated = run_tests(root, output, "regression-revalidated", "test_regression.py")
    require(target_revalidated["exit_code"] == regression_revalidated["exit_code"] == 0, "Revalidation failed")
    state.save(run_id, {"completed": ["implement", "target-tests", "regression-tests", "spec-revalidation"],
                        "pending": [], "checks_passed": True, "fingerprint": fingerprint(root),
                        "minimax_participation": minimax_live,
                        "code_sha256": target_revalidated["code_sha256"],
                        "target_exit_code": 0, "regression_exit_code": 0})
    final = child_resume(root, output, "resume-final", pointer)
    require(final["progress"]["next_action"] == "complete", "Final durable state was not reused")
    write_json(output / "database-history.json", store.history(project_id))
    report = {
        "schema": "sdd.acceptance.v1", "run_id": run_id, "timestamp": now(), "mode": mode,
        "output": str(output), "project_id": project_id,
        "versions": {package: importlib.metadata.version(package) for package in ("powercontext", "PyMySQL", "pytest", "httpx")},
        "database_version": database_version,
        "acceptance": {"runnable": "passed", "minimax_actual_participation": "passed" if minimax_live else "blocked_no_credentials",
                       "context_correct_and_updates": "passed", "database_actual_participation": "passed",
                       "powercontext_state_reused": "passed", "code_change_valid": "passed"},
        "implementation_checks_passed": True, "all_six_passed": minimax_live,
        "submission_ready": minimax_live, "target_before": target_before, "target_after": target_after,
        "regression_after": regression_after, "state_update_invalidates_validation": True,
        "source_expectations": sorted(required),
        "limitations": [] if minimax_live else ["Local reference code is NOT evidence of MiniMax involvement. Configure a real key and run --mode live before submission."],
    }
    write_json(output / "acceptance.json", report)
    return report
