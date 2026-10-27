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

import base64
import hashlib
import itertools
import json

import pytest

from powercontext.builtin.runtime.context_pack import (
    ContextPack,
    ContextPackDelta,
    ContextPackError,
    apply_context_pack_delta,
)


@pytest.mark.parametrize("size", [0, 1, 99, 999, 1000, 9999])
def test_full_wire_size_includes_its_own_field_at_decimal_boundaries(size: int) -> None:
    pack = ContextPack.build((b"x" * size,))
    wire = pack.to_bytes()
    payload = json.loads(wire)
    assert set(payload) == {"schema", "items", "digest", "byte_count"}
    assert payload["items"] == [base64.b64encode(b"x" * size).decode()]
    unsigned = {"schema": "powercontext.context-pack.v1", "items": payload["items"]}
    assert (
        payload["digest"]
        == "sha256:" + hashlib.sha256(json.dumps(unsigned, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    )
    assert payload["byte_count"] == pack.byte_count == len(wire)
    assert wire == json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    assert ContextPack.from_bytes(wire) == pack


@pytest.mark.parametrize("limit", [1, 2, 3, 4, 5, 7])
def test_utf8_chunking_preserves_exact_bytes_across_unicode_and_newline_boundaries(limit: int) -> None:
    for symbols in itertools.product(("a", "é", "海", "🙂", "\r\n", "é"), repeat=2):
        content = "".join(symbols)
        longest_character = max(len(character.encode()) for character in content)
        if longest_character > limit:
            with pytest.raises(ContextPackError):
                ContextPack.from_content(content, chunk_bytes=limit)
            continue
        pack = ContextPack.from_content(content, chunk_bytes=limit)
        assert b"".join(pack.items) == content.encode()
        assert all(len(item) <= limit and item.decode().encode() == item for item in pack.items)
        assert ContextPack.from_content(content, chunk_bytes=limit).to_bytes() == pack.to_bytes()


@pytest.mark.parametrize("limit", [0, -1, True, 1.5, "512"])
def test_invalid_chunk_limit_is_a_protocol_error(limit: int) -> None:
    with pytest.raises(ContextPackError):
        ContextPack.from_content("x", chunk_bytes=limit)


@pytest.mark.parametrize("items", [(b"\xff",), (b"\xe6\xb5", b"\xb7"), ("text",), [b"text"]])
def test_chunks_must_be_immutable_bytes_and_individually_valid_utf8(items: tuple[bytes, ...]) -> None:
    with pytest.raises(ContextPackError):
        ContextPack.build(items)


@pytest.mark.parametrize("content", ["", b"", None])
def test_empty_content_has_an_empty_pack(content: str | bytes | None) -> None:
    assert ContextPack.from_content(content).items == ()
    assert ContextPack.from_bytes(ContextPack.from_content(content).to_bytes()).items == ()


@pytest.mark.parametrize(
    "change",
    [
        {"schema": "wrong"},
        {"extra": 1},
        {"digest": "SHA256:" + "0" * 64},
        {"byte_count": True},
        {"byte_count": 1.5},
        {"byte_count": -1},
        {"byte_count": 9999},
        {"items": "YQ=="},
        {"items": [1]},
        {"items": ["YQ"]},
        {"items": ["YR=="]},
        {"items": ["YQ==\n"]},
        {"items": ["_w=="]},
        {"items": ["/w=="]},
    ],
)
def test_pack_wire_rejects_bad_fields_counts_and_encodings(change: dict[str, object]) -> None:
    payload = json.loads(ContextPack.build((b"a",)).to_bytes())
    payload.update(change)
    with pytest.raises(ContextPackError):
        ContextPack.from_bytes(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode())


@pytest.mark.parametrize("wire", [b"", b"[]", b"null", b"\xff", b"{broken}"])
def test_invalid_wire_fails_consistently_for_both_message_types(wire: bytes) -> None:
    for decoder in (ContextPack.from_bytes, ContextPackDelta.from_bytes):
        with pytest.raises(ContextPackError):
            decoder(wire)


def test_missing_fields_and_duplicate_fields_are_rejected() -> None:
    base = ContextPack.build((b"base",))
    delta = ContextPackDelta.between(base, ContextPack.build((b"base", b"tail")))
    for value, decoder in ((base, ContextPack.from_bytes), (delta, ContextPackDelta.from_bytes)):
        payload = json.loads(value.to_bytes())
        for field in payload:
            incomplete = {key: item for key, item in payload.items() if key != field}
            with pytest.raises(ContextPackError):
                decoder(json.dumps(incomplete).encode())
        duplicate = value.to_bytes()[:-1] + b',"schema":' + json.dumps(payload["schema"]).encode() + b"}"
        with pytest.raises(ContextPackError):
            decoder(duplicate)


@pytest.mark.parametrize("prefix", [True, 1.0, -1, "1", None])
def test_delta_prefix_is_a_strict_nonnegative_integer(prefix: int) -> None:
    base = ContextPack.build((b"a",))
    payload = json.loads(ContextPackDelta.between(base, base).to_bytes())
    payload["prefix_items"] = prefix
    with pytest.raises(ContextPackError):
        ContextPackDelta.from_bytes(json.dumps(payload).encode())


@pytest.mark.parametrize(
    "change",
    [
        {"schema": "wrong"},
        {"byte_count": 123},
        {"base_digest": "bad"},
        {"target_digest": 123},
        {"appended": "YQ=="},
        {"appended": [True]},
        {"appended": ["YQ"]},
        {"appended": ["/w=="]},
    ],
)
def test_delta_rejects_extra_fields_bad_digests_and_invalid_suffix_chunks(change: dict[str, object]) -> None:
    base = ContextPack.build((b"a",))
    payload = json.loads(ContextPackDelta.between(base, ContextPack.build((b"a", b"b"))).to_bytes())
    payload.update(change)
    with pytest.raises(ContextPackError):
        ContextPackDelta.from_bytes(json.dumps(payload).encode())


def test_every_valid_common_prefix_reconstructs_exact_target_chunks() -> None:
    base = ContextPack.build((b"first", "第二".encode(), b"old"))
    target = ContextPack.build((b"first", "第二".encode(), b"new", b"tail"))
    for prefix in range(3):
        delta = ContextPackDelta(base.digest, target.digest, prefix, target.items[prefix:])
        receiver = apply_context_pack_delta(
            ContextPack.from_bytes(base.to_bytes()), ContextPackDelta.from_bytes(delta.to_bytes())
        )
        assert receiver.items == target.items
        assert receiver.to_bytes() == target.to_bytes()
        assert delta.byte_count == len(delta.to_bytes())
        assert "byte_count" not in json.loads(delta.to_bytes())


def test_digest_protects_chunk_boundaries_as_well_as_joined_text() -> None:
    base = ContextPack.build((b"abc",))
    target = ContextPack.build((b"a", b"bc"))
    assert b"".join(base.items) == b"".join(target.items) and base.digest != target.digest
    with pytest.raises(ContextPackError):
        apply_context_pack_delta(base, ContextPackDelta(base.digest, target.digest, 1, ()))
    with pytest.raises(ContextPackError):
        apply_context_pack_delta(base, ContextPackDelta(base.digest, target.digest, 2, ()))
    assert apply_context_pack_delta(base, ContextPackDelta.between(base, target)) == target


def test_empty_target_and_independent_receiver_can_drop_every_base_chunk() -> None:
    base = ContextPack.from_content("prefix\n正文\n")
    empty = ContextPack.build(())
    delta = ContextPackDelta.between(base, empty)
    assert (
        apply_context_pack_delta(ContextPack.from_bytes(base.to_bytes()), ContextPackDelta.from_bytes(delta.to_bytes()))
        == empty
    )
