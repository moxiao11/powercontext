"""Audit credentials, model/code correspondence, and unchanged test evidence."""
import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
REPO = BASE.parent
sys.path.insert(0, str(BASE))
from sdd_context.common import digest, load_env, now, read_json, write_json


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence", type=Path, default=BASE / "evidence" / "live-final")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    load_env(BASE / ".env")
    # Empty strings match every file, so an absent key must never be a scan pattern.
    key = os.getenv("MINIMAX_API_KEY", "").encode()
    files = subprocess.check_output(["git", "ls-files", "--cached", "--others", "--exclude-standard", "--", "minimax"],
                                    cwd=REPO, text=True, encoding="utf-8").splitlines()
    pattern = re.compile(rb"sk-(?:cp-)?[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}")
    findings = []
    protected = []
    for name in sorted(set(files)):
        path = REPO / name
        if not path.is_file():
            continue
        if path.name == ".env" or any(part in {".venv", "runtime", "__pycache__"} for part in path.relative_to(REPO).parts):
            protected.append(name)
        content = path.read_bytes()
        if pattern.search(content) or (key and key in content):
            findings.append(name)
    evidence = args.evidence.resolve()
    response = read_json(evidence / "minimax-attempt-1" / "response.json")
    acceptance = read_json(evidence / "acceptance.json")
    before = digest((evidence / "before.py").read_bytes())
    after = digest((evidence / "after.py").read_bytes())
    test_files = {path.relative_to(evidence / "project").as_posix(): digest(path.read_bytes())
                  for path in sorted((evidence / "project" / "tests").glob("*.py"))}
    # Earlier run records use the host's path separator; validate either encoding.
    tree_forms = {digest(test_files), digest({name.replace("/", "\\"): value for name, value in test_files.items()})}
    checks = {
        "no_credential_patterns": not findings,
        "private_files_excluded": not protected,
        "minimax_response_matches_code": (response["edit"]["content"].rstrip() + "\n").encode() == (evidence / "after.py").read_bytes(),
        "before_snapshot_matches_tests": before == acceptance["target_before"]["code_sha256"] == response["before_sha256"],
        "after_snapshot_matches_tests": after == acceptance["target_after"]["code_sha256"] == acceptance["regression_after"]["code_sha256"],
        "tests_and_fixtures_unchanged": acceptance["target_before"]["test_tree_sha256"] in tree_forms and acceptance["target_before"]["test_tree_sha256"] == acceptance["target_after"]["test_tree_sha256"] == acceptance["regression_after"]["test_tree_sha256"],
        "six_acceptance_items_passed": acceptance["all_six_passed"] and len(acceptance["acceptance"]) == 6 and all(value == "passed" for value in acceptance["acceptance"].values()),
    }
    forbidden = {"authorization", "api_key", "reasoning_content", "thinking", "reasoning_details"}

    def contains_forbidden(value):
        if isinstance(value, dict):
            return any(str(k).lower() in forbidden or contains_forbidden(v) for k, v in value.items())
        if isinstance(value, list):
            return any(contains_forbidden(item) for item in value)
        return False

    checks["no_private_reasoning_or_auth_fields"] = not contains_forbidden(response) and not contains_forbidden(read_json(evidence / "minimax-attempt-1" / "request.json"))
    report = {"timestamp": now(), "checks": checks, "passed": all(checks.values()),
              "files_checked": len(set(files)), "known_key_available_for_exact_scan": bool(key),
              "credential_pattern_findings": findings, "private_file_findings": protected,
              "response_id": response["response_id"], "before_sha256": before, "after_sha256": after}
    write_json(args.output, report)
    print(json.dumps({"passed": report["passed"], "checks": checks}, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
