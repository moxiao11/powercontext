"""Record negative submission gates and installed dependency versions."""
import argparse
import importlib.metadata
import os
import platform
import subprocess
import sys
import uuid
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))
from sdd_context.common import now, write_json


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    directory = BASE / "runtime" / ("missing-key-" + uuid.uuid4().hex[:8])
    cases = [
        ("missing_minimax_key", [sys.executable, "-m", "sdd_context", "demo", "--mode", "live", "--output", str(directory)], 2),
        ("reference_cannot_pass_submission", [sys.executable, "scripts/verify_submission.py", "evidence/reference-final"], 1),
    ]
    records = []
    for name, command, expected in cases:
        result = subprocess.run(command, cwd=BASE, capture_output=True, text=True, encoding="utf-8", errors="replace",
                                timeout=60, env={**os.environ, "MINIMAX_API_KEY": "", "PYTHONUTF8": "1"})
        records.append({"name": name, "command": command, "expected_exit_code": expected,
                        "actual_exit_code": result.returncode, "passed": result.returncode == expected,
                        "stdout": result.stdout, "stderr": result.stderr})
    report = {"timestamp": now(), "platform": platform.platform(), "python": platform.python_version(),
              "checks": records, "all_passed": all(record["passed"] for record in records),
              "dependencies": {dist.metadata["Name"]: dist.version for dist in importlib.metadata.distributions()}}
    write_json(args.output, report)
    print("Negative gates:", "passed" if report["all_passed"] else "failed")
    return 0 if report["all_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
