from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

from powercontext.client import PowerContextClient
from powercontext.http import CreateScopeRequest, RememberMemoryRequest

from .common import append_event, canonical, read_json, write_json


class TaskState:
    """Local files contain addresses only. Task content lives in PowerContext."""

    def __init__(self, pointer: Path, audit: Path | None = None):
        self.pointer = pointer
        self.audit = audit

    def client(self):
        return PowerContextClient(os.getenv("SDD_POWERCONTEXT_URL", "http://127.0.0.1:18080"),
                                  token=os.getenv("SDD_POWERCONTEXT_TOKEN") or None,
                                  timeout=30)

    async def _save(self, task_id: str, state: dict):
        async with self.client() as client:
            if self.pointer.is_file():
                pointer = read_json(self.pointer)
                if pointer["task_id"] != task_id:
                    raise ValueError("State pointer belongs to a different task")
                scope_id = pointer["scope_id"]
            else:
                scope = await client.create_scope(CreateScopeRequest(
                    title="SDD " + task_id, summary="Task progress and version-bound test evidence",
                    idempotency_key="sdd:" + task_id))
                scope_id = scope.scope_id
            text = canonical({**state, "schema": "sdd.task-state.v1", "task_id": task_id})
            if len(text.encode("utf-8")) > 8192:
                raise ValueError("Task state exceeds PowerContext's 8192-byte memory limit")
            saved = await client.remember_memory(RememberMemoryRequest(
                scope_id=scope_id, kind="task-state", text=text,
                reason="Persist verified task progress for the next process"))
            if len(saved.records) != 1:
                raise RuntimeError("PowerContext did not return exactly one state record")
            reference = saved.records[0].artifact.model_dump(mode="json")
            pointer = {"task_id": task_id, "scope_id": scope_id, "artifact": reference}
            temporary = self.pointer.with_suffix(".tmp")
            write_json(temporary, pointer)
            temporary.replace(self.pointer)
            append_event(self.audit, {"operation": "powercontext.write", "pointer": pointer, "state": json.loads(text)})
            return pointer

    def save(self, task_id: str, state: dict):
        return asyncio.run(self._save(task_id, state))

    async def _load(self):
        if not self.pointer.is_file():
            append_event(self.audit, {"operation": "powercontext.empty"})
            return None
        pointer = read_json(self.pointer)
        reference = pointer["artifact"]
        async with self.client() as client:
            record = await client.get_artifact_revision(pointer["scope_id"], reference["family"],
                                                        reference["artifact_id"], reference["revision"])
        state = json.loads(record.content["text"])
        if state.get("schema") != "sdd.task-state.v1" or state.get("task_id") != pointer["task_id"]:
            raise ValueError("PowerContext state identity mismatch")
        append_event(self.audit, {"operation": "powercontext.read", "pointer": pointer, "state": state})
        return state

    def load(self):
        return asyncio.run(self._load())
