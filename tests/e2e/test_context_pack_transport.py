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

from __future__ import annotations

import asyncio
import base64
import gzip
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from powercontext.builtin.artifacts.memory import MemoryCandidateRequest, MemoryEntryInput
from powercontext.builtin.persistence.sqlite import SQLiteConfig
from powercontext.builtin.runtime import (
    BuiltinConfig,
    CaptureSource,
    ContextAssembly,
    ContextPack,
    ContextPackDelta,
    PrepareContextRequest,
    apply_context_pack_delta,
    open_builtin_runtime,
)
from powercontext.builtin.scope import ScopeDraft
from powercontext.builtin.sources import ContentSource

_FIXTURES = Path(__file__).parents[1] / "fixtures" / "context_pack"


class _MeetingPipeline:
    async def extract(self, request: MemoryCandidateRequest, /) -> tuple[MemoryEntryInput, ...]:
        return tuple(
            MemoryEntryInput(kind="meeting-turn", text=source.content, sources=(source,))
            for source in request.sources
            if isinstance(source, ContentSource)
        )


async def test_forty_round_real_meeting_transport_and_independent_receiver(tmp_path: Path) -> None:
    sample = json.loads((_FIXTURES / "meeting_turns.json").read_text(encoding="utf-8"))
    turns = sample["turns"]
    config = BuiltinConfig(database=SQLiteConfig(url=f"sqlite+aiosqlite:///{tmp_path / 'transport.db'}"))
    frames, contents, digests, rounds = [], [], [], []
    raw_full_bytes = full_pack_bytes = incremental_bytes = gzip_bytes = 0
    base = None
    queries = ("remote", "control")
    async with open_builtin_runtime(config, candidate_pipeline=_MeetingPipeline()) as runtime:
        assert runtime.scopes is not None
        scope = await runtime.scopes.create(
            ScopeDraft(title="Meeting", summary="Transport", idempotency_key="transport")
        )
        sources = runtime.sources.for_scope(scope.scope_id)
        memory = runtime.memory.for_scope(scope.scope_id)
        context = runtime.context.for_scope(scope.scope_id)

        async def capture(index: int) -> None:
            turn = turns[index]
            await sources.capture(
                CaptureSource(
                    source_id=f"meeting-turn-{turn['turn_index']}",
                    content=turn["speaker"] + ": " + turn["content"],
                    metadata={},
                )
            )

        for index in range(8):
            await capture(index)
        while (await memory.flush()).processed:
            pass
        for index in range(40):
            if index and index % 5 == 0:
                await capture(8 + index // 5 - 1)
                while (await memory.flush()).processed:
                    pass
            query = queries[(index // 10) % len(queries)]
            request = PrepareContextRequest(query=query, max_bytes=8000)
            ordinary = await context.prepare(request)
            assert ordinary.content, "Cost sequence must not use empty context rounds"
            raw = ordinary.content.encode("utf-8")
            envelope = json.loads(ordinary.content.split("\n")[-2])
            evidence_bodies = json.dumps([item["content"] for item in envelope["items"]], ensure_ascii=False).encode()
            complete = ContextPack.from_content(ordinary.content)
            message = await context.prepare_incremental(request, base_pack=base)
            wire = message.to_bytes()
            if base is None:
                assert isinstance(message, ContextPack)
                receiver = ContextPack.from_bytes(wire)
            else:
                assert isinstance(message, ContextPackDelta)
                receiver = apply_context_pack_delta(
                    ContextPack.from_bytes(base.to_bytes()), ContextPackDelta.from_bytes(wire)
                )
            assert receiver.items == complete.items
            assert b"".join(receiver.items) == raw
            assert receiver.digest == complete.digest
            assert message.byte_count == len(wire)
            raw_full_bytes += len(raw)
            full_pack_bytes += len(complete.to_bytes())
            incremental_bytes += len(wire)
            gzip_size = len(gzip.compress(raw, compresslevel=9, mtime=0))
            gzip_bytes += gzip_size
            frames.append(base64.b64encode(wire).decode("ascii"))
            contents.append(base64.b64encode(raw).decode("ascii"))
            digests.append(receiver.digest)
            rounds.append({
                "round": index + 1,
                "query": query,
                "raw_bytes": len(raw),
                "full_pack_bytes": len(complete.to_bytes()),
                "sent_bytes": len(wire),
                "gzip_bytes": gzip_size,
                "context_sha256": hashlib.sha256(raw).hexdigest(),
                "evidence_sha256": hashlib.sha256(evidence_bodies).hexdigest(),
                "wire_type": "pack" if base is None else "delta",
                "prefix_items": message.prefix_items if isinstance(message, ContextPackDelta) else None,
            })
            base = receiver
    completed = await asyncio.to_thread(
        subprocess.run,
        [sys.executable, str(_FIXTURES / "receiver.py")],
        input=json.dumps(frames),
        text=True,
        capture_output=True,
        check=True,
        timeout=30,
    )
    independent = json.loads(completed.stdout)
    assert [value["content"] for value in independent] == contents
    assert [value["digest"] for value in independent] == digests
    distinct = len({row["context_sha256"] for row in rounds})
    distinct_evidence = len({row["evidence_sha256"] for row in rounds})
    assert len(rounds) == 40 and distinct >= 4
    assert distinct_evidence >= 4, "Measurement must also exercise different retrieved evidence bodies"
    report = {
        "configuration": {
            "origin": "product self-test, not the hidden platform configuration",
            "source": sample["source"],
            "meeting_id": sample["meeting_id"],
            "initial_turn_indices": [turn["turn_index"] for turn in turns[:8]],
            "append_rounds": [6, 11, 16, 21, 26, 31, 36],
            "queries": queries,
            "query_switch_rounds": [11, 21, 31],
            "max_bytes": 8000,
        },
        "round_count": len(rounds),
        "nonempty_rounds": sum(row["raw_bytes"] > 0 for row in rounds),
        "distinct_contexts": distinct,
        "distinct_evidence_bodies": distinct_evidence,
        "raw_full_bytes": raw_full_bytes,
        "full_v1_pack_bytes": full_pack_bytes,
        "incremental_bytes": incremental_bytes,
        "gzip_bytes": gzip_bytes,
        "saving_vs_raw": 1 - incremental_bytes / raw_full_bytes,
        "saving_vs_full_v1_pack": 1 - incremental_bytes / full_pack_bytes,
        "saving_vs_gzip": 1 - incremental_bytes / gzip_bytes,
        "independent_receiver": "stdlib only, separate Python process",
        "rounds": rounds,
    }
    print("CONTEXT_PACK_MEASUREMENT=" + json.dumps(report, ensure_ascii=False, sort_keys=True), flush=True)
    assert report["saving_vs_raw"] >= 0.45


async def test_native_empty_context_round_trip_and_authorization_are_preserved() -> None:
    async with open_builtin_runtime(BuiltinConfig(database=SQLiteConfig())) as runtime:
        assert runtime.scopes is not None
        scope = await runtime.scopes.create(ScopeDraft(title="Empty", summary="Empty", idempotency_key="empty"))
        context = runtime.context.for_scope(scope.scope_id)
        empty_request = PrepareContextRequest(query="empty", assembly=ContextAssembly(sections=()))
        ordinary = await context.prepare(empty_request)
        assert ordinary.content is None
        pack = await context.prepare_incremental(empty_request)
        assert isinstance(pack, ContextPack) and pack.items == ()
        base = ContextPack.from_content("previous context")
        delta = await context.prepare_incremental(empty_request, base_pack=base)
        assert isinstance(delta, ContextPackDelta)
        assert (
            apply_context_pack_delta(
                ContextPack.from_bytes(base.to_bytes()), ContextPackDelta.from_bytes(delta.to_bytes())
            ).items
            == ()
        )

        async def deny(scope_ids: tuple[str, ...]) -> None:
            assert scope_ids == (scope.scope_id,)
            raise PermissionError

        with pytest.raises(PermissionError):
            await context.prepare_incremental(PrepareContextRequest(query="context"), authorize_scopes=deny)
