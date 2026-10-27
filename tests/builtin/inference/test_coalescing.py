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

import pytest

from powercontext.builtin.artifacts.memory import EmbeddingProfile
from powercontext.builtin.inference import CoalescingEmbeddingModel, EmbeddingResult, InferenceUsage


class _GatedEmbedding:
    profile = EmbeddingProfile(profile_id="coalescing-test", model="offline", dimension=1)

    def __init__(self):
        self.calls = []
        self.started = asyncio.Queue()

    async def embed(self, texts):
        self.calls.append(texts)
        response = asyncio.get_running_loop().create_future()
        self.started.put_nowait((texts, response))
        return await response


def _result(texts, *, requests=1, tokens=7, output=0):
    return EmbeddingResult(
        vectors=tuple((float(len(text)),) for text in texts),
        usage=InferenceUsage(requests=requests, input_tokens=tokens, output_tokens=output),
    )


def test_late_waiter_shares_running_work_without_cache_and_survives_owner_cancellation():
    async def scenario():
        base = _GatedEmbedding()
        model = CoalescingEmbeddingModel(base, max_batch_size=2, coalesce_ms=0, cache_size=0)
        assert model.profile == base.profile
        first = asyncio.create_task(model.embed(("alpha", "beta", "alpha")))
        texts, response = await base.started.get()
        assert texts == ("alpha", "beta")
        late = asyncio.create_task(model.embed(("beta", "alpha")))
        await asyncio.sleep(0)  # Let the late caller attach before cancellation and completion.
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first
        assert not response.cancelled()
        response.set_result(_result(texts, requests=3, tokens=11, output=2))
        result = await late
        assert result.vectors == ((4.0,), (5.0,))
        assert result.usage == InferenceUsage(requests=3, input_tokens=11, output_tokens=2)
        assert base.calls == [("alpha", "beta")]
        retry = asyncio.create_task(model.embed(("alpha",)))
        texts, response = await base.started.get()
        assert texts == ("alpha",)
        response.set_result(_result(texts))
        assert (await retry).usage.requests == 1

    asyncio.run(asyncio.wait_for(scenario(), timeout=5))


@pytest.mark.parametrize("cache_size", [0, 1, 16])
def test_overlapping_running_and_new_batches_charge_each_caller_once_despite_completion_order(cache_size):
    async def scenario():
        base = _GatedEmbedding()
        model = CoalescingEmbeddingModel(base, max_batch_size=2, coalesce_ms=0, cache_size=cache_size)
        first = asyncio.create_task(model.embed(("a", "bb", "ccc", "a")))
        ab, ab_response = await base.started.get()
        c, c_response = await base.started.get()
        assert (ab, c) == (("a", "bb"), ("ccc",))
        second = asyncio.create_task(model.embed(("bb", "dddd", "ccc", "bb")))
        d, d_response = await base.started.get()
        assert d == ("dddd",)
        d_response.set_result(_result(d, requests=2, tokens=5, output=0))
        c_response.set_result(_result(c, requests=4, tokens=11, output=3))
        ab_response.set_result(_result(ab, requests=3, tokens=7, output=1))
        one, two = await asyncio.gather(first, second)
        assert one.vectors == ((1.0,), (2.0,), (3.0,), (1.0,))
        assert two.vectors == ((2.0,), (4.0,), (3.0,), (2.0,))
        assert one.usage == InferenceUsage(requests=7, input_tokens=18, output_tokens=4)
        assert two.usage == InferenceUsage(requests=9, input_tokens=23, output_tokens=4)
        assert len(base.calls) == 3
        if cache_size == 16:
            cached = await model.embed(("dddd", "a", "ccc", "bb"))
            assert cached.vectors == ((4.0,), (1.0,), (3.0,), (2.0,))
            assert cached.usage.requests == 0
            assert len(base.calls) == 3

    asyncio.run(asyncio.wait_for(scenario(), timeout=5))


@pytest.mark.parametrize("failure", ["exception", "too_few", "too_many"])
def test_failed_or_malformed_batch_can_retry_without_poisoning_independent_batch(failure):
    async def scenario():
        base = _GatedEmbedding()
        model = CoalescingEmbeddingModel(base, max_batch_size=2, coalesce_ms=0)
        mixed = asyncio.create_task(model.embed(("bad", "other", "good")))
        shared = asyncio.create_task(model.embed(("other", "bad")))
        independent = asyncio.create_task(model.embed(("good",)))
        bad, bad_response = await base.started.get()
        good, good_response = await base.started.get()
        assert (bad, good) == (("bad", "other"), ("good",))
        if failure == "exception":
            bad_response.set_exception(RuntimeError("provider unavailable"))
        else:
            bad_response.set_result(EmbeddingResult(vectors=((1.0,),) * (1 if failure == "too_few" else 3)))
        error_type = RuntimeError if failure == "exception" else ValueError
        for caller in (mixed, shared):
            with pytest.raises(error_type):
                await caller
        assert not good_response.cancelled()
        good_response.set_result(_result(good))
        assert (await independent).vectors == ((4.0,),)
        assert (await model.embed(("good",))).usage.requests == 0
        retry = asyncio.create_task(model.embed(("other", "bad")))
        texts, response = await base.started.get()
        assert texts == ("other", "bad")
        response.set_result(_result(texts))
        assert (await retry).vectors == ((5.0,), (3.0,))
        assert len(base.calls) == 3

    asyncio.run(asyncio.wait_for(scenario(), timeout=5))


def test_abandoned_failed_work_is_observed_and_can_be_retried():
    async def scenario():
        reports = []
        asyncio.get_running_loop().set_exception_handler(lambda loop, context: reports.append(context))
        base = _GatedEmbedding()
        model = CoalescingEmbeddingModel(base, coalesce_ms=0)
        abandoned = asyncio.create_task(model.embed(("abandoned",)))
        _texts, response = await base.started.get()
        abandoned.cancel()
        with pytest.raises(asyncio.CancelledError):
            await abandoned
        response.set_exception(RuntimeError("provider failed after cancellation"))
        await asyncio.sleep(0)  # Process the provider completion before the retry.
        retry = asyncio.create_task(model.embed(("abandoned",)))
        texts, response = await base.started.get()
        response.set_result(_result(texts))
        assert (await retry).vectors == ((9.0,),)
        assert (await model.embed(("abandoned",))).usage.requests == 0
        await asyncio.sleep(0)
        assert reports == []

    asyncio.run(asyncio.wait_for(scenario(), timeout=5))
