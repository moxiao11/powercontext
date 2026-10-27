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
from sqlalchemy import event, insert, select, update

from powercontext.builtin.persistence.cursors import SourceCursorRepository
from powercontext.builtin.persistence.processing_intents import ArtifactProcessingIntentRepository
from powercontext.builtin.persistence.supervision import ArtifactProcessingLeaseRepository
from powercontext.builtin.persistence.tables import SOURCE_JOURNAL_HEADS_TABLE
from powercontext.builtin.runtime import artifact_processing as processing
from powercontext.builtin.runtime.artifact_processing import ArtifactProcessingBinding, ArtifactProcessingSupervisor
from powercontext.builtin.runtime.processing_discovery import SourceProcessingPendingProvider
from powercontext.builtin.sources.journal import SourceCursor
from tests.builtin.runtime.test_processing_scheduler import _intent, _Launcher, _profile, _wait

_BINDING = "count-memory"


def test_count_discovery_resumes_after_idle_and_visits_every_page(tmp_path, monkeypatch):
    monkeypatch.setattr(processing, "_DISCOVERY_PAGE_SIZE", 2)

    async def scenario():
        async with _profile(tmp_path, "count-pages") as profile:

            async def consume(work):
                async with profile.database.transaction() as connection:
                    head = await connection.scalar(
                        select(SOURCE_JOURNAL_HEADS_TABLE.c.position).where(
                            SOURCE_JOURNAL_HEADS_TABLE.c.scope_id == work.scope_id
                        )
                    )
                    await SourceCursorRepository().save(
                        connection, work.scope_id, _BINDING, SourceCursor(sequence=head), expected_generation=None
                    )

            launcher = _Launcher(profile.database, on_work=consume)
            async with ArtifactProcessingSupervisor(
                database=profile.database,
                bindings=(
                    ArtifactProcessingBinding(
                        _BINDING,
                        "memory",
                        launcher,
                        pending_provider=SourceProcessingPendingProvider(
                            profile.database, _BINDING, "memory", source_count_threshold=3
                        ),
                        reconcile_continuously=True,
                    ),
                ),
                lease_mode="single-process",
                oceanbase_tick_seconds=0.01,
            ) as supervisor:
                state = supervisor._families[_BINDING]
                await _wait(lambda: state.reconcile_complete and not state.discovery_pending)
                # No notification: discovery must wake again even with no time schedule.
                async with profile.database.transaction() as connection:
                    await connection.execute(
                        insert(SOURCE_JOURNAL_HEADS_TABLE),
                        [{"scope_id": scope, "position": 3} for scope in ("a", "b", "c", "d", "e")],
                    )
                await _wait(lambda: supervisor.family_status["memory"]["completed"] == 5)
                assert sorted(work.scope_id for work in launcher.assignments) == ["a", "b", "c", "d", "e"]
                await asyncio.sleep(0.05)
                assert len(launcher.assignments) == 5

    asyncio.run(scenario())


def test_count_uses_success_cursor_and_retains_accepted_request_across_threshold_changes(tmp_path):
    async def scenario():
        async with _profile(tmp_path, "count-cursor") as profile:
            database = profile.database
            intents = ArtifactProcessingIntentRepository()
            cursors = SourceCursorRepository()
            async with database.transaction() as connection:
                term = await ArtifactProcessingLeaseRepository().start_single_process_term(connection, "count-test")
                await connection.execute(insert(SOURCE_JOURNAL_HEADS_TABLE).values(scope_id="a", position=10))
                cursor = await cursors.save(
                    connection, "a", _BINDING, SourceCursor(sequence=8), expected_generation=None
                )
            fence = term.fence("single-process")
            provider = SourceProcessingPendingProvider(database, _BINDING, "memory", source_count_threshold=3)
            await provider.reconcile(None, 2, fence=fence)
            assert (await _intent(database, _BINDING, "a")).requested_generation == 0
            async with database.transaction() as connection:
                await connection.execute(update(SOURCE_JOURNAL_HEADS_TABLE).values(position=11))
            await provider.reconcile(None, 2, fence=fence)
            await provider.reconcile(None, 2, fence=fence)
            assert (await _intent(database, _BINDING, "a")).requested_generation == 1
            # Changing admission policy never retracts an already accepted invocation.
            for threshold in (None, 100):
                changed = SourceProcessingPendingProvider(
                    database, _BINDING, "memory", source_count_threshold=threshold
                )
                await changed.reconcile(None, 2, fence=fence)
                row = await _intent(database, _BINDING, "a")
                assert (row.requested_generation, row.handled_generation) == (1, 0)
            async with database.transaction() as connection:
                await cursors.save(
                    connection, "a", _BINDING, SourceCursor(sequence=9), expected_generation=cursor.generation
                )
                await intents.acknowledge(connection, "a", _BINDING, 1)
            await provider.reconcile(None, 2, fence=fence)
            assert (await _intent(database, _BINDING, "a")).requested_generation == 1
            async with database.transaction() as connection:
                await connection.execute(update(SOURCE_JOURNAL_HEADS_TABLE).values(position=12))
            await provider.reconcile(None, 2, fence=fence)
            assert (await _intent(database, _BINDING, "a")).requested_generation == 2

    asyncio.run(scenario())


def test_count_admission_commit_failure_rolls_back_the_whole_page(tmp_path):
    class CommitFailure(Exception):
        pass

    async def scenario():
        async with _profile(tmp_path, "count-rollback") as profile:
            database = profile.database
            async with database.transaction() as connection:
                term = await ArtifactProcessingLeaseRepository().start_single_process_term(connection, "count-test")
                await connection.execute(
                    insert(SOURCE_JOURNAL_HEADS_TABLE),
                    [{"scope_id": scope, "position": 3} for scope in ("a", "b")],
                )
            provider = SourceProcessingPendingProvider(database, _BINDING, "memory", source_count_threshold=3)

            def fail_commit(connection):
                raise CommitFailure

            event.listen(database.engine.sync_engine, "commit", fail_commit, once=True)
            with pytest.raises(CommitFailure):
                await provider.reconcile(None, 2, fence=term.fence("single-process"))
            for scope in ("a", "b"):
                assert await _intent(database, _BINDING, scope) is None
            assert await provider.reconcile(None, 2, fence=term.fence("single-process")) == "b"
            for scope in ("a", "b"):
                assert (await _intent(database, _BINDING, scope)).requested_generation == 1

    asyncio.run(scenario())
