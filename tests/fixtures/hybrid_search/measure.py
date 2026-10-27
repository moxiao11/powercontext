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

"""Measure full native searches against frozen SQL; no relevance labels are read."""

from __future__ import annotations

import asyncio
import hashlib
import json
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from frozen_memory_index import OceanBaseMemoryFTSIndex, OceanBaseMemoryVectorIndex
from sqlalchemy import Engine, event

from powercontext.builtin.artifacts.memory import EmbeddingProfile, MemoryEntryInput
from powercontext.builtin.artifacts.memory.service import MemoryService
from powercontext.builtin.inference import EmbeddingResult
from powercontext.builtin.persistence.memory import RelationalMemoryBackend
from powercontext.builtin.persistence.memory_index import CompositeMemoryIndex
from powercontext.builtin.persistence.seekdb import SeekDBConfig
from powercontext.builtin.runtime import BuiltinConfig, open_builtin_contexts

PROFILE = EmbeddingProfile(profile_id="scifact-local-minilm-384", model="all-MiniLM-L6-v2", dimension=384)


class FixedEmbeddings:
    profile = PROFILE

    def __init__(self, inputs):
        self.vectors = {
            " ".join(item["text"].split()): tuple(item["vector"]) for item in inputs["documents"] + inputs["queries"]
        }

    async def embed(self, texts, /):
        return EmbeddingResult(vectors=tuple(self.vectors[" ".join(text.split())] for text in texts))


async def measure(inputs):
    model = FixedEmbeddings(inputs)
    observations = []
    first_plan = None
    statements = []

    def record(_connection, _cursor, statement, parameters, _context, _executemany):
        if "AGAINST" in statement.upper() or "l2_distance" in statement.lower():
            statements.append((statement, parameters))

    path = Path(tempfile.mkdtemp(prefix="hybrid-measure-")) / "db"
    async with open_builtin_contexts(
        BuiltinConfig(database=SeekDBConfig(path=path)), embedding_model=model
    ) as contexts:
        for scope in ("quality-a", "quality-b", "quality-c"):
            memory = (await contexts.get(scope)).artifacts.memory
            head = await memory.remember(
                memory=None,
                mode="append",
                entries=tuple(
                    MemoryEntryInput(kind="document", text=document["text"]) for document in inputs["documents"]
                ),
            )
            assert head is not None
            text_ids = {document["text"].strip(): document["id"] for document in inputs["documents"]}
            entries = {entry.entry_id: entry for entry in await memory.entries(head)}
            assert len(entries) == len(inputs["documents"]) == 173
            baseline = MemoryService(
                backend=RelationalMemoryBackend(
                    database=contexts.database,
                    scope_id=scope,
                    artifacts=contexts.repositories.artifacts,
                    index=CompositeMemoryIndex(OceanBaseMemoryFTSIndex(), OceanBaseMemoryVectorIndex(PROFILE)),
                ),
                embedding_model=model,
            )
            for service in (memory, baseline):
                await service.search(inputs["queries"][0]["text"], memories=(head,), mode="hybrid", limit=10)
            for number, query in enumerate(inputs["queries"]):
                paired: dict[str, dict[str, Any]] = {}
                order = (("candidate", memory), ("frozen", baseline))
                if number % 2:
                    order = tuple(reversed(order))
                for name, service in order:
                    statements.clear()
                    event.listen(Engine, "before_cursor_execute", record)
                    try:
                        start = time.perf_counter()
                        result = await service.search(query["text"], memories=(head,), mode="hybrid", limit=10)
                        milliseconds = (time.perf_counter() - start) * 1000
                    finally:
                        event.remove(Engine, "before_cursor_execute", record)
                    assert len(statements) == (1 if name == "candidate" else 2)
                    if name == "candidate" and first_plan is None:
                        statement, parameters = statements[0]
                        async with contexts.database.transaction() as connection:
                            first_plan = "\n".join(
                                str(row[0])
                                for row in (await connection.exec_driver_sql("EXPLAIN " + statement, parameters))
                            )
                        assert "TEXT RETRIEVAL SCAN" in first_plan and "VECTOR INDEX" in first_plan
                    hits = []
                    seen = set()
                    for hit in result.hits:
                        original = entries[hit.entry_id]
                        assert hit.memory_ref == head.as_ref()
                        assert hit.entry_version_id == original.entry_version_id
                        assert hit.text == original.text
                        assert hit.matched_by and set(hit.matched_by) <= {"fts", "vector"}
                        assert (hit.entry_id, hit.entry_version_id) not in seen
                        seen.add((hit.entry_id, hit.entry_version_id))
                        hits.append({
                            "document_id": text_ids[hit.text],
                            "memory_ref": hit.memory_ref.model_dump(),
                            "entry_id": hit.entry_id,
                            "entry_version_id": hit.entry_version_id,
                            "text": hit.text,
                            "matched_by": list(hit.matched_by),
                        })
                    paired[name] = {"latency_ms": milliseconds, "candidate_statements": len(statements), "hits": hits}
                repeated = await memory.search(query["text"], memories=(head,), mode="hybrid", limit=10)
                assert [(hit.entry_id, hit.entry_version_id) for hit in repeated.hits] == [
                    (hit["entry_id"], hit["entry_version_id"]) for hit in paired["candidate"]["hits"]
                ]
                observations.append({"scope": scope, "query_id": query["id"], **paired})
                print(f"completed {len(observations)}/60", file=sys.stderr, flush=True)
    return {
        "source": inputs["source"],
        "embedding": inputs["embedding"],
        "profile": PROFILE.model_dump(),
        "explain": first_plan,
        "frozen_index_sha256": hashlib.sha256(
            Path(__file__).with_name("frozen_memory_index.py").read_bytes()
        ).hexdigest(),
        "rows": observations,
    }


if __name__ == "__main__":
    print(
        json.dumps(asyncio.run(measure(json.loads(Path(sys.argv[1]).read_text(encoding="utf-8")))), ensure_ascii=False)
    )
