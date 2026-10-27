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

"""Real native index checks; these require the optional embedded seekdb binding."""

from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest
from sqlalchemy import event

from powercontext.builtin.artifacts.memory import EmbeddingProfile, MemoryEntryInput, MemorySearchRequest
from powercontext.builtin.artifacts.memory.service import MemoryService
from powercontext.builtin.inference import EmbeddingResult
from powercontext.builtin.persistence.memory import RelationalMemoryBackend
from powercontext.builtin.persistence.memory_index import CompositeMemoryIndex
from powercontext.builtin.persistence.oceanbase.memory_index import OceanBaseMemoryFTSIndex, OceanBaseMemoryVectorIndex
from powercontext.builtin.persistence.seekdb import SeekDBConfig
from powercontext.builtin.runtime import BuiltinConfig, open_builtin_contexts
from powercontext.builtin.tags import MemoryEntryTagTarget, TagFilter

pytest.importorskip("pylibseekdb")

_PROFILE = EmbeddingProfile(profile_id="hybrid-filter-test", model="offline", dimension=3)


class _Model:
    profile = _PROFILE

    async def embed(self, texts, /):
        return EmbeddingResult(vectors=tuple((1.0, 0.0, 0.0) for _ in texts))


def test_native_hybrid_limits_each_filtered_channel_and_keeps_current_refs(tmp_path):
    async def scenario():
        async with open_builtin_contexts(
            BuiltinConfig(database=SeekDBConfig(path=tmp_path / "db")), embedding_model=_Model()
        ) as contexts:
            memory = (await contexts.get("project")).artifacts.memory
            first = await memory.remember(
                memory=None,
                entries=tuple(
                    MemoryEntryInput(kind="fact", text=f"Alpha shared evidence number {n}.") for n in range(8)
                ),
                mode="append",
            )
            current = await memory.remember(
                memory=first, entries=(MemoryEntryInput(kind="fact", text="Unrelated later entry."),), mode="append"
            )
            other_memory = MemoryService(
                backend=RelationalMemoryBackend(
                    database=contexts.database,
                    scope_id="project",
                    artifacts=contexts.repositories.artifacts,
                    index=contexts.index,
                ),
                embedding_model=_Model(),
                id_factory=lambda _: uuid4().hex,
            )
            other = await other_memory.remember(
                memory=None, entries=(MemoryEntryInput(kind="fact", text="Alpha other artifact."),), mode="append"
            )
            decoy = (await contexts.get("other-scope")).artifacts.memory
            await decoy.remember(
                memory=None, entries=(MemoryEntryInput(kind="fact", text="Alpha other scope."),), mode="append"
            )
            assert current is not None and other is not None
            entries = tuple(entry for entry in await memory.entries(current) if "Alpha" in entry.text)
            selected = entries[-1]
            for artifact, entry_id, labels in (
                (current.artifact_id, entries[0].entry_id, ("red",)),
                (current.artifact_id, selected.entry_id, ("red", "blue")),
                (other.artifact_id, other.content.manifest.entries[0].entry_id, ("red", "blue")),
            ):
                target = MemoryEntryTagTarget(artifact_id=artifact, entry_id=entry_id)
                tags = await contexts.records.get_tags("project", target)
                await contexts.records.replace_tags("project", target, labels, expected_etag=tags.etag)

            statements = []

            def record(_connection, _cursor, statement, parameters, _context, _executemany):
                if "AGAINST" in statement.upper() or "l2_distance" in statement.lower():
                    statements.append((statement, parameters))

            async with contexts.database.transaction() as connection:
                for tag_filter, expected in (
                    (None, None),
                    (TagFilter(tags=("red", "blue"), match="all"), {selected.entry_id}),
                    (TagFilter(tags=("red", "blue"), match="any"), {selected.entry_id, entries[0].entry_id}),
                    (TagFilter(tags=("absent",)), set()),
                ):
                    request = MemorySearchRequest(
                        query="alpha",
                        analyzed_query="alpha",
                        memories=(current.as_ref(),),
                        candidate_limit=2,
                        mode="hybrid",
                        query_vector=(1.0, 0.0, 0.0),
                        embedding_profile=_PROFILE,
                        tag_filter=tag_filter,
                    )
                    statements.clear()
                    event.listen(connection.sync_connection, "before_cursor_execute", record)
                    try:
                        result = await contexts.index.search(connection, "project", request)
                    finally:
                        event.remove(connection.sync_connection, "before_cursor_execute", record)
                    assert len(statements) == 1
                    assert len(result.fts) <= 2 and len(result.vector) <= 2
                    assert all(hit.memory_ref == current.as_ref() for hit in result.fts + result.vector)
                    if expected is not None:
                        assert {hit.entry_id for hit in result.fts} == expected
                        assert {hit.entry_id for hit in result.vector} == expected
                    statement, parameters = statements[0]
                    plan = "\n".join(
                        str(row[0]) for row in (await connection.exec_driver_sql("EXPLAIN " + statement, parameters))
                    )
                    assert "TEXT RETRIEVAL SCAN" in plan
                    assert "VECTOR INDEX" in plan
                    baseline = CompositeMemoryIndex(OceanBaseMemoryFTSIndex(), OceanBaseMemoryVectorIndex(_PROFILE))
                    if tag_filter is not None:
                        control = await baseline.search(connection, "project", request)
                        assert {hit.entry_id for hit in result.fts} == {hit.entry_id for hit in control.fts}
                        assert {hit.entry_id for hit in result.vector} == {hit.entry_id for hit in control.vector}
                multi = await contexts.index.search(
                    connection,
                    "project",
                    request.model_copy(
                        update={
                            "memories": (current.as_ref(), other.as_ref()),
                            "tag_filter": TagFilter(tags=("blue",)),
                            "candidate_limit": 10,
                        }
                    ),
                )
                assert {hit.memory_ref.artifact_id for hit in multi.fts} == {current.artifact_id, other.artifact_id}
                assert {hit.memory_ref.artifact_id for hit in multi.vector} == {current.artifact_id, other.artifact_id}

    asyncio.run(scenario())
