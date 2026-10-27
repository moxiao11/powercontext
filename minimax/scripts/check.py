"""Record real unit/integration commands, exit codes and JUnit output."""
import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))
from sdd_context.common import digest, load_env, write_json


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--integration", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    load_env(BASE / ".env")
    output = args.output.resolve()
    if output.exists():
        raise ValueError("Choose a new output directory")
    output.mkdir(parents=True)
    command = [sys.executable, "-m", "pytest", "-q", "tests/test_unit.py"]
    if args.integration:
        command.append("tests/test_integration.py")
    command.extend(["--tb=short", "--basetemp=" + str(BASE / "runtime" / ("test-" + output.name)),
                    "--junitxml=" + str(output / "results.xml")])
    result = subprocess.run(command, cwd=BASE, capture_output=True, text=True, encoding="utf-8", errors="replace",
                            timeout=180, env={**os.environ, "PYTHONUTF8": "1"})
    (output / "results.log").write_text(result.stdout + result.stderr, encoding="utf-8")
    summary = {"timestamp": datetime.now(timezone.utc).isoformat(), "command": command,
               "exit_code": result.returncode, "real_services": args.integration,
               "source_hashes": {str(p.relative_to(BASE)): digest(p.read_bytes()) for p in sorted((BASE / "sdd_context").glob("*.py"))}}
    write_json(output / "summary.json", summary)
    print(result.stdout + result.stderr)
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
