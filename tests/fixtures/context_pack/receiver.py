# Copyright (c) 2026 OceanBase.
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
# http://www.apache.org/licenses/LICENSE-2.0
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Independent receiver oracle: deliberately imports only the Python standard library."""

from __future__ import annotations

import base64
import hashlib
import json
import sys


def receive(frames: list[str]) -> list[dict[str, object]]:
    items: list[str] = []
    digest = None
    results: list[dict[str, object]] = []
    for index, frame in enumerate(frames):
        raw = base64.b64decode(frame, validate=True)
        payload = json.loads(raw.decode("utf-8"))
        if index == 0:
            if set(payload) != {"schema", "items", "digest", "byte_count"}:
                raise ValueError("Incorrect full pack fields")  # noqa: TRY003
            if payload["schema"] != "powercontext.context-pack.v1" or payload["byte_count"] != len(raw):
                raise ValueError("Incorrect full pack metadata")  # noqa: TRY003
            items = payload["items"]
            expected = payload["digest"]
        else:
            if set(payload) != {"schema", "base_digest", "target_digest", "prefix_items", "appended"}:
                raise ValueError("Incorrect delta fields")  # noqa: TRY003
            prefix = payload["prefix_items"]
            if (
                payload["schema"] != "powercontext.context-pack-delta.v1"
                or payload["base_digest"] != digest
                or type(prefix) is not int
                or not 0 <= prefix <= len(items)
            ):
                raise ValueError("Incorrect delta metadata")  # noqa: TRY003
            items = items[:prefix] + payload["appended"]
            expected = payload["target_digest"]
        unsigned = {"schema": "powercontext.context-pack.v1", "items": items}
        digest = (
            "sha256:" + hashlib.sha256(json.dumps(unsigned, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        )
        if digest != expected:
            raise ValueError("Incorrect reconstructed digest")  # noqa: TRY003
        chunks = tuple(base64.b64decode(item, validate=True) for item in items)
        for chunk in chunks:
            chunk.decode("utf-8", errors="strict")
        results.append({"content": base64.b64encode(b"".join(chunks)).decode("ascii"), "digest": digest})
    return results


if __name__ == "__main__":
    print(json.dumps(receive(json.load(sys.stdin)), separators=(",", ":")))
