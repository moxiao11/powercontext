from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .common import load_env, read_json, write_json
from .context import build_context
from .ingest import collect, fingerprint
from .state import TaskState
from .store import EngineeringStore


def main():
    load_env()
    parser = argparse.ArgumentParser(description="SDD engineering context backed by seekdb and PowerContext")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init", help="Create only SDD's own database and tables")
    ingest = sub.add_parser("import", help="Atomically replace one project's current indexed snapshot")
    ingest.add_argument("--project", type=Path, required=True)
    ingest.add_argument("--spec-file")
    for command in ("context", "resume"):
        context = sub.add_parser(command)
        context.add_argument("--project", type=Path, required=True)
        context.add_argument("--task", required=True)
        context.add_argument("--pointer", type=Path)
        context.add_argument("--output", type=Path)
        context.add_argument("--audit-dir", type=Path)
    save = sub.add_parser("save-state")
    save.add_argument("--project", type=Path, required=True)
    save.add_argument("--task-id", required=True)
    save.add_argument("--pointer", type=Path, required=True)
    save.add_argument("--state", type=Path, required=True)
    demo = sub.add_parser("demo")
    demo.add_argument("--mode", choices=("reference", "live"), required=True)
    demo.add_argument("--output", type=Path)
    demo.add_argument("--attempts", type=int, default=3)
    args = parser.parse_args()
    audit = getattr(args, "audit_dir", None) or Path("runtime/audit")
    store = EngineeringStore(audit / "database.jsonl")
    if args.command == "init":
        store.initialize()
        result = {"status": "initialized", "database": store.database}
    elif args.command == "import":
        project_id, documents = collect(args.project, args.spec_file)
        result = store.import_documents(project_id, documents)
    elif args.command in {"context", "resume"}:
        state = TaskState(args.pointer, audit / "powercontext.jsonl").load() if args.pointer else None
        if args.command == "resume" and state is None:
            raise ValueError("No durable task state is available to resume")
        result = build_context(args.project, args.task, store, state)
        if args.output:
            write_json(args.output, result)
    elif args.command == "save-state":
        state = read_json(args.state)
        state["fingerprint"] = fingerprint(args.project)
        result = TaskState(args.pointer, audit / "powercontext.jsonl").save(args.task_id, state)
    else:
        from .demo import run_demo
        result = run_demo(args.mode, args.output, args.attempts)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if args.command == "demo" and not result["implementation_checks_passed"]:
        return 1
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, RuntimeError, OSError) as error:
        print(f"SDD error: {error}", file=sys.stderr)
        raise SystemExit(2)
