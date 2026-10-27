"""Verify a packaged source snapshot can run without checkout-local assets."""
import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))
from sdd_context.common import load_env, now, write_json


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("archive", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    load_env(BASE / ".env")
    runtime = (BASE / "runtime").resolve()
    runtime.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="source-check-", dir=runtime) as directory:
        root = Path(directory).resolve()
        if not root.is_relative_to(runtime):
            raise ValueError("Unexpected temporary directory outside runtime")
        with zipfile.ZipFile(args.archive) as archive:
            for name in archive.namelist():
                if not (root / name).resolve().is_relative_to(root):
                    raise ValueError("Archive path escaped the test directory")
            archive.extractall(root)
        manifest = json.loads((root / "build-manifest.json").read_text(encoding="utf-8"))
        for name, expected in manifest["files"].items():
            actual = hashlib.sha256((root / name).read_bytes()).hexdigest()
            if actual != expected:
                raise ValueError("Packaged file hash mismatch: " + name)
        command = [sys.executable, "-m", "sdd_context", "demo", "--mode", "reference", "--output", str(root / "run")]
        result = subprocess.run(command, cwd=root / "minimax", capture_output=True, text=True, encoding="utf-8",
                                errors="replace", timeout=180,
                                env={**os.environ, "PYTHONPATH": "", "PYTHONNOUSERSITE": "1", "PYTHONUTF8": "1"})
        report = {"timestamp": now(), "archive_sha256": hashlib.sha256(args.archive.read_bytes()).hexdigest(),
                  "manifest_commit": manifest["commit"], "files_verified": len(manifest["files"]),
                  "command": command, "exit_code": result.returncode,
                  "isolated_source_directory": str(root / "minimax"),
                  "stdout": result.stdout, "stderr": result.stderr,
                  "note": "Sources extracted from archive; installed pinned dependencies and real services are reused. This is not a fresh OS/dependency installation test."}
        write_json(args.output, report)
        print(json.dumps({"exit_code": result.returncode, "files_verified": len(manifest["files"]), "output": str(args.output)}, indent=2))
        return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
