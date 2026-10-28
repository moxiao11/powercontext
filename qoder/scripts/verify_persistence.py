#!/usr/bin/env python3
"""Verify real PowerContext persistence across a local Docker container restart.

This restarts only the explicitly named PowerContext container. Other users of
that same local service may see a short interruption. Creates disposable data.
"""

import argparse
import json
import subprocess
import time
import uuid

import httpx


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api", default="http://127.0.0.1:8100")
    parser.add_argument("--container", required=True)
    args = parser.parse_args()
    with httpx.Client(base_url=args.api, timeout=30) as client:
        created = client.post("/api/projects", json={"name": "持久化重启验证（示例）"})
        created.raise_for_status()
        project = created.json()["project_id"]
        try:
            saved = client.post(
                "/api/memory/save-progress",
                json={
                    "project_id": project,
                    "session_id": uuid.uuid4().hex,
                    "summary": "服务重启后恢复测试",
                    "next_steps": ["验证房间约束后继续研究"],
                },
            )
            saved.raise_for_status()
            assert saved.json()["handoff"]["status"] == "committed"
            before = client.post("/api/memory/restore", params={"project_id": project})
            before.raise_for_status()
            before = before.json()
            subprocess.run(
                ["docker", "restart", args.container],
                check=True,
                stdout=subprocess.DEVNULL,
            )
            for _ in range(60):
                try:
                    health = client.get("/api/health", timeout=3)
                    if health.is_success and health.json()["powercontext"]["ready"]:
                        break
                except httpx.HTTPError:
                    pass
                time.sleep(1)
            else:
                raise RuntimeError("PowerContext readiness timed out after restart")
            # A new HTTP client cannot inherit any previous in-memory context.
            with httpx.Client(base_url=args.api, timeout=30) as fresh:
                restored = fresh.post(
                    "/api/memory/restore", params={"project_id": project}
                )
                restored.raise_for_status()
                after = restored.json()
            before_ids = sorted(
                item["citation"]["entry_id"] for item in before["memories"]
            )
            after_ids = sorted(
                item["citation"]["entry_id"] for item in after["memories"]
            )
            assert before_ids == after_ids and after_ids
            assert (
                before["handoff"]["selected_revision"]
                == after["handoff"]["selected_revision"]
            )
            assert "验证房间约束后继续研究" in after["answer"]
            print(
                json.dumps(
                    {
                        "passed": True,
                        "project_id": project,
                        "container_restarted": args.container,
                        "before_entry_ids": before_ids,
                        "after_entry_ids": after_ids,
                        "handoff_revision": after["handoff"]["selected_revision"],
                        "fresh_http_client": True,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
        finally:
            client.delete(f"/api/projects/{project}").raise_for_status()


if __name__ == "__main__":
    main()
