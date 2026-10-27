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

"""Propagate explicit Source dependencies without changing historical bodies."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from powercontext.artifacts import ArtifactRef, MemoryCitation
from powercontext.builtin.artifacts.memory import Memory, MemoryService
from powercontext.builtin.artifacts.memory.errors import MemoryLayerError
from powercontext.builtin.persistence.database import AsyncDatabase
from powercontext.builtin.persistence.source_lifecycle import (
    SourceLifecycleRepository,
    StoredLifecycleGraph,
    StoredLifecycleNode,
)
from powercontext.builtin.records import BaseValueNotFoundError
from powercontext.builtin.sources import validate_scope_id
from powercontext.sources import SourceRef

if TYPE_CHECKING:
    from powercontext.builtin.runtime.application import BuiltinRuntime


class SourceLifecycleError(ValueError):
    """An invalid lifecycle binding, event, dependency or generation use."""


class SourceLifecycleEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    node_id: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    revision: int = Field(gt=0)
    sequence: int = Field(gt=0)
    available: bool

    @field_validator("node_id", "reason")
    @classmethod
    def reject_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")  # noqa: TRY003
        return value


class ScopedSourceLifecycle:
    def __init__(self, runtime: BuiltinRuntime, database: AsyncDatabase, scope_id: str) -> None:
        self._runtime = runtime
        self._database = database
        self.scope_id = validate_scope_id(scope_id)
        self._repository = SourceLifecycleRepository()

    async def register_source(self, node_id: str, source_ref: SourceRef, *, revision: int) -> None:
        if type(revision) is not int or revision <= 0 or not isinstance(source_ref, SourceRef):
            raise SourceLifecycleError("invalid-source-binding")
        await self._register(node_id, StoredLifecycleNode(kind="source", reference=source_ref, revision=revision))

    async def register_memory(
        self, node_id: str, citation: MemoryCitation, *, parents: tuple[str, ...], policy: Literal["all", "any"]
    ) -> None:
        if not isinstance(citation, MemoryCitation):
            raise SourceLifecycleError("invalid-memory-binding")
        await self._register(
            node_id,
            StoredLifecycleNode(kind="memory", reference=citation, parents=_parents(parents), policy=_policy(policy)),
        )

    async def register_topic(
        self, node_id: str, artifact_ref: ArtifactRef, *, parents: tuple[str, ...], policy: Literal["all", "any"]
    ) -> None:
        if not isinstance(artifact_ref, ArtifactRef) or artifact_ref.family != "topic-memory":
            raise SourceLifecycleError("invalid-topic-binding")
        await self._register(
            node_id,
            StoredLifecycleNode(
                kind="topic", reference=artifact_ref, parents=_parents(parents), policy=_policy(policy)
            ),
        )

    async def _register(self, node_id: str, node: StoredLifecycleNode) -> None:
        _identifier(node_id)
        async with self._runtime._context(self.scope_id) as context, self._runtime._locked(self.scope_id):
            async with self._database.transaction() as connection:
                graph = await self._repository.load(connection, self.scope_id)
            if node_id in node.parents or any(parent not in graph.nodes for parent in node.parents):
                raise SourceLifecycleError("invalid-parent")
            existing = graph.nodes.get(node_id)
            if existing is not None:
                fields = {"available", "event"}
                if existing.model_dump(exclude=fields) != node.model_dump(exclude=fields):
                    raise SourceLifecycleError("binding-conflict")
            else:
                await self._validate_reference(node, context.artifacts.memory, context.artifacts.memory_artifact_id)
                graph.nodes[node_id] = node
            await self._persist_targets(graph)
            await self._sync_memory(graph, context.artifacts.memory, reason="source lifecycle registration")

    async def _validate_reference(self, node: StoredLifecycleNode, memory: MemoryService, memory_id: str) -> None:
        reference = node.reference
        try:
            if isinstance(reference, SourceRef):
                await self._runtime._records().get_source(self.scope_id, reference.source_type, reference.source_id)
            elif isinstance(reference, MemoryCitation):
                if reference.memory_ref.artifact_id != memory_id:
                    raise SourceLifecycleError("memory-scope-mismatch")
                await memory.validate_citation(reference)
            else:
                await self._runtime._records().get_artifact_revision(
                    self.scope_id, reference.family, reference.artifact_id, reference.revision
                )
        except (LookupError, MemoryLayerError, BaseValueNotFoundError) as error:
            raise SourceLifecycleError("unreadable-reference") from error

    async def apply(self, event: SourceLifecycleEvent) -> list[str]:
        if not isinstance(event, SourceLifecycleEvent):
            raise SourceLifecycleError("invalid-event")
        async with self._runtime._context(self.scope_id) as context, self._runtime._locked(self.scope_id):
            async with self._database.transaction() as connection:
                graph = await self._repository.load(connection, self.scope_id)
            source = graph.nodes.get(event.node_id)
            if source is None or source.kind != "source" or source.revision != event.revision:
                raise SourceLifecycleError("source-revision-mismatch")
            payload = event.model_dump(mode="json")
            if source.event is not None:
                previous_sequence = source.event["sequence"]
                if type(previous_sequence) is not int:
                    raise SourceLifecycleError("invalid-stored-event")
                if event.sequence < previous_sequence or (
                    event.sequence == previous_sequence and source.event != payload
                ):
                    raise SourceLifecycleError("event-sequence-conflict")
            source.event = payload
            source.available = event.available
            # Commit the desired state first. After any native write failure,
            # the same event remains accepted and can resume after reopening.
            await self._persist_targets(graph)
            await self._sync_memory(graph, context.artifacts.memory, reason=event.reason)
            return sorted(node_id for node_id, node in graph.nodes.items() if node.available)

    async def resolve(
        self, node_id: str, *, purpose: Literal["generation", "audit"]
    ) -> SourceRef | MemoryCitation | ArtifactRef:
        _identifier(node_id)
        if purpose not in ("generation", "audit"):
            raise SourceLifecycleError("unknown-purpose")
        async with self._runtime._scope_operation(self.scope_id), self._runtime._locked(self.scope_id):
            async with self._database.transaction() as connection:
                graph = await self._repository.load(connection, self.scope_id)
            node = graph.nodes.get(node_id)
            if node is None:
                raise SourceLifecycleError("unknown-node")
            if purpose == "generation" and not node.available:
                raise SourceLifecycleError("unavailable-node")
            return node.reference

    async def _persist_targets(self, graph: StoredLifecycleGraph) -> None:
        _refresh_availability(graph)
        async with self._database.transaction() as connection:
            await self._repository.save(connection, self.scope_id, graph)

    async def _sync_memory(self, graph: StoredLifecycleGraph, service: MemoryService, *, reason: str) -> None:
        targets: dict[tuple[str, str, str], tuple[MemoryCitation, bool]] = {}
        for node in graph.nodes.values():
            if node.kind == "memory" and isinstance(node.reference, MemoryCitation):
                ref = node.reference
                key = (ref.memory_ref.artifact_id, ref.entry_id, ref.entry_version_id)
                previous = targets.get(key)
                targets[key] = (ref, node.available or (previous is not None and previous[1]))
        heads: dict[str, Memory] = {}
        for (memory_id, entry_id, version), (citation, available) in targets.items():
            current = heads.get(memory_id)
            if current is None:
                current = await service.head(memory_id)
            manifest = next((item for item in current.content.manifest.entries if item.entry_id == entry_id), None)
            if manifest is None or manifest.entry_version_id != version:
                raise SourceLifecycleError("bound-memory-body-changed")
            target_state = "active" if available else "inactive"
            if manifest.state != target_state:
                entry = await service.validate_citation(citation)
                if available:
                    current = await service.reactivate(current, entries=(entry,), reason=reason)
                else:
                    current = await service.forget(current, entries=(entry,), reason=reason)
            heads[memory_id] = current


class SourceLifecycleApplication:
    def __init__(self, runtime: BuiltinRuntime, database: AsyncDatabase | None) -> None:
        self._runtime = runtime
        self._database = database

    def for_scope(self, scope_id: str) -> ScopedSourceLifecycle:
        if self._database is None:
            raise SourceLifecycleError("lifecycle-storage-unavailable")
        return ScopedSourceLifecycle(self._runtime, self._database, scope_id)


def _identifier(value: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise SourceLifecycleError("invalid-node-id")


def _parents(values: tuple[str, ...]) -> tuple[str, ...]:
    if not isinstance(values, (tuple, list)) or not values:
        raise SourceLifecycleError("empty-parents")
    for value in values:
        _identifier(value)
    if len(set(values)) != len(values):
        raise SourceLifecycleError("duplicate-parents")
    return tuple(values)


def _policy(value: str) -> Literal["all", "any"]:
    if value == "all":
        return "all"
    if value == "any":
        return "any"
    raise SourceLifecycleError("invalid-policy")


def _refresh_availability(graph: StoredLifecycleGraph) -> None:
    complete: set[str] = set()
    visiting: set[str] = set()

    def visit(node_id: str) -> bool:
        if node_id in visiting or node_id not in graph.nodes:
            raise SourceLifecycleError("invalid-dependency-graph")
        node = graph.nodes[node_id]
        if node_id not in complete:
            visiting.add(node_id)
            if node.kind != "source":
                parents = tuple(visit(parent) for parent in node.parents)
                node.available = all(parents) if node.policy == "all" else any(parents)
            visiting.remove(node_id)
            complete.add(node_id)
        return node.available

    for node_id in graph.nodes:
        visit(node_id)


__all__ = ["SourceLifecycleApplication", "SourceLifecycleError", "SourceLifecycleEvent"]
