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

"""Durable lifecycle targets and Topic retrieval eligibility."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue
from sqlalchemy import Table, insert, select, update
from sqlalchemy.ext.asyncio import AsyncConnection
from sqlalchemy.sql import ColumnElement

from powercontext.artifacts import ArtifactRef, MemoryCitation
from powercontext.builtin.persistence.codec import dump_model, load_model
from powercontext.builtin.persistence.tables import SOURCE_LIFECYCLE_GRAPHS_TABLE, SOURCE_LIFECYCLE_TOPICS_TABLE
from powercontext.sources import SourceRef


class StoredLifecycleNode(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["source", "memory", "topic"]
    reference: SourceRef | MemoryCitation | ArtifactRef
    revision: int | None = None
    parents: tuple[str, ...] = ()
    policy: Literal["all", "any"] | None = None
    available: bool = True
    event: dict[str, JsonValue] | None = None


class StoredLifecycleGraph(BaseModel):
    model_config = ConfigDict(extra="forbid")

    nodes: dict[str, StoredLifecycleNode] = Field(default_factory=dict)


class SourceLifecycleRepository:
    async def load(self, connection: AsyncConnection, scope_id: str) -> StoredLifecycleGraph:
        table = SOURCE_LIFECYCLE_GRAPHS_TABLE
        payload = await connection.scalar(select(table.c.payload).where(table.c.scope_id == scope_id))
        if payload is None:
            return StoredLifecycleGraph()
        return load_model(StoredLifecycleGraph, payload, kind="source-lifecycle", name=scope_id)

    async def save(self, connection: AsyncConnection, scope_id: str, graph: StoredLifecycleGraph) -> None:
        table = SOURCE_LIFECYCLE_GRAPHS_TABLE
        payload = dump_model(graph, kind="source-lifecycle", name=scope_id)
        present = await connection.scalar(select(table.c.scope_id).where(table.c.scope_id == scope_id))
        if present is None:
            await connection.execute(insert(table).values(scope_id=scope_id, payload=payload))
        else:
            await connection.execute(update(table).where(table.c.scope_id == scope_id).values(payload=payload))
        # Multiple graph nodes may name the same Topic; any available binding
        # independently supports its unchanged body.
        topics: dict[tuple[str, int], bool] = {}
        for node in graph.nodes.values():
            if node.kind == "topic" and isinstance(node.reference, ArtifactRef):
                key = (node.reference.artifact_id, node.reference.revision)
                topics[key] = topics.get(key, False) or node.available
        visibility = SOURCE_LIFECYCLE_TOPICS_TABLE
        for (artifact_id, revision), available in topics.items():
            identity = (
                visibility.c.scope_id == scope_id,
                visibility.c.artifact_id == artifact_id,
                visibility.c.revision == revision,
            )
            present = await connection.scalar(select(visibility.c.artifact_id).where(*identity))
            if present is None:
                await connection.execute(
                    insert(visibility).values(
                        scope_id=scope_id, artifact_id=artifact_id, revision=revision, available=available
                    )
                )
            else:
                await connection.execute(update(visibility).where(*identity).values(available=available))


def topic_lifecycle_predicate(table: Table) -> ColumnElement[bool]:
    visibility = SOURCE_LIFECYCLE_TOPICS_TABLE
    return (
        ~select(visibility.c.artifact_id)
        .where(
            visibility.c.scope_id == table.c.scope_id,
            visibility.c.artifact_id == table.c.artifact_id,
            visibility.c.revision == table.c.revision,
            visibility.c.available.is_(False),
        )
        .correlate(table)
        .exists()
    )


def topic_lifecycle_sql(alias: str) -> str:
    """Build eligibility with a bound scope and fixed internal SQL aliases."""

    return (
        f"({alias}.artifact_id, {alias}.revision) NOT IN "  # noqa: S608 - fixed internal aliases only
        "(SELECT lifecycle.artifact_id, lifecycle.revision "
        "FROM pc_source_lifecycle_topics AS lifecycle "
        "WHERE lifecycle.scope_id = :scope_id AND lifecycle.available = 0)"
    )
