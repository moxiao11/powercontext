#!/usr/bin/env python3
"""Check competition deliverables and build a source-only, credential-free archive.

Use --strict before submitting; without it, pending account-dependent requirements
are reported honestly while a review package can still be assembled.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
BASELINE = "d647275c308e09b7b623f322a26f5c4e85734fb0"
DOCS = [
    "README.md",
    ".env.example",
    "docker-compose.yml",
    "db/schema.sql",
    "docs/ARCHITECTURE.md",
    "docs/SETUP.md",
    "docs/VERIFICATION.md",
    "docs/QODER_DEVELOPMENT_LOG.md",
    "docs/TECH_INTEGRATION.md",
    "docs/DEPLOYMENT.md",
    "docs/USER_TESTING.md",
    "docs/SUBMISSION.md",
    "frontend/package-lock.json",
    "backend/requirements.lock",
    "sample-data/papers/sample-pdf-eqa.pdf",
]
EXCLUDED_DIRS = {
    ".git",
    "node_modules",
    "dist",
    ".venv",
    "venv",
    "__pycache__",
    "data",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
    ".vite",
    ".idea",
    ".vscode",
}


def git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(ROOT), *args],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def source_files():
    """Use a directory whitelist and reject local configuration at every depth."""
    allowed = {
        "backend",
        "frontend",
        "db",
        "docker",
        "scripts",
        "sample-data",
        "docs",
        "site",
    }
    root_files = {
        "README.md",
        ".env.example",
        ".gitignore",
        ".dockerignore",
        ".gitattributes",
        "docker-compose.yml",
        "submission.example.json",
    }
    for directory, dirs, files in os.walk(ROOT):
        parent = Path(directory)
        dirs[:] = sorted(
            name
            for name in dirs
            if name not in EXCLUDED_DIRS
            and not (parent / name).is_symlink()
            and (parent != ROOT or name in allowed)
        )
        for filename in sorted(files):
            path = parent / filename
            relative = path.relative_to(ROOT)
            if path.is_symlink() or (parent == ROOT and filename not in root_files):
                continue
            name = filename.lower()
            if name.endswith((".pyc", ".log", ".pid", ".tsbuildinfo")):
                continue
            if (".env" in name and not name.endswith(".example")) or name.endswith(
                (".pem", ".key", ".p12")
            ):
                continue
            yield path, relative


def inspect(config: dict) -> dict:
    checks = []

    def add(name, status, detail):
        checks.append({"name": name, "status": status, "detail": detail})

    head = git("rev-parse", "HEAD")
    branch = git("branch", "--show-current")
    ancestry = git("merge-base", "--is-ancestor", BASELINE, "HEAD")
    add(
        "competition_ancestry", "pass" if ancestry.returncode == 0 else "fail", BASELINE
    )
    add(
        "competition_branch",
        "pass" if branch.stdout.strip() == "2026-competition-ecosystem" else "fail",
        branch.stdout.strip(),
    )
    changes = git("status", "--porcelain", "--", ".")
    add(
        "committed_source",
        "pending" if changes.stdout.strip() else "pass",
        "Commit qoder changes before recording the final competition hash."
        if changes.stdout.strip()
        else head.stdout.strip(),
    )
    for relative in DOCS:
        path = ROOT / relative
        add(
            relative,
            "pass" if path.is_file() and path.stat().st_size else "fail",
            relative,
        )
    for field in ("site_url", "repository_url"):
        value = config.get(field, "")
        parsed = urlparse(value)
        valid = (
            parsed.scheme == "https"
            and bool(parsed.hostname)
            and not parsed.username
            and not parsed.password
        )
        if (
            field == "repository_url"
            and parsed.path.rstrip("/").lower() == "/oceanbase/powercontext"
        ):
            valid = False
        add(
            field,
            "pass" if valid else "pending",
            value
            if valid
            else "Provide the actual project URL in submission.local.json",
        )
    add(
        "qoder_uid",
        "pass" if str(config.get("qoder_uid", "")).strip() else "pending",
        "Real Qoder account UID required",
    )
    evidence = config.get("qoder_evidence", [])
    valid_evidence = isinstance(evidence, list) and bool(evidence)
    for value in evidence if isinstance(evidence, list) else []:
        path = (ROOT / value).resolve()
        if (
            not path.is_relative_to(ROOT)
            or not path.is_file()
            or not path.stat().st_size
        ) or path.suffix.lower() not in {
            ".png",
            ".jpg",
            ".jpeg",
            ".webp",
            ".mp4",
            ".webm",
        }:
            valid_evidence = False
    add(
        "qoder_development_evidence",
        "pass" if valid_evidence else "pending",
        "Attach original Qoder screenshots or video and UID; an archived text transcript is supporting material.",
    )
    add(
        "anonymous_site_access",
        "pass" if config.get("anonymous_access_verified") is True else "pending",
        "Open the published Qoder Sites URL in a signed-out browser before marking verified.",
    )
    transcript = ROOT / "docs/evidence/qoder-development-transcript.txt"
    return {
        "project": "LabTrace",
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "branch": branch.stdout.strip(),
        "commit": head.stdout.strip(),
        "baseline": BASELINE,
        "qoder_transcript": {
            "path": transcript.relative_to(ROOT).as_posix(),
            "sha256": hashlib.sha256(transcript.read_bytes()).hexdigest(),
            "source": "user-provided Qoder conversation text",
        }
        if transcript.is_file()
        else None,
        "ready_for_submission": all(item["status"] == "pass" for item in checks),
        "checks": checks,
        "validation_note": "This is a local completeness check. It does not establish site ownership, public access, or Qoder provenance.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["check", "pack"])
    parser.add_argument("--config", type=Path, default=ROOT / "submission.local.json")
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()
    config = (
        json.loads(args.config.read_text(encoding="utf-8-sig"))
        if args.config.exists()
        else {}
    )
    report = inspect(config)
    for check in report["checks"]:
        print(f"[{check['status'].upper()}] {check['name']}: {check['detail']}")
    out = ROOT / "dist/submission"
    out.mkdir(parents=True, exist_ok=True)
    (out / "preflight.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    if any(item["status"] == "fail" for item in report["checks"]):
        return 1
    if args.strict and not report["ready_for_submission"]:
        print("Submission is incomplete; pending requirements are listed above.")
        return 1
    if args.command == "pack":
        archive_path = out / "labtrace-submission.zip"
        manifest = []
        with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as archive:
            for path, relative in source_files():
                content = path.read_bytes()
                name = "qoder/" + relative.as_posix()
                archive.writestr(name, content)
                manifest.append(
                    {
                        "path": name,
                        "sha256": hashlib.sha256(content).hexdigest(),
                        "bytes": len(content),
                    }
                )
            archive.writestr(
                "preflight.json", json.dumps(report, ensure_ascii=False, indent=2)
            )
            archive.writestr(
                "manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2)
            )
        print(f"Package: {archive_path} ({len(manifest)} source files)")
        print(
            "This qoder-only archive supplements the full competition repository; it cannot replace its Git history."
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
