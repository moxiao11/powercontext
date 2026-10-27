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

"""Shared in-flight embedding batches and a bounded successful-vector cache."""

from __future__ import annotations

import asyncio
import math
from collections import OrderedDict
from collections.abc import Iterable
from dataclasses import dataclass

from powercontext.builtin.inference.models import EmbeddingResult, EmbeddingVector, InferenceUsage
from powercontext.builtin.inference.protocols import EmbeddingModel


@dataclass(frozen=True, slots=True, eq=False)
class _BatchUsage:
    # Identity distinguishes separate requests even when their usage is equal.
    usage: InferenceUsage


@dataclass(frozen=True, slots=True)
class _EmbeddedText:
    vector: EmbeddingVector
    batch: _BatchUsage


class CoalescingEmbeddingModel:
    """Share embedding work among callers in one event loop.

    The cache stores vectors only; each caller is charged once for every
    distinct provider batch it waits for. A cache hit incurs no model usage.
    Cancellation detaches a caller while provider work continues for other
    callers and the cache. Failed batches can be retried immediately.
    """

    def __init__(
        self,
        model: EmbeddingModel,
        *,
        max_batch_size: int = 64,
        coalesce_ms: float = 5.0,
        cache_size: int = 1024,
    ) -> None:
        if type(max_batch_size) is not int or max_batch_size < 1:
            raise ValueError("max_batch_size must be a positive integer")  # noqa: TRY003
        if type(cache_size) is not int or cache_size < 0:
            raise ValueError("cache_size must be a nonnegative integer")  # noqa: TRY003
        if (
            isinstance(coalesce_ms, bool)
            or not isinstance(coalesce_ms, (int, float))
            or not math.isfinite(coalesce_ms)
            or coalesce_ms < 0
        ):
            raise ValueError("coalesce_ms must be finite and nonnegative")  # noqa: TRY003
        self.profile = model.profile
        self._model = model
        self._max_batch_size = max_batch_size
        self._coalesce_seconds = coalesce_ms / 1000
        self._cache_size = cache_size
        self._cache: OrderedDict[str, EmbeddingVector] = OrderedDict()
        self._inflight: dict[str, asyncio.Future[_EmbeddedText]] = {}
        self._pending: dict[str, asyncio.Future[_EmbeddedText]] = {}
        self._flush_handle: asyncio.TimerHandle | None = None
        self._tasks: set[asyncio.Task[None]] = set()

    async def embed(self, texts: tuple[str, ...], /) -> EmbeddingResult:
        """Embed texts in their original order, including duplicate positions."""

        if not texts:
            return EmbeddingResult(vectors=())
        loop = asyncio.get_running_loop()
        vectors: dict[str, EmbeddingVector] = {}
        waiting: dict[str, asyncio.Future[_EmbeddedText]] = {}
        # No await while looking up or registering work: callers in this event
        # loop see one authoritative Future per text, including running batches.
        for text in texts:
            if text in self._cache:
                vectors[text] = self._cache[text]
                self._cache.move_to_end(text)
                continue
            future = self._inflight.get(text)
            if future is None:
                future = loop.create_future()
                self._inflight[text] = future
                self._pending[text] = future
            waiting[text] = future
        if self._pending and self._flush_handle is None:
            self._flush_handle = loop.call_later(self._coalesce_seconds, self._flush)
        # Shield the whole gather so a cancelled caller cannot cancel shared
        # Futures. Observe its eventual error even if every caller detaches.
        aggregate = asyncio.gather(*waiting.values())
        aggregate.add_done_callback(_observe_completion)
        resolved = await asyncio.shield(aggregate)
        batches = {item.batch for item in resolved}
        for text, item in zip(waiting, resolved, strict=True):
            vectors[text] = item.vector
        return EmbeddingResult(
            vectors=tuple(vectors[text] for text in texts),
            usage=InferenceUsage(
                requests=sum(batch.usage.requests for batch in batches),
                input_tokens=_sum_tokens(batch.usage.input_tokens for batch in batches),
                output_tokens=_sum_tokens(batch.usage.output_tokens for batch in batches),
            ),
        )

    def _flush(self) -> None:
        pending = tuple(self._pending.items())
        self._pending.clear()
        self._flush_handle = None
        for start in range(0, len(pending), self._max_batch_size):
            task = asyncio.create_task(self._run_batch(pending[start : start + self._max_batch_size]))
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)

    async def _run_batch(self, batch: tuple[tuple[str, asyncio.Future[_EmbeddedText]], ...]) -> None:
        texts = tuple(text for text, _future in batch)
        try:
            result = await self._model.embed(texts)
            if len(result.vectors) != len(texts):
                # Validate the complete response before publishing or caching any vector.
                raise ValueError("Embedding vector count does not match the batch")  # noqa: TRY003, TRY301
        except asyncio.CancelledError:
            for _text, future in batch:
                future.cancel()
            raise
        except Exception as error:
            for _text, future in batch:
                future.set_exception(error)
        else:
            usage = _BatchUsage(result.usage)
            for (text, future), vector in zip(batch, result.vectors, strict=True):
                self._cache_vector(text, vector)
                future.set_result(_EmbeddedText(vector, usage))
        finally:
            for text, _future in batch:
                del self._inflight[text]

    def _cache_vector(self, text: str, vector: EmbeddingVector) -> None:
        if not self._cache_size:
            return
        self._cache[text] = vector
        self._cache.move_to_end(text)
        if len(self._cache) > self._cache_size:
            self._cache.popitem(last=False)


def _observe_completion(future: asyncio.Future[list[_EmbeddedText]]) -> None:
    if not future.cancelled():
        future.exception()


def _sum_tokens(values: Iterable[int | None]) -> int | None:
    counts = tuple(values)
    if not counts or any(value is None for value in counts):
        return None
    return sum(value for value in counts if value is not None)


__all__ = ["CoalescingEmbeddingModel"]
