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
import sqlite3

import pytest
from pydantic import ValidationError
from sqlalchemy import insert
from sqlalchemy.exc import IntegrityError

from powercontext.artifacts import ArtifactRef
from powercontext.builtin.artifacts.memory import EmbeddingProfile, MemoryEntryInput
from powercontext.builtin.artifacts.topic_memory import (
    TopicMemoryContent,
    TopicMemoryDraft,
    TopicMemorySearchRequest,
    prepare_topic_memory_projection,
)
from powercontext.builtin.inference import EmbeddingResult
from powercontext.builtin.persistence.sqlite import SQLiteConfig, SQLiteProfile
from powercontext.builtin.persistence.sqlite.topic_memory_index import (
    SQLiteTopicMemoryFTSIndex,
    SQLiteTopicMemoryVectorIndex,
)
from powercontext.builtin.persistence.tables import BUILTIN_TABLES, SOURCE_LIFECYCLE_TOPICS_TABLE
from powercontext.builtin.persistence.topic_memory import TopicMemoryRepository
from powercontext.builtin.persistence.topic_memory_index import CompositeTopicMemoryIndex
from powercontext.builtin.records import ArtifactWrite
from powercontext.builtin.runtime import (
    BuiltinConfig,
    CaptureSource,
    GetMemoryEntryRequest,
    GetTopicMemoryRequest,
    RememberMemoryRequest,
    SearchMemoryRequest,
    SearchTopicMemoryRequest,
    open_builtin_runtime,
)
from powercontext.builtin.runtime.source_lifecycle import SourceLifecycleError, SourceLifecycleEvent
from powercontext.builtin.scope import ScopeDraft
from powercontext.sources import SourceRef


def _event(sequence, available, *, reason="test lifecycle"):
    return SourceLifecycleEvent(node_id="root", revision=7, sequence=sequence, available=available, reason=reason)


async def _graph(runtime, name):
    scope = await runtime.scopes.create(ScopeDraft(title=name, summary="lifecycle", idempotency_key=name))
    sid = scope.scope_id
    lifecycle = runtime.lifecycle.for_scope(sid)
    receipt = await runtime.sources.for_scope(sid).capture(
        CaptureSource(source_id="root", content="evidence", metadata={})
    )
    await lifecycle.register_source("root", receipt.source_ref, revision=7)
    refs = {"root": receipt.source_ref}
    for index in range(3):
        key = f"memory{index}"
        result = await runtime.memory.for_scope(sid).remember(
            RememberMemoryRequest(entries=(MemoryEntryInput(kind="fact", text=f"{key} lifecycle evidence"),))
        )
        refs[key] = result.entry.citation
        await lifecycle.register_memory(key, refs[key], parents=("root",), policy="all")
    topic = await runtime.records.for_scope(sid).create_artifact(
        "topic-memory", ArtifactWrite(content={"title": "topic", "summary": "lifecycle summary", "detail": "evidence"})
    )
    refs["topic"] = ArtifactRef(family="topic-memory", artifact_id=topic.artifact_id, revision=topic.revision)
    await lifecycle.register_topic("topic", refs["topic"], parents=("memory0", "memory1"), policy="all")
    return sid, lifecycle, refs


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("node_id", " "),
        ("node_id", 1),
        ("reason", "\t\n"),
        ("reason", False),
        ("revision", True),
        ("revision", "7"),
        ("revision", 7.0),
        ("revision", 0),
        ("sequence", True),
        ("sequence", "1"),
        ("sequence", 1.0),
        ("sequence", -1),
        ("available", 0),
        ("available", "false"),
        ("extra", "forbidden"),
    ],
)
def test_event_types_and_extra_fields_are_strict(field, value):
    data = _event(1, False).model_dump()
    data[field] = value
    with pytest.raises(ValidationError):
        SourceLifecycleEvent.model_validate(data)


def test_registration_identity_references_and_event_purpose_are_scope_local(tmp_path):
    async def scenario():
        config = BuiltinConfig(database=SQLiteConfig(url=f"sqlite+aiosqlite:///{tmp_path / 'scopes.db'}"))
        async with open_builtin_runtime(config) as runtime:
            left, service, refs = await _graph(runtime, "left")
            right, other, other_refs = await _graph(runtime, "right")
            before = (await runtime.memory.for_scope(left).list()).memory_ref
            await service.register_source("root", refs["root"], revision=7)
            await service.register_memory("memory0", refs["memory0"], parents=("root",), policy="all")
            await service.register_topic("topic", refs["topic"], parents=("memory0", "memory1"), policy="all")
            assert (await runtime.memory.for_scope(left).list()).memory_ref == before
            with pytest.raises(SourceLifecycleError):
                await service.register_source("root", refs["root"], revision=8)
            with pytest.raises(SourceLifecycleError):
                await service.register_source(
                    "missing", SourceRef(source_type="content", source_id="missing"), revision=1
                )
            for parents, policy in [
                ((), "all"),
                (("root", "root"), "all"),
                (("missing",), "all"),
                (("root",), "invalid"),
            ]:
                with pytest.raises(SourceLifecycleError):
                    await service.register_memory("new", refs["memory0"], parents=parents, policy=policy)
            with pytest.raises(SourceLifecycleError):
                await service.register_memory("new", other_refs["memory0"], parents=("root",), policy="all")
            with pytest.raises(SourceLifecycleError):
                await service.register_topic(
                    "new", refs["topic"].model_copy(update={"revision": 99}), parents=("root",), policy="all"
                )
            for invalid in [
                _event(1, False).model_copy(update={"node_id": "memory0"}),
                _event(1, False).model_copy(update={"node_id": "unknown"}),
                _event(1, False).model_copy(update={"revision": 8}),
            ]:
                with pytest.raises(SourceLifecycleError):
                    await service.apply(invalid)
            assert await service.apply(_event(1, False)) == []
            assert {
                item.state for item in (await runtime.memory.for_scope(left).list(include_inactive=True)).entries
            } == {"inactive"}
            assert len((await runtime.memory.for_scope(right).list()).entries) == 3
            for node, reference in other_refs.items():
                assert await other.resolve(node, purpose="generation") == reference
            for node, purpose in [("unknown", "audit"), ("root", "invalid"), ("memory0", "generation")]:
                with pytest.raises(SourceLifecycleError):
                    await service.resolve(node, purpose=purpose)
        async with open_builtin_runtime(config) as runtime:
            service = runtime.lifecycle.for_scope(left)
            with pytest.raises(SourceLifecycleError):
                await service.apply(_event(1, False, reason="different replay"))
            await service.apply(_event(2, True))
            for node, reference in refs.items():
                assert await service.resolve(node, purpose="generation") == reference
            assert len((await runtime.memory.for_scope(right).list()).entries) == 3

    asyncio.run(scenario())


@pytest.mark.parametrize("restoring", [False, True])
def test_partial_native_sqlite_write_failure_retries_after_restart_without_duplicate_revisions(tmp_path, restoring):
    async def scenario():
        path = tmp_path / "failure.db"
        config = BuiltinConfig(database=SQLiteConfig(url=f"sqlite+aiosqlite:///{path}"))
        async with open_builtin_runtime(config) as runtime:
            sid, service, refs = await _graph(runtime, "failure")
            if restoring:
                await service.apply(_event(1, False))
            before = (await runtime.memory.for_scope(sid).list(include_inactive=True)).memory_ref
            assert before is not None
            # The first state transition commits, then the next actual native
            # Memory revision fails in SQLite. No domain method is replaced.
            with sqlite3.connect(path) as connection:
                connection.execute(
                    f"""CREATE TRIGGER fail_lifecycle BEFORE INSERT ON pc_artifacts
                    WHEN NEW.family = 'memory' AND NEW.revision >= {before.revision + 2}
                    BEGIN SELECT RAISE(ABORT, 'lifecycle native write failure'); END"""
                )
            event = _event(2 if restoring else 1, restoring)
            with pytest.raises(IntegrityError):
                await service.apply(event)
            partial = await runtime.memory.for_scope(sid).list(include_inactive=True)
            assert partial.memory_ref is not None
            assert partial.memory_ref.revision == before.revision + 1
            assert sorted(item.state for item in partial.entries).count("active") == (1 if restoring else 2)
        with sqlite3.connect(path) as connection:
            connection.execute("DROP TRIGGER fail_lifecycle")
        async with open_builtin_runtime(config) as runtime:
            service = runtime.lifecycle.for_scope(sid)
            active = await service.apply(event)
            assert active == (sorted(refs) if restoring else [])
            after = await runtime.memory.for_scope(sid).list(include_inactive=True)
            assert after.memory_ref is not None
            assert after.memory_ref.revision == before.revision + 3
            await service.apply(event)
            assert (await runtime.memory.for_scope(sid).list(include_inactive=True)).memory_ref == after.memory_ref
            for node, reference in refs.items():
                assert await service.resolve(node, purpose="audit") == reference
                if node.startswith("memory"):
                    entry = await runtime.memory.for_scope(sid).get(GetMemoryEntryRequest(citation=reference))
                    assert entry.entry.entry_version_id == reference.entry_version_id
            await service.register_memory("memory0", refs["memory0"], parents=("root",), policy="all")
            assert (await runtime.memory.for_scope(sid).list(include_inactive=True)).memory_ref == after.memory_ref

    asyncio.run(scenario())


class _Embedding:
    profile = EmbeddingProfile(profile_id="lifecycle-vector", model="offline", dimension=2)

    async def embed(self, texts):
        return EmbeddingResult(vectors=((1.0, 0.0),) * len(texts))


def test_native_vector_topic_browse_and_exact_reads_follow_lifecycle(tmp_path):
    async def scenario():
        config = BuiltinConfig(database=SQLiteConfig(url=f"sqlite+aiosqlite:///{tmp_path / 'vector.db'}"))
        async with open_builtin_runtime(config, embedding_model=_Embedding()) as runtime:
            sid, service, refs = await _graph(runtime, "vectors")
            for sequence, available in [(1, False), (2, True)]:
                await service.apply(_event(sequence, available))
                for mode in ("fts", "vector", "hybrid"):
                    memories = await runtime.memory.for_scope(sid).search(
                        SearchMemoryRequest(query="lifecycle", mode=mode)
                    )
                    assert bool(memories.hits) is available
                for allow_embedding in (False, True):
                    topics = await runtime.topic_memory.for_scope(sid).search(
                        SearchTopicMemoryRequest(query="lifecycle"), allow_embedding=allow_embedding
                    )
                    assert bool(topics.hits) is available
                page = await runtime.topic_memory.for_scope(sid).browse(limit=10)
                assert bool(page) is available
                topic = await runtime.topic_memory.for_scope(sid).get(GetTopicMemoryRequest(artifact=refs["topic"]))
                assert topic.topic.as_ref() == refs["topic"]

    asyncio.run(scenario())


def test_withdrawn_nearest_topic_does_not_consume_a_single_vector_candidate_slot():
    async def scenario():
        profile = _Embedding.profile
        vectors = SQLiteTopicMemoryVectorIndex(profile)
        index = CompositeTopicMemoryIndex(SQLiteTopicMemoryFTSIndex(), vectors)
        repository = TopicMemoryRepository(index=index)
        async with SQLiteProfile.open(
            SQLiteConfig(), tables=BUILTIN_TABLES + index.tables, load_vector_extension=True
        ) as database:
            async with database.database.transaction() as connection:
                await repository.initialize(connection)
                for scope in ("scope-a", "scope-b"):
                    for key, vector in [("nearest", (1.0, 0.0)), ("supported", (0.0, 1.0))]:
                        content = TopicMemoryContent(title=key, summary="evidence", detail="evidence")
                        projection = prepare_topic_memory_projection(content)
                        await repository.publish_create(
                            connection,
                            scope,
                            key,
                            TopicMemoryDraft(content=content),
                            prepare_topic_memory_projection(
                                content,
                                topic_embedding=vector,
                                chunk_embeddings=(vector,) * len(projection.chunks),
                                embedding_profile=profile,
                            ),
                        )
                await connection.execute(
                    insert(SOURCE_LIFECYCLE_TOPICS_TABLE).values(
                        scope_id="scope-a", artifact_id="nearest", revision=1, available=False
                    )
                )
            async with database.database.transaction() as connection:
                for scope, expected in [("scope-a", "supported"), ("scope-b", "nearest")]:
                    channels = await vectors.search(
                        connection,
                        scope,
                        TopicMemorySearchRequest(
                            query="evidence",
                            mode="vector",
                            candidate_limit=1,
                            query_vector=(1.0, 0.0),
                            embedding_profile=profile,
                        ),
                    )
                    for hits in (channels.topic_vector, channels.detail_vector):
                        assert [hit.artifact_ref.artifact_id for hit in hits] == [expected]

    asyncio.run(scenario())
