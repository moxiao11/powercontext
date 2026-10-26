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

"""Observable Pi parsing and immutable evidence boundaries."""

from __future__ import annotations

import json

import pytest
from pydantic import JsonValue

from powercontext.sources import SourceDefinitionRegistry, SourceMaterialization, TextEvidence
from powercontext.sources.pi_session import PI_EVENT_SOURCE_DEFINITION, PiSessionInput, parse_pi_session
from powercontext.sources.projections import TEXT_EVIDENCE_PROJECTION_KEY


def _input(records: list[dict[str, JsonValue]], *, session_id: str = "s", leaf: str | None = None) -> PiSessionInput:
    header: dict[str, JsonValue] = {"type": "session", "version": 3, "id": session_id}
    return PiSessionInput(
        content="\n".join(json.dumps(row, ensure_ascii=False) for row in [header, *records]).encode(), leaf_id=leaf
    )


def test_mixed_blocks_preserve_text_and_sorted_unicode_tool_arguments() -> None:
    records: list[dict[str, JsonValue]] = [
        {
            "type": "message",
            "id": "call",
            "parentId": None,
            "message": {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": " lead \u2028line "},
                    {"type": "thinking", "thinking": "PRIVATE"},
                    {"type": "image", "data": "IMAGE"},
                    {"type": "toolCall", "name": "read", "id": "c", "arguments": {"z": "杭州", "a": {"y": 2, "b": 1}}},
                    {"type": "text", "text": " tail "},
                ],
                "extra": {"retained": [True, None, 3]},
            },
        }
    ]
    event = parse_pi_session(_input(records))[0]
    assert event.content == 'assistant:  lead \u2028line \n[tool_call read c] {"a":{"b":1,"y":2},"z":"杭州"}\n tail '
    assert event.record == records[0]


def test_invisible_nodes_keep_parent_links_and_do_not_replace_older_evidence() -> None:
    records: list[dict[str, JsonValue]] = [
        {"type": "message", "id": "root", "parentId": None, "message": {"role": "user", "content": "original"}},
        {
            "type": "message",
            "id": "hidden",
            "parentId": "root",
            "message": {"role": "assistant", "content": [{"type": "thinking", "thinking": "private"}]},
        },
        {"type": "compaction", "id": "summary", "parentId": "hidden", "summary": "summary"},
        {"type": "model_change", "id": "control", "parentId": "summary"},
    ]
    events = parse_pi_session(_input(records))
    assert [event.event_id for event in events] == ["root", "summary"]
    assert [event.content for event in events] == ["user: original", "compaction: summary"]
    assert events[1].parent_id == "hidden"
    assert parse_pi_session(_input([], leaf=None)) == ()
    with pytest.raises(ValueError):
        parse_pi_session(_input([], leaf="absent"))


@pytest.mark.parametrize(
    "bad_record",
    [
        {"type": "model_change", "id": "bad"},
        {"type": "model_change", "id": "bad", "parentId": "future"},
        {"type": "model_change", "id": "root", "parentId": None},
        {"type": "model_change", "id": "", "parentId": None},
        {"type": "model_change", "id": 5, "parentId": None},
        {"type": "model_change", "id": "bad", "parentId": []},
        {"type": "message", "id": "bad", "parentId": None, "message": []},
    ],
)
def test_unselected_invalid_records_still_fail_the_whole_archive(bad_record: dict[str, JsonValue]) -> None:
    root: dict[str, JsonValue] = {
        "type": "message",
        "id": "root",
        "parentId": None,
        "message": {"role": "user", "content": "valid"},
    }
    with pytest.raises(ValueError):
        parse_pi_session(_input([root, bad_record], leaf="root"))


@pytest.mark.parametrize(
    "raw",
    [
        b'{"type":"session","version":3.0,"id":"s"}\n',
        b'{"type":"session","version":3,"id":""}\n',
        b'{"type":"session","version":3,"id":123}\n',
        b'{"type":"session","version":3,"id":"s","value":NaN}\n',
        b'{"type":"session","version":3,"id":"s"}\n{bad}\n',
    ],
)
def test_invalid_header_or_json_never_returns_partial_evidence(raw: bytes) -> None:
    with pytest.raises(ValueError):
        parse_pi_session(PiSessionInput(content=raw))


async def test_long_and_ambiguous_identity_components_remain_stable_and_distinct() -> None:
    registry = SourceDefinitionRegistry((PI_EVENT_SOURCE_DEFINITION,))
    names = set()
    for session_id, event_id in [("a:b", "c"), ("a", "b:c"), ("界" * 300, "事" * 300)]:
        event = parse_pi_session(
            _input(
                [{"type": "message", "id": event_id, "parentId": None, "message": {"role": "user", "content": "body"}}],
                session_id=session_id,
            )
        )[0]
        source = await registry.resolve(event)
        assert source.name == (await registry.resolve(event)).name
        assert len(source.name) <= 256
        assert source.materialization is SourceMaterialization.CAPTURED
        assert await registry.read(source) == event
        evidence = TextEvidence.model_validate(registry.project(source, TEXT_EVIDENCE_PROJECTION_KEY))
        assert evidence.source_id == source.name and evidence.metadata["session_id"] == session_id
        names.add(source.name)
        with pytest.raises(ValueError):
            await registry.resolve(event.model_copy(update={"content": "forged"}))
    assert len(names) == 3
