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

"""Stateless, interoperable UTF-8 context packs and prefix deltas."""

from __future__ import annotations

import base64
import hashlib
import json
import re
from dataclasses import dataclass
from typing import cast

_PACK_SCHEMA = "powercontext.context-pack.v1"
_DELTA_SCHEMA = "powercontext.context-pack-delta.v1"


class ContextPackError(ValueError):
    """Invalid context content, wire fields, or reconstruction checksums."""


def _json_bytes(value: dict[str, object]) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _validate_items(items: tuple[bytes, ...]) -> None:
    if not isinstance(items, tuple) or not all(isinstance(item, bytes) for item in items):
        message = "Context chunks must be a tuple of bytes"
        raise ContextPackError(message)
    try:
        for item in items:
            item.decode("utf-8", errors="strict")
    except UnicodeError as error:
        message = "Each context chunk must independently contain valid UTF-8"
        raise ContextPackError(message) from error


def _digest(value: object) -> str:
    if not isinstance(value, str) or re.fullmatch(r"sha256:[0-9a-f]{64}", value) is None:
        message = "Context digest must use sha256 followed by 64 lowercase hexadecimal characters"
        raise ContextPackError(message)
    return value


def _prefix(value: object) -> int:
    if type(value) is not int or value < 0:
        message = "Context prefix_items must be a non-negative integer"
        raise ContextPackError(message)
    return value


def _unique_fields(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            message = "Context JSON must not contain duplicate fields"
            raise ContextPackError(message)
        result[key] = value
    return result


def _read_wire(data: bytes, schema: str, fields: frozenset[str]) -> dict[str, object]:
    if not isinstance(data, bytes):
        message = "Context wire data must be UTF-8 bytes"
        raise ContextPackError(message)
    try:
        payload = json.loads(data.decode("utf-8", errors="strict"), object_pairs_hook=_unique_fields)
    except ContextPackError:
        raise
    except (ValueError, RecursionError) as error:
        message = "Context wire data must contain a valid UTF-8 JSON object"
        raise ContextPackError(message) from error
    if not isinstance(payload, dict) or set(payload) != fields or payload.get("schema") != schema:
        message = "Context wire schema or fields do not match the protocol"
        raise ContextPackError(message)
    return cast(dict[str, object], payload)


def _decode_items(values: object) -> tuple[bytes, ...]:
    if not isinstance(values, list):
        message = "Context wire chunks must be a Base64 string array"
        raise ContextPackError(message)
    items = []
    for value in values:
        if not isinstance(value, str):
            message = "Context wire chunks must be Base64 strings"
            raise ContextPackError(message)
        try:
            item = base64.b64decode(value, validate=True)
        except ValueError as error:
            message = "Context wire chunks must use valid standard Base64"
            raise ContextPackError(message) from error
        if base64.b64encode(item).decode("ascii") != value:
            message = "Context wire chunks must use canonical standard Base64"
            raise ContextPackError(message)
        items.append(item)
    return tuple(items)


@dataclass(frozen=True, slots=True)
class ContextPack:
    """A complete, immutable ordered tuple of independently valid UTF-8 chunks."""

    items: tuple[bytes, ...]

    def __post_init__(self) -> None:
        _validate_items(self.items)

    @classmethod
    def build(cls, items: tuple[bytes, ...]) -> ContextPack:
        return cls(items)

    @classmethod
    def from_content(cls, content: str | bytes | None, *, chunk_bytes: int = 512) -> ContextPack:
        if type(chunk_bytes) is not int or chunk_bytes <= 0:
            message = "Context chunk_bytes must be a positive integer"
            raise ContextPackError(message)
        try:
            if content is None:
                data = b""
            elif isinstance(content, str):
                data = content.encode("utf-8", errors="strict")
            elif isinstance(content, bytes):
                data = content
                data.decode("utf-8", errors="strict")
            else:
                message = "Context content must be text or UTF-8 bytes"
                raise ContextPackError(message)
        except UnicodeError as error:
            message = "Context content must be valid UTF-8"
            raise ContextPackError(message) from error
        items = []
        # Preserve line boundaries so a changing long line does not absorb a stable header.
        for line in data.splitlines(keepends=True):
            start = 0
            while start < len(line):
                end = min(start + chunk_bytes, len(line))
                while end < len(line) and line[end] & 0xC0 == 0x80:
                    end -= 1
                if end == start:
                    message = "Context chunk limit cannot hold the next UTF-8 character"
                    raise ContextPackError(message)
                items.append(line[start:end])
                start = end
        return cls.build(tuple(items))

    def _unsigned(self) -> dict[str, object]:
        return {"schema": _PACK_SCHEMA, "items": [base64.b64encode(item).decode("ascii") for item in self.items]}

    @property
    def digest(self) -> str:
        return "sha256:" + hashlib.sha256(_json_bytes(self._unsigned())).hexdigest()

    @property
    def byte_count(self) -> int:
        return len(self.to_bytes())

    def to_bytes(self) -> bytes:
        unsigned = self._unsigned()
        payload = {**unsigned, "digest": "sha256:" + hashlib.sha256(_json_bytes(unsigned)).hexdigest(), "byte_count": 0}
        while True:
            data = _json_bytes(payload)
            if len(data) == payload["byte_count"]:
                return data
            payload["byte_count"] = len(data)

    @classmethod
    def from_bytes(cls, data: bytes) -> ContextPack:
        payload = _read_wire(data, _PACK_SCHEMA, frozenset({"schema", "items", "digest", "byte_count"}))
        pack = cls.build(_decode_items(payload["items"]))
        if _digest(payload["digest"]) != pack.digest:
            message = "Context pack digest does not match its chunks"
            raise ContextPackError(message)
        count = payload["byte_count"]
        if type(count) is not int or count != pack.byte_count or count != len(data):
            message = "Context pack byte_count does not match its complete serialized size"
            raise ContextPackError(message)
        return pack


@dataclass(frozen=True, slots=True)
class ContextPackDelta:
    """A receiver can apply this value using only its serialized base pack."""

    base_digest: str
    target_digest: str
    prefix_items: int
    appended: tuple[bytes, ...]

    def __post_init__(self) -> None:
        _digest(self.base_digest)
        _digest(self.target_digest)
        _prefix(self.prefix_items)
        _validate_items(self.appended)

    @classmethod
    def between(cls, base: ContextPack, target: ContextPack) -> ContextPackDelta:
        if not isinstance(base, ContextPack) or not isinstance(target, ContextPack):
            message = "Context delta requires complete base and target packs"
            raise ContextPackError(message)
        prefix_items = 0
        for left, right in zip(base.items, target.items, strict=False):
            if left != right:
                break
            prefix_items += 1
        return cls(base.digest, target.digest, prefix_items, target.items[prefix_items:])

    @property
    def byte_count(self) -> int:
        return len(self.to_bytes())

    def to_bytes(self) -> bytes:
        return _json_bytes({
            "schema": _DELTA_SCHEMA,
            "base_digest": self.base_digest,
            "target_digest": self.target_digest,
            "prefix_items": self.prefix_items,
            "appended": [base64.b64encode(item).decode("ascii") for item in self.appended],
        })

    @classmethod
    def from_bytes(cls, data: bytes) -> ContextPackDelta:
        payload = _read_wire(
            data,
            _DELTA_SCHEMA,
            frozenset({"schema", "base_digest", "target_digest", "prefix_items", "appended"}),
        )
        return cls(
            _digest(payload["base_digest"]),
            _digest(payload["target_digest"]),
            _prefix(payload["prefix_items"]),
            _decode_items(payload["appended"]),
        )


def apply_context_pack_delta(base: ContextPack, delta: ContextPackDelta) -> ContextPack:
    """Validate the base, bounds and final target digest before returning any result."""

    if not isinstance(base, ContextPack) or not isinstance(delta, ContextPackDelta):
        message = "Context reconstruction requires a complete base pack and a delta"
        raise ContextPackError(message)
    if base.digest != delta.base_digest:
        message = "Context delta does not identify this base pack"
        raise ContextPackError(message)
    if delta.prefix_items > len(base.items):
        message = "Context delta prefix exceeds the base chunk count"
        raise ContextPackError(message)
    target = ContextPack.build(base.items[: delta.prefix_items] + delta.appended)
    if target.digest != delta.target_digest:
        message = "Reconstructed context does not match the target digest"
        raise ContextPackError(message)
    return target


__all__ = ["ContextPack", "ContextPackDelta", "ContextPackError", "apply_context_pack_delta"]
