"""Package Git-visible sources and evidence; never package runtime or credentials."""
import argparse
import hashlib
import json
import subprocess
import zipfile
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    files = subprocess.check_output(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "--", "minimax"],
        cwd=REPO, text=True, encoding="utf-8").splitlines()
    if not files:
        raise ValueError("No source files found")
    metadata = {"created_utc": datetime.now(timezone.utc).isoformat(),
                "commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO, text=True).strip(),
                "dirty": bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=REPO, text=True).strip()),
                "files": {}}
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for relative in sorted(set(files)):
            path = REPO / relative
            if not path.is_file() or path.is_symlink():
                raise ValueError("Invalid source entry: " + relative)
            if ".env" == path.name or any(part in {".venv", "runtime", "__pycache__", ".git"} for part in path.relative_to(REPO).parts):
                raise ValueError("Refusing to package private/runtime entry: " + relative)
            metadata["files"][relative] = hashlib.sha256(path.read_bytes()).hexdigest()
            archive.write(path, relative)
        archive.writestr("build-manifest.json", json.dumps(metadata, indent=2) + "\n")
    print(json.dumps({"archive": str(output), "file_count": len(metadata["files"]),
                      "sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
                      "commit": metadata["commit"], "dirty": metadata["dirty"]}, indent=2))


if __name__ == "__main__":
    main()
