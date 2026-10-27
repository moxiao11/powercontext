"""Fail closed if evidence is only a reference run or lacks real model records."""
import argparse
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("evidence", type=Path)
    args = parser.parse_args()
    root = args.evidence
    if not (root / "acceptance.json").is_file():
        print(json.dumps({"submission_evidence_ready": False, "issues": ["Missing completed acceptance.json"]}, indent=2))
        return 1
    report = json.loads((root / "acceptance.json").read_text(encoding="utf-8"))
    issues = []
    if not report.get("all_six_passed") or report.get("mode") != "live":
        issues.append("MiniMax live participation is missing; a reference run does not satisfy all six requirements")
    if any(value != "passed" for value in report.get("acceptance", {}).values()) or len(report.get("acceptance", {})) != 6:
        issues.append("All six acceptance items must be present and passed")
    responses = list(root.glob("minimax-attempt-*/response.json"))
    if not responses:
        issues.append("No recorded MiniMax API response")
    for path in responses:
        record = json.loads(path.read_text(encoding="utf-8"))
        if record.get("provider") != "minimax" or record.get("live") is not True or not record.get("response_id"):
            issues.append("Invalid model response record: " + str(path))
    for name in ("database.jsonl", "powercontext.jsonl", "change.diff", "before.py", "after.py",
                 "target-before.xml", "resume-before.json", "resume-after.json", "resume-spec-updated.json"):
        if not (root / name).is_file():
            issues.append("Missing evidence: " + name)
    print(json.dumps({"submission_evidence_ready": not issues, "issues": issues}, ensure_ascii=False, indent=2))
    return 1 if issues else 0


if __name__ == "__main__":
    raise SystemExit(main())
