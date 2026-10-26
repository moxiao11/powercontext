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

"""Capture immutable Pi v3 branch history with durable incremental progress."""

from __future__ import annotations

import asyncio
import hashlib
import io
import json
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, NoReturn, cast

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from powercontext.sources.connectors import ConnectorRunCompletion, ConnectorRunSession, ConnectorRunStatus
from powercontext.sources.definitions import AdapterSourceDefinition, SourceDefinition
from powercontext.sources.models import Source, SourceMaterialization
from powercontext.sources.projections import TEXT_EVIDENCE_PROJECTION_KEY, TextEvidence


class PiSessionInput(BaseModel):
    """An offline Pi session and an optional branch endpoint."""

    content: bytes
    leaf_id: str | None = None


class PiEventInput(BaseModel):
    """One visible event, including its complete original JSON record."""

    session_id: str
    event_id: str
    parent_id: str | None
    event_type: str
    role: str
    content: str
    record: dict[str, JsonValue]


class PiEventSource(Source):
    """An immutable captured event rather than a compacted model context."""

    session_id: str
    event_id: str
    parent_id: str | None
    event_type: str
    role: str
    content: str
    record: dict[str, JsonValue]


def _required_string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        message = f"Pi {field} must be a non-empty string"
        raise ValueError(message)
    return value


def _compact_json(value: JsonValue) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _event_identity(session_id: str, event_id: str) -> str:
    _required_string(session_id, "session id")
    _required_string(event_id, "event id")
    # Hash the framed pair so arbitrary Unicode IDs remain bounded and delimiter-safe.
    return "pi:" + hashlib.sha256(_compact_json([session_id, event_id]).encode("utf-8")).hexdigest()


def _visible_text(content: JsonValue, *, tool_calls: bool = False) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "text" and isinstance(block.get("text"), str):
            parts.append(cast(str, block["text"]))
        elif tool_calls and block.get("type") == "toolCall":
            name = _required_string(block.get("name"), "tool name")
            call_id = _required_string(block.get("id"), "tool call id")
            arguments = _compact_json(block.get("arguments", {}))
            parts.append(f"[tool_call {name} {call_id}] {arguments}")
    return "\n".join(parts)


def _message_text(record: dict[str, JsonValue]) -> tuple[str, str]:
    message = record.get("message")
    if not isinstance(message, dict):
        detail = "Pi message must be a JSON object"
        raise ValueError(detail)  # noqa: TRY004 -- Invalid archive data must raise ValueError.
    role = _required_string(message.get("role"), "message role")
    if role == "bashExecution":
        command = message.get("command", "")
        output = message.get("output", "")
        if not isinstance(command, str) or not isinstance(output, str):
            detail = "Pi bash command and output must be strings"
            raise ValueError(detail)
        body = f"$ {command}\n{output}" if command.strip() or output.strip() else ""
    else:
        body = _visible_text(message.get("content"), tool_calls=True)
        if role == "toolResult" and body.strip():
            name = _required_string(message.get("toolName"), "tool result name")
            call_id = _required_string(message.get("toolCallId"), "tool result call id")
            body = f"[tool_result {name} {call_id}] {body}"
    return role, body


def _parse_event(session_id: str, record: dict[str, JsonValue]) -> PiEventInput | None:
    event_id = _required_string(record.get("id"), "event id")
    event_type = _required_string(record.get("type"), "event type")
    if "parentId" not in record:
        message = "Pi event must declare parentId, including null for a root"
        raise ValueError(message)
    parent_id = record["parentId"]
    if parent_id is not None:
        parent_id = _required_string(parent_id, "parent id")
    if event_type == "message":
        role, body = _message_text(record)
    elif event_type in {"compaction", "branch_summary"}:
        role = event_type
        body = _visible_text(record.get("summary"))
    elif event_type == "custom_message":
        role = "custom"
        body = _visible_text(record.get("content"))
    else:
        return None
    if not body.strip():
        return None
    return PiEventInput(
        session_id=session_id,
        event_id=event_id,
        parent_id=parent_id,
        event_type=event_type,
        role=role,
        content=f"{role}: {body}",
        record=record,
    )


def _reject_nonfinite(value: str) -> NoReturn:
    message = f"Pi JSON must not contain non-finite number {value}"
    raise ValueError(message)


def _read_records(content: bytes) -> Iterator[dict[str, JsonValue]]:
    for line_number, line in enumerate(io.StringIO(content.decode("utf-8-sig"), newline=None), start=1):
        if not line.strip():
            continue
        try:
            record = json.loads(line, parse_constant=_reject_nonfinite)
        except (json.JSONDecodeError, RecursionError) as error:
            message = f"Invalid Pi JSON at line {line_number}"
            raise ValueError(message) from error
        if not isinstance(record, dict):
            message = f"Pi record at line {line_number} must be a JSON object"
            raise ValueError(message)  # noqa: TRY004 -- Invalid archive data must raise ValueError.
        yield record


@dataclass(frozen=True)
class _PiArchive:
    session_id: str
    fingerprints: dict[str, str]
    events: tuple[PiEventInput, ...]


def _parse_archive(value: PiSessionInput) -> _PiArchive:
    records = _read_records(value.content)
    header = next(records, None)
    if header is None or header.get("type") != "session" or type(header.get("version")) is not int:
        message = "Pi archive must start with a version 3 session header"
        raise ValueError(message)
    if header["version"] != 3:
        message = "Only Pi session version 3 is supported"
        raise ValueError(message)
    session_id = _required_string(header.get("id"), "session id")
    parents: dict[str, str | None] = {}
    visible: dict[str, PiEventInput] = {}
    fingerprints: dict[str, str] = {}
    last_id = None
    for record in records:
        event_id = _required_string(record.get("id"), "event id")
        event = _parse_event(session_id, record)
        parent_id = cast(str | None, record["parentId"])
        if event_id in parents or (parent_id is not None and parent_id not in parents):
            message = "Pi event IDs must be unique and parents must refer to earlier nodes"
            raise ValueError(message)
        parents[event_id] = parent_id
        fingerprints[event_id] = hashlib.sha256(_compact_json(record).encode("utf-8")).hexdigest()
        if event is not None:
            visible[event_id] = event
        last_id = event_id
    leaf = value.leaf_id if value.leaf_id is not None else last_id
    if leaf is not None and leaf not in parents:
        message = "Selected Pi leaf does not exist in the archive"
        raise ValueError(message)
    branch: list[PiEventInput] = []
    while leaf is not None:
        if leaf in visible:
            branch.append(visible[leaf])
        leaf = parents[leaf]
    return _PiArchive(session_id, fingerprints, tuple(reversed(branch)))


def parse_pi_session(value: PiSessionInput) -> tuple[PiEventInput, ...]:
    """Validate every record, then return the selected branch from root to leaf."""

    return _parse_archive(value).events


class _PiEventAdapter:
    name = "pi-event"
    input_class = PiEventInput
    source_class = PiEventSource

    async def resolve(self, value: PiEventInput, /) -> PiEventSource:
        if _parse_event(value.session_id, value.record) != value:
            message = "Pi event fields must match its original record"
            raise ValueError(message)
        return PiEventSource(
            name=_event_identity(value.session_id, value.event_id),
            materialization=SourceMaterialization.CAPTURED,
            **value.model_dump(),
        )

    async def read(self, source: PiEventSource, /) -> PiEventInput:
        return PiEventInput.model_validate(source.model_dump())


class _PiEventTextEvidence:
    name = TEXT_EVIDENCE_PROJECTION_KEY.name
    version = TEXT_EVIDENCE_PROJECTION_KEY.version
    source_class = PiEventSource
    output_class: type[BaseModel] = TextEvidence

    def project(self, source: PiEventSource, /) -> TextEvidence:
        return TextEvidence(
            source_type="pi-event",
            source_id=source.name,
            content=source.content,
            metadata={
                "session_id": source.session_id,
                "event_id": source.event_id,
                "parent_id": source.parent_id,
                "event_type": source.event_type,
                "role": source.role,
            },
        )


PI_EVENT_SOURCE_DEFINITION: SourceDefinition[PiEventInput, PiEventSource, PiEventInput] = AdapterSourceDefinition(
    _PiEventAdapter(), projections=(_PiEventTextEvidence(),)
)


class _PiCheckpoint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal[1] = 1
    imported: dict[str, dict[str, str]] = Field(default_factory=dict)


class PiSessionConnector:
    """Import new visible events, leaving checkpoint commits to ConnectorLifecycle."""

    name = "pi-session-history"
    version = "1"
    source_definitions = frozenset({"pi-event"})

    def __init__(self, path: str | Path, leaf_id: str | None = None) -> None:
        self.path = Path(path)
        self.leaf_id = leaf_id

    async def run(self, session: ConnectorRunSession, /) -> ConnectorRunCompletion:
        content = await asyncio.to_thread(self.path.read_bytes)
        archive = _parse_archive(PiSessionInput(content=content, leaf_id=self.leaf_id))
        checkpoint = (
            _PiCheckpoint.model_validate(session.checkpoint) if session.checkpoint is not None else _PiCheckpoint()
        )
        checkpoint = checkpoint.model_copy(deep=True)
        imported = checkpoint.imported.setdefault(archive.session_id, {})
        # Check all previously imported branches before submitting any new event.
        for event_id, fingerprint in imported.items():
            if archive.fingerprints.get(event_id) != fingerprint:
                message = f"Previously imported Pi event {event_id!r} was changed or removed"
                raise ValueError(message)
        for event in archive.events:
            if event.event_id not in imported:
                await session.submit(_event_identity(event.session_id, event.event_id), "pi-event", event)
                imported[event.event_id] = archive.fingerprints[event.event_id]
        return ConnectorRunCompletion(status=ConnectorRunStatus.COMPLETE, checkpoint=checkpoint.model_dump(mode="json"))


__all__ = [
    "PI_EVENT_SOURCE_DEFINITION",
    "PiEventInput",
    "PiEventSource",
    "PiSessionConnector",
    "PiSessionInput",
    "parse_pi_session",
]
