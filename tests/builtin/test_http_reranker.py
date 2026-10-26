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

import json
import math

import httpx
import pytest

from powercontext.artifacts import ArtifactRef
from powercontext.builtin.artifacts.memory import HTTPMemoryReranker, MemoryEntryInput
from powercontext.builtin.artifacts.memory.models import MemoryHit
from powercontext.builtin.persistence.sqlite import SQLiteConfig
from powercontext.builtin.runtime import BuiltinConfig, open_builtin_contexts


def _candidates(count: int) -> tuple[MemoryHit, ...]:
    return tuple(
        MemoryHit(
            memory_ref=ArtifactRef(family="memory", artifact_id="memory", revision=1),
            entry_id=f"entry-{index}",
            entry_version_id=f"version-{index}",
            text="identical text" if index % 2 else f"candidate {index}",
            score=1 / index,
            matched_by=("fts",),
        )
        for index in range(1, count + 1)
    )


@pytest.mark.parametrize("count,batch_size,limit", [(1, 1, 1), (9, 3, 4), (10, 4, 10), (173, 7, 10)])
async def test_global_selection_covers_every_rank_and_keeps_original_candidates(
    count: int, batch_size: int, limit: int
) -> None:
    seen: list[int] = []
    candidates = _candidates(count)
    original = tuple(candidate.model_dump() for candidate in candidates)
    scores = {rank: (rank % 5) - 2 for rank in range(1, count + 1)}

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["query"] == "查询"
        assert 1 <= len(body["candidates"]) <= batch_size
        ranks = [item["rank"] for item in body["candidates"]]
        for item in body["candidates"]:
            assert item["text"] == candidates[item["rank"] - 1].text
        seen.extend(ranks)
        return httpx.Response(200, json={"scores": [{"rank": rank, "score": scores[rank]} for rank in reversed(ranks)]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        reranker = HTTPMemoryReranker(
            "https://score.invalid", client=client, batch_size=batch_size, policy_id="test-policy"
        )
        decision = await reranker.rerank("查询", candidates, limit)
        assert not client.is_closed and reranker.policy_id == "test-policy"
    assert decision.selected_ranks == tuple(sorted(scores, key=lambda rank: (-scores[rank], rank))[:limit])
    assert decision.usage.requests == math.ceil(count / batch_size)
    assert sorted(seen) == list(range(1, count + 1))
    assert tuple(candidate.model_dump() for candidate in candidates) == original


@pytest.mark.parametrize(
    "payload",
    [
        None,
        [],
        {},
        {"scores": None},
        {"scores": {}},
        {"scores": []},
        {"scores": [{"rank": True, "score": 0.1}]},
        {"scores": [{"rank": 1.0, "score": 0.1}]},
        {"scores": [{"rank": "1", "score": 0.1}]},
        {"scores": [{"rank": 1, "score": True}]},
        {"scores": [{"rank": 1, "score": "0.1"}]},
        {"scores": [{"rank": 1, "score": None}]},
        {"scores": [{"rank": 1, "score": float("-inf")}]},
    ],
)
async def test_response_schema_rejects_coercion_and_missing_scores(payload: object) -> None:
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, content=json.dumps(payload).encode())

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ValueError):
            await HTTPMemoryReranker("https://score.invalid", client=client).rerank("q", _candidates(1), 1)
    assert len(seen) == 1


@pytest.mark.parametrize(
    "body",
    [
        b"not JSON",
        b'{"scores":[],"scores":[{"rank":1,"score":0.5}]}',
        b'{"scores":[{"rank":1,"score":0.2,"score":0.9}]}',
    ],
)
async def test_malformed_and_ambiguous_json_is_rejected(body: bytes) -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _request: httpx.Response(200, content=body))
    ) as client:
        with pytest.raises(ValueError):
            await HTTPMemoryReranker("https://score.invalid", client=client).rerank("q", _candidates(1), 1)


@pytest.mark.parametrize("status", [301, 400, 500])
async def test_non_success_status_propagates_without_redirects(status: int) -> None:
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(status, headers={"Location": "https://other.invalid"}, content=b"invalid JSON")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=True) as client:
        with pytest.raises(httpx.HTTPStatusError) as error:
            await HTTPMemoryReranker("https://score.invalid", client=client).rerank("q", _candidates(1), 1)
        assert error.value.response.status_code == status
    assert len(seen) == 1


@pytest.mark.parametrize("batch_size", [0, -1, True, 1.5, "2"])
async def test_invalid_batch_size_fails_at_construction(batch_size: int) -> None:
    async with httpx.AsyncClient() as client:
        with pytest.raises(ValueError):
            HTTPMemoryReranker("https://score.invalid", client=client, batch_size=batch_size)


@pytest.mark.parametrize("limit", [0, -1, 3, True, 1.5])
async def test_invalid_limit_does_not_send_requests(limit: int) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        pytest.fail("Invalid bounds must fail before HTTP requests")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ValueError):
            await HTTPMemoryReranker("https://score.invalid", client=client).rerank("q", _candidates(2), limit)


async def test_native_search_maps_later_batches_to_original_memory_versions() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        batch = json.loads(request.content)["candidates"]
        return httpx.Response(200, json={"scores": [{"rank": item["rank"], "score": item["rank"]} for item in batch]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        reranker = HTTPMemoryReranker("https://score.invalid", client=client, batch_size=7)
        async with open_builtin_contexts(BuiltinConfig(database=SQLiteConfig()), memory_reranker=reranker) as contexts:
            service = (await contexts.get("http-scoring")).artifacts.memory
            memory = await service.remember(
                memory=None,
                entries=tuple(
                    MemoryEntryInput(kind="fact", text=f"Project fact number {index}") for index in range(18)
                ),
                mode="append",
            )
            assert memory is not None
            result = await service.search("project", memories=(memory,), limit=4, mode="fts")
            assert result.rerank is not None
            trace = result.rerank
            assert trace.usage.requests == 3
            assert trace.selected_ranks == (18, 17, 16, 15)
            for hit, rank in zip(result.hits, trace.selected_ranks, strict=True):
                assert hit == trace.candidate_hits[rank - 1]
