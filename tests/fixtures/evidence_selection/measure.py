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

"""Run query-only inputs through real Memory; this process never reads gold."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from powercontext.artifacts import MemoryCitation
from powercontext.builtin.artifacts.memory import MemoryCandidateRequest, MemoryEntryInput, MemoryHit
from powercontext.builtin.persistence.sqlite import SQLiteConfig
from powercontext.builtin.runtime import (
    BuiltinConfig,
    CaptureSource,
    GetMemoryEntryRequest,
    PrepareContextRequest,
    open_builtin_runtime,
)
from powercontext.builtin.runtime.prepared_context import PreparedContextBuilder, PreparedMemoryCandidates
from powercontext.builtin.scope import ScopeDraft
from powercontext.builtin.sources import ContentSource


class LiteralPipeline:
    async def extract(self, request: MemoryCandidateRequest, /):
        return tuple(
            MemoryEntryInput(kind="document", text=source.content, sources=(source,))
            for source in request.sources
            if isinstance(source, ContentSource)
        )


async def measure(inputs):  # noqa: C901 - verify native storage, citations and wire output together
    observations = []
    async with open_builtin_runtime(
        BuiltinConfig(database=SQLiteConfig()), candidate_pipeline=LiteralPipeline()
    ) as runtime:
        assert runtime.scopes is not None
        for number, case in enumerate(inputs["cases"], start=1):
            scope = await runtime.scopes.create(
                ScopeDraft(
                    title="Evidence measurement",
                    summary="Literal abstracts",
                    idempotency_key="quality-" + case["case_id"],
                )
            )
            sid = scope.scope_id
            memory = runtime.memory.for_scope(sid)
            texts = {document["text"].strip(): document["id"] for document in case["documents"]}
            for document in case["documents"]:
                await runtime.sources.for_scope(sid).capture(
                    CaptureSource(source_id="document-" + document["id"], content=document["text"], metadata={})
                )
            while (await memory.flush()).processed:
                pass
            page = await memory.list()
            assert page.memory_ref is not None
            entries = {item.entry.text: item.entry for item in page.entries}
            assert set(entries) == set(texts)
            hits = tuple(
                MemoryHit(
                    memory_ref=page.memory_ref,
                    entry_id=entries[document["text"].strip()].entry_id,
                    entry_version_id=entries[document["text"].strip()].entry_version_id,
                    text=document["text"].strip(),
                    score=1.0,
                    matched_by=("fts",),
                )
                for document in case["documents"]
            )
            groups = (PreparedMemoryCandidates(scope_id=sid, memory_ref=page.memory_ref, hits=hits),)
            citations = {
                texts[hit.text]: {
                    "scope_id": sid,
                    "memory_ref": hit.memory_ref.model_dump(mode="json"),
                    "entry_id": hit.entry_id,
                    "entry_version_id": hit.entry_version_id,
                }
                for hit in hits
            }
            for budget in inputs["budgets"]:
                for enabled in (False, True):
                    build = PreparedContextBuilder().build_scopes_result(
                        request=PrepareContextRequest(
                            query=case["query"], max_bytes=budget, evidence_selection=enabled
                        ),
                        current_scope_id=sid,
                        memory_candidates=groups,
                    )
                    body = build.context.content or ""
                    assert build.context.content_bytes == len(body.encode()) <= budget
                    fragments = []
                    if enabled:
                        items = json.loads(body.splitlines()[-2])["items"] if body else []
                        assert len(items) == len(build.fragments) == len(build.origins)
                        for item, fragment, origin in zip(items, build.fragments, build.origins, strict=True):
                            address = fragment.address
                            citation = MemoryCitation(
                                memory_ref=address.memory.artifact,
                                entry_id=address.entry_id,
                                entry_version_id=address.entry_version_id,
                            )
                            original = (await memory.get(GetMemoryEntryRequest(citation=citation))).entry.text
                            assert address.memory.scope_id == sid and origin == address
                            assert type(fragment.start) is int and type(fragment.end) is int
                            assert 0 <= fragment.start < fragment.end <= len(original)
                            assert original[fragment.start : fragment.end] == fragment.text == item["content"]
                            doc_id = texts[original]
                            assert item["citation"] == citations[doc_id]
                            assert (item["start"], item["end"]) == (fragment.start, fragment.end)
                            fragments.append({
                                "document_id": doc_id,
                                "start": fragment.start,
                                "end": fragment.end,
                                "text": fragment.text,
                            })
                    elif body:
                        originals = {hit.entry_id: hit.text for hit in hits}
                        for item in json.loads(body.splitlines()[-2])["items"]:
                            original = originals[item["citation"]["entry_id"]]
                            content = item["content"]
                            if item["truncated"] and content.endswith("…"):
                                content = content[:-1]
                            assert original.startswith(content)
                            fragments.append({
                                "document_id": texts[original],
                                "start": 0,
                                "end": len(content),
                                "text": content,
                            })
                    observations.append({
                        "case_id": case["case_id"],
                        "budget": budget,
                        "selection": enabled,
                        "bytes": len(body.encode()),
                        "content": body,
                        "fragments": fragments,
                        "citations": citations,
                    })
            print(f"completed {number}/{len(inputs['cases'])}", file=sys.stderr, flush=True)
    return observations


if __name__ == "__main__":
    inputs = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    print(json.dumps(asyncio.run(measure(inputs)), ensure_ascii=False))
