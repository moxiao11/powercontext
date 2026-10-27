from __future__ import annotations

import ast
from pathlib import Path

from .common import digest, inside, read_json


def collect(root: Path, spec_path: str | None = None) -> tuple[str, list[dict]]:
    """Validate the complete snapshot before changing any database rows."""
    manifest = read_json(inside(root, "project.json"))
    project_id = manifest["project_id"]
    documents = []
    specs = read_json(inside(root, spec_path or manifest["spec_file"]))
    for entry in specs["requirements"]:
        if entry["status"] not in {"active", "superseded", "retired"}:
            raise ValueError("Unknown specification lifecycle state")
        documents.append({
            "doc_id": "spec:" + entry["id"], "kind": "spec",
            "source_path": spec_path or manifest["spec_file"],
            "symbol": entry["id"], "start_line": 1,
            "end_line": len(inside(root, spec_path or manifest["spec_file"]).read_text(encoding="utf-8").splitlines()),
            "content": entry["content"], "tags": entry["tags"],
            "links": entry.get("links", []), "declared_version": specs["version"],
            "active": entry["status"] == "active",
            "source_sha256": digest(inside(root, spec_path or manifest["spec_file"]).read_bytes()),
        })
    for entry in manifest["sources"]:
        if entry["kind"] not in {"code", "test"}:
            raise ValueError("Source kind must be code or test")
        path = inside(root, entry["path"])
        text = path.read_text(encoding="utf-8")
        tree = ast.parse(text, filename=entry["path"])
        names = [node.name for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))]
        documents.append({
            "doc_id": entry["kind"] + ":" + entry["path"], "kind": entry["kind"],
            "source_path": entry["path"], "symbol": ", ".join(names),
            "start_line": 1, "end_line": len(text.splitlines()), "content": text,
            "tags": entry["tags"], "links": entry.get("links", []),
            "declared_version": None, "active": True,
            "source_sha256": digest(path.read_bytes()),
        })
    ids = [entry["doc_id"] for entry in documents]
    if len(set(ids)) != len(ids):
        raise ValueError("Duplicate document IDs in project snapshot")
    for entry in documents:
        missing = set(entry["links"]) - set(ids)
        if missing:
            raise ValueError(f"Unresolved source links: {sorted(missing)}")
        entry["sha256"] = digest(entry)
    return project_id, documents


def fingerprint(root: Path) -> str:
    project_id, documents = collect(root)
    return digest({"project_id": project_id, "documents": documents})
