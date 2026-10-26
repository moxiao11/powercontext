# Copyright (c) 2026 OceanBase.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Pi recovery and full evidence through actual persistent Runtime boundaries."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from pydantic import JsonValue

from powercontext.builtin.artifacts.memory import MemoryEntryInput
from powercontext.builtin.artifacts.memory.models import MemoryCitation
from powercontext.builtin.persistence.sqlite import SQLiteConfig
from powercontext.builtin.runtime import (
    BuiltinConfig,
    BuiltinRuntime,
    CommitConnectorCheckpoint,
    GetMemoryEntryRequest,
    SearchMemoryRequest,
    SubmitSourceObservation,
    open_builtin_contexts,
    open_builtin_runtime,
)
from powercontext.builtin.scope import ScopeDraft
from powercontext.sources import (
    ConnectorBinding,
    SourceDefinitionRegistry,
    SourceObservation,
    SourceRef,
    manifest_for_definition,
    project_source_for_transport,
)
from powercontext.sources.connectors import ConnectorLifecycle
from powercontext.sources.pi_session import (
    PI_EVENT_SOURCE_DEFINITION,
    PiEventInput,
    PiEventSource,
    PiSessionConnector,
    PiSessionInput,
    parse_pi_session,
)
from powercontext.sources.projections import TEXT_EVIDENCE_PROJECTION_KEY, TextEvidence


class _InterruptedCapture(RuntimeError):
    pass


class _RuntimeSink:
    def __init__(self, runtime: BuiltinRuntime, *, fail_event: str | None = None) -> None:
        self.runtime = runtime
        self.registry = SourceDefinitionRegistry((PI_EVENT_SOURCE_DEFINITION,))
        self.fail_event = fail_event

    async def submit(
        self, binding: ConnectorBinding, item_id: str, definition_name: str, value: object, /
    ) -> SourceRef:
        assert isinstance(value, PiEventInput)
        if value.event_id == self.fail_event:
            raise _InterruptedCapture
        source = await self.registry.resolve(value)
        assert item_id == source.name and definition_name == "pi-event"
        result = await self.runtime.ingestion.submit(
            SubmitSourceObservation(
                scope_id=binding.scope_id, observation=project_source_for_transport(self.registry, source)
            )
        )
        return result.source_ref


class _RuntimeCheckpoints:
    def __init__(self, runtime: BuiltinRuntime) -> None:
        self.runtime = runtime

    async def load(self, binding: ConnectorBinding, /) -> JsonValue | None:
        return (await self.runtime.ingestion.checkpoint(binding)).checkpoint

    async def save(
        self, binding: ConnectorBinding, checkpoint: JsonValue | None, /, *, expected: JsonValue | None
    ) -> None:
        await self.runtime.ingestion.commit(
            CommitConnectorCheckpoint(binding=binding, checkpoint=checkpoint, expected=expected)
        )


async def _run(directory: Path, leaf: str | None = None, *, fail_event: str | None = None):
    config = BuiltinConfig(database=SQLiteConfig(url=f"sqlite+aiosqlite:///{directory / 'history.db'}"))
    async with open_builtin_runtime(config) as runtime:
        assert runtime.scopes is not None
        scope = await runtime.scopes.create(ScopeDraft(title="Pi", summary="History", idempotency_key="pi"))
        binding = ConnectorBinding(
            scope_id=scope.scope_id, binding_id="pi", connector_name="pi-session-history", connector_version="1"
        )
        await runtime.ingestion.register(manifest_for_definition(PI_EVENT_SOURCE_DEFINITION))
        result = await ConnectorLifecycle(
            sink=_RuntimeSink(runtime, fail_event=fail_event), checkpoints=_RuntimeCheckpoints(runtime)
        ).run(PiSessionConnector(directory / "session.jsonl", leaf), binding)
    async with open_builtin_contexts(config) as contexts:
        entries = await (await contexts.get(binding.scope_id)).sources.journal.entries()
    return result, entries


def _message(event_id: str, parent: str | None, content: str) -> dict[str, JsonValue]:
    return {"type": "message", "id": event_id, "parentId": parent, "message": {"role": "user", "content": content}}


async def _write(directory: Path, records: list[dict[str, JsonValue]], *, sorted_keys: bool = False) -> None:
    header: dict[str, JsonValue] = {"type": "session", "version": 3, "id": "persistent"}
    content = "\n".join(json.dumps(row, ensure_ascii=False, sort_keys=sorted_keys) for row in [header, *records])
    await asyncio.to_thread((directory / "session.jsonl").write_text, content + "\n", encoding="utf-8")


async def test_partial_ingestion_retries_idempotently_after_runtime_restart(tmp_path: Path) -> None:
    records = [_message("root", None, "root evidence")]
    await _write(tmp_path, records)
    first, _ = await _run(tmp_path)
    records.extend([_message("new", "root", "new evidence"), _message("last", "new", "last evidence")])
    await _write(tmp_path, records)
    with pytest.raises(_InterruptedCapture):
        await _run(tmp_path, fail_event="last")
    unchanged, partial = await _run(tmp_path, "root")
    assert unchanged.previous_checkpoint == first.committed_checkpoint
    assert unchanged.items == () and len(partial) == 2
    recovered, complete = await _run(tmp_path)
    assert recovered.previous_checkpoint == first.committed_checkpoint
    assert len(recovered.items) == 2 and len(complete) == 3
    replay, history = await _run(tmp_path)
    assert replay.items == () and history == complete


async def test_changed_off_branch_record_fails_before_any_new_source_is_saved(tmp_path: Path) -> None:
    records = [_message("root", None, "shared"), _message("left", "root", "left"), _message("right", "root", "right")]
    await _write(tmp_path, records)
    await _run(tmp_path, "left")
    before, _ = await _run(tmp_path, "right")
    records.append(_message("tail", "right", "tail"))
    original = records[1]
    records[1] = {**original, "metadata": {"changed": True}}
    await _write(tmp_path, records)
    with pytest.raises(ValueError):
        await _run(tmp_path, "tail")
    records[1] = original
    await _write(tmp_path, records, sorted_keys=True)
    stable, history = await _run(tmp_path, "right")
    assert stable.previous_checkpoint == before.committed_checkpoint
    assert stable.items == () and len(history) == 3
    recovered, history = await _run(tmp_path, "tail")
    assert len(recovered.items) == 1 and len(history) == 4


class _ChunkedEvidencePipeline:
    async def extract(self, request, /):
        candidates = []
        for source in request.sources:
            evidence = TextEvidence.model_validate(source.projection(TEXT_EVIDENCE_PROJECTION_KEY))
            for index, offset in enumerate(range(0, len(evidence.content), 1000)):
                candidates.append(
                    MemoryEntryInput(
                        kind=f"pi-evidence-{index}", text=evidence.content[offset : offset + 1000], sources=(source,)
                    )
                )
        return tuple(candidates)


async def test_large_tool_result_survives_restart_and_exact_memory_citation(tmp_path: Path) -> None:
    output = "largeevidence " + "完整结果 " * 3000 + " tailmarker"
    records: list[dict[str, JsonValue]] = [
        _message("root", None, "request"),
        {
            "type": "message",
            "id": "result",
            "parentId": "root",
            "message": {
                "role": "toolResult",
                "toolName": "read",
                "toolCallId": "call-1",
                "content": [{"type": "text", "text": output}],
                "extra": {"exitCode": 0},
            },
        },
    ]
    await _write(tmp_path, records)
    result, _ = await _run(tmp_path)
    config = BuiltinConfig(database=SQLiteConfig(url=f"sqlite+aiosqlite:///{tmp_path / 'history.db'}"))
    async with open_builtin_runtime(config, candidate_pipeline=_ChunkedEvidencePipeline()) as runtime:
        memory = runtime.memory.for_scope(result.binding.scope_id)
        for _ in range(4):
            if not (await memory.flush()).processed:
                break
        else:
            pytest.fail("Pi sources did not drain")
    async with open_builtin_contexts(config) as contexts:
        entries = await (await contexts.get(result.binding.scope_id)).sources.journal.entries()
        stored = {entry.source_ref.source_id: entry.source for entry in entries}
    async with open_builtin_runtime(config) as runtime:
        memory = runtime.memory.for_scope(result.binding.scope_id)
        hits = (await memory.search(SearchMemoryRequest(query="tailmarker", mode="fts", limit=20))).hits
        assert hits
        hit = hits[0]
        entry = await memory.get(
            GetMemoryEntryRequest(
                citation=MemoryCitation(
                    memory_ref=hit.memory_ref, entry_id=hit.entry_id, entry_version_id=hit.entry_version_id
                )
            )
        )
        assert "tailmarker" in entry.entry.text
        observation = stored[entry.entry.sources[0].source_id]
        assert isinstance(observation, SourceObservation)
        evidence = TextEvidence.model_validate(observation.projection(TEXT_EVIDENCE_PROJECTION_KEY))
        assert evidence.content == "toolResult: [tool_result read call-1] " + output
        assert len(evidence.content.encode()) > 8192
        registry = SourceDefinitionRegistry((PI_EVENT_SOURCE_DEFINITION,))
        recovered = await registry.read(PiEventSource.model_validate(observation.payload))
        assert isinstance(recovered, PiEventInput)
        expected = parse_pi_session(
            PiSessionInput(content=await asyncio.to_thread((tmp_path / "session.jsonl").read_bytes))
        )[1]
        assert recovered == expected and recovered.record == records[1]
