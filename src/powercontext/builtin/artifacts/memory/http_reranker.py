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

"""Strict HTTP scoring with global, identity-preserving Memory selection."""

from __future__ import annotations

import json
import math
from typing import TYPE_CHECKING, cast

from pydantic import JsonValue

from powercontext.builtin.artifacts.memory.models import MemoryHit
from powercontext.builtin.artifacts.memory.reranking import MemoryRerankDecision
from powercontext.builtin.inference import InferenceUsage

if TYPE_CHECKING:
    import httpx


def _response_object(pairs: list[tuple[str, JsonValue]]) -> dict[str, JsonValue]:
    value: dict[str, JsonValue] = {}
    for key, item in pairs:
        if key in value:
            message = "Reranking response must not contain duplicate JSON keys"
            raise ValueError(message)
        value[key] = item
    return value


def _batch_scores(payload: JsonValue, expected: set[int]) -> dict[int, int | float]:
    if not isinstance(payload, dict) or set(payload) != {"scores"} or not isinstance(payload["scores"], list):
        message = "Reranking response must contain exactly one scores array"
        raise ValueError(message)
    scores: dict[int, int | float] = {}
    for item in payload["scores"]:
        if not isinstance(item, dict) or set(item) != {"rank", "score"}:
            message = "Each reranking score must contain exactly rank and score"
            raise ValueError(message)
        rank, score = item["rank"], item["score"]
        if type(rank) is not int or rank not in expected or rank in scores:
            message = "Reranking ranks must cover this batch exactly once"
            raise ValueError(message)
        if type(score) not in {int, float} or (isinstance(score, float) and not math.isfinite(score)):
            message = "Reranking scores must be finite JSON numbers"
            raise ValueError(message)
        scores[rank] = cast(int | float, score)
    if scores.keys() != expected:
        message = "Reranking response omitted batch candidates"
        raise ValueError(message)
    return scores


class HTTPMemoryReranker:
    """Score every original rank once using the caller-owned asynchronous client."""

    def __init__(
        self,
        endpoint: str,
        *,
        client: httpx.AsyncClient,
        batch_size: int = 32,
        policy_id: str = "http-cross-encoder-v1",
    ) -> None:
        if type(batch_size) is not int or batch_size <= 0:
            message = "Reranking batch_size must be a positive integer"
            raise ValueError(message)
        self.endpoint = endpoint
        self.client = client
        self.batch_size = batch_size
        self.policy_id = policy_id

    async def rerank(self, query: str, candidates: tuple[MemoryHit, ...], limit: int, /) -> MemoryRerankDecision:
        if not candidates or type(limit) is not int or not 1 <= limit <= len(candidates):
            message = "Reranking requires candidates and a limit within the candidate count"
            raise ValueError(message)
        scores: dict[int, int | float] = {}
        requests = 0
        for start in range(0, len(candidates), self.batch_size):
            batch = [
                {"rank": start + offset + 1, "text": candidate.text}
                for offset, candidate in enumerate(candidates[start : start + self.batch_size])
            ]
            requests += 1
            response = await self.client.post(
                self.endpoint, json={"query": query, "candidates": batch}, follow_redirects=False
            )
            response.raise_for_status()
            payload = json.loads(response.content, object_pairs_hook=_response_object)
            scores.update(_batch_scores(payload, set(range(start + 1, start + len(batch) + 1))))
        selected = sorted(scores, key=lambda rank: (-scores[rank], rank))[:limit]
        return MemoryRerankDecision(selected_ranks=tuple(selected), usage=InferenceUsage(requests=requests))


__all__ = ["HTTPMemoryReranker"]
