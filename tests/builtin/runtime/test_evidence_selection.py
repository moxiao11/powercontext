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

import pytest
from pydantic import ValidationError

from powercontext.artifacts import ArtifactAddress, ArtifactRef
from powercontext.builtin.artifacts.memory import MemoryHit
from powercontext.builtin.runtime import ContextAssembly, PrepareContextRequest
from powercontext.builtin.runtime.errors import PreparedContextInvariantError
from powercontext.builtin.runtime.prepared_context import (
    MemoryEntryAddress,
    PreparedContextBuilder,
    PreparedMemoryCandidates,
    PreparedMemoryFragment,
)
from powercontext.builtin.runtime.prepared_text import TRUST_POLICY

_REF = ArtifactRef(family="memory", artifact_id="memory", revision=3)


def _group(text, *, scope="current", entry="entry"):
    return PreparedMemoryCandidates(
        scope_id=scope,
        memory_ref=_REF,
        hits=(
            MemoryHit(
                memory_ref=_REF,
                entry_id=entry,
                entry_version_id=entry + "-v1",
                text=text,
                score=1.0,
                matched_by=("fts",),
            ),
        ),
    )


def _build(query, groups, budget=1400, **settings):
    return PreparedContextBuilder().build_scopes_result(
        request=PrepareContextRequest(query=query, max_bytes=budget, evidence_selection=True, **settings),
        current_scope_id="current",
        memory_candidates=groups,
    )


def _verify(result, groups, budget):
    text = result.context.content or ""
    assert result.context.content_bytes == len(text.encode("utf-8")) <= budget
    if not text:
        assert result.fragments == result.origins == ()
        return
    assert text.startswith(TRUST_POLICY + "\n\nBEGIN_POWERCONTEXT_PREPARED_CONTEXT_V1\n")
    assert text.endswith("\nEND_POWERCONTEXT_PREPARED_CONTEXT_V1")
    wire = json.loads(text.splitlines()[-2])
    assert wire["trust"] == "untrusted_history"
    assert len(wire["items"]) == len(result.fragments) == len(result.origins)
    for item, fragment, origin in zip(wire["items"], result.fragments, result.origins, strict=True):
        assert origin == fragment.address
        address = fragment.address
        original = next(
            hit.text
            for group in groups
            if group.scope_id == address.memory.scope_id
            for hit in group.hits
            if hit.entry_id == address.entry_id and hit.entry_version_id == address.entry_version_id
        )
        assert type(fragment.start) is int and type(fragment.end) is int
        assert 0 <= fragment.start < fragment.end <= len(original)
        assert fragment.text == original[fragment.start : fragment.end] == item["content"]
        assert (item["start"], item["end"]) == (fragment.start, fragment.end)
        assert item["citation"] == {
            "scope_id": address.memory.scope_id,
            "memory_ref": address.memory.artifact.model_dump(mode="json"),
            "entry_id": address.entry_id,
            "entry_version_id": address.entry_version_id,
        }


@pytest.mark.parametrize("value", ["true", "false", 1, 0, None, 1.0])
def test_selection_switch_is_an_optional_strict_boolean(value):
    assert PrepareContextRequest(query="evidence").evidence_selection is False
    with pytest.raises(ValidationError):
        PrepareContextRequest.model_validate({"query": "evidence", "evidence_selection": value})


def test_disjoint_evidence_from_one_entry_keeps_two_literal_ranges():
    text = (
        "The cobalt sensor is calibrated at 37 degrees. "
        + "Unrelated operational history. " * 100
        + "The amber valve opens at 19 degrees."
    )
    groups = (_group(text),)
    result = _build("cobalt sensor calibrated amber valve opens", groups)
    _verify(result, groups, 1400)
    assert len(result.fragments) >= 2
    assert any("37 degrees" in fragment.text for fragment in result.fragments)
    assert any("19 degrees" in fragment.text for fragment in result.fragments)
    for first, second in zip(result.fragments, result.fragments[1:], strict=False):
        assert first.address == second.address and first.end <= second.start


def test_identical_content_in_distinct_scopes_retains_both_identities():
    text = "The cobalt station records the pressure."
    groups = (_group(text), _group(text, scope="other"))
    result = _build("cobalt station pressure", groups, budget=2200)
    _verify(result, groups, 2200)
    assert {fragment.address.memory.scope_id for fragment in result.fragments} == {"current", "other"}


@pytest.mark.parametrize("budget", [512, 700, 900, 1400])
def test_unicode_and_escaped_json_charge_the_complete_wire_bytes(budget):
    text = '深海传感器记录压力，原始证据包含引号"、反斜杠\\与符号🦑。\n' * 30  # noqa: RUF001 - literal Unicode evidence
    groups = (_group(text),)
    result = _build("深海 压力", groups, budget=budget)
    _verify(result, groups, budget)
    if budget >= 900:
        assert result.fragments


def test_exact_budget_boundary_and_probe_use_the_same_rendering():
    groups = (_group("The cobalt station records pressure.\nThe sensor calibration is complete."),)
    generous = _build("cobalt pressure calibration", groups, budget=3000)
    ceiling = generous.context.content_bytes
    exact = _build("cobalt pressure calibration", groups, budget=ceiling)
    assert exact.context.content == generous.context.content
    smaller = _build("cobalt pressure calibration", groups, budget=ceiling - 1)
    _verify(smaller, groups, ceiling - 1)
    request = PrepareContextRequest(query="cobalt pressure calibration", max_bytes=ceiling - 1, evidence_selection=True)
    probe = PreparedContextBuilder().probe_budget(request=request, current_scope_id="current", memory_candidates=groups)
    assert probe.delivered_items == len(smaller.origins)
    assert probe.unused_bytes == request.max_bytes - smaller.context.content_bytes


def test_long_sentence_clips_around_rare_tail_matches_instead_of_repeated_prefix_terms():
    text = "station history " * 800 + "the cobalt instrument records 371 degrees at the final station"
    groups = (_group(text),)
    result = _build("station cobalt 371", groups, budget=1100)
    _verify(result, groups, 1100)
    assert any("371" in fragment.text and fragment.start > 5000 for fragment in result.fragments)


def test_empty_and_unrelated_candidates_return_legal_empty_context():
    for groups in [(), (_group("Administrative paperwork is archived."),)]:
        result = _build("cobalt sensor", groups, budget=900)
        _verify(result, groups, 900)
        assert result.context.content is None


def test_sentence_formatting_is_literal_evidence_when_budget_permits():
    prefix = "Administrative " + "notes " * 900 + "."
    evidence = "\n   RESULTS The cobalt calibration is accurate.  \n"
    text = prefix + evidence + "Further " + "history " * 900 + "."
    groups = (_group(text),)
    result = _build("cobalt calibration", groups, budget=1100)
    _verify(result, groups, 1100)
    assert any(
        fragment.start <= len(prefix) and fragment.end >= len(prefix) + len(evidence) for fragment in result.fragments
    )


def test_selection_remains_a_memory_envelope_when_other_presentation_modes_are_requested():
    groups = (_group("The cobalt station records pressure."),)
    result = _build("cobalt pressure", groups, include_code=True, assembly=ContextAssembly(sections=()))
    _verify(result, groups, 1400)
    assert result.fragments and not result.code_origins


@pytest.mark.parametrize(("start", "end"), [(False, 2), (0, True), (0.0, 2), (0, 2.0), (-1, 2), (2, 2)])
def test_fragment_coordinates_reject_booleans_floats_and_invalid_ranges(start, end):
    address = MemoryEntryAddress(
        memory=ArtifactAddress(scope_id="current", artifact=_REF), entry_id="entry", entry_version_id="entry-v1"
    )
    with pytest.raises(PreparedContextInvariantError):
        PreparedMemoryFragment(address=address, start=start, end=end, text="ab")


def test_default_off_preserves_the_ordinary_prefix_envelope_and_empty_fragment_metadata():
    groups = (_group("The cobalt station records pressure."),)
    builder = PreparedContextBuilder()
    ordinary = builder.build_scopes_result(
        request=PrepareContextRequest(query="cobalt"), current_scope_id="current", memory_candidates=groups
    )
    explicit = builder.build_scopes_result(
        request=PrepareContextRequest(query="cobalt", evidence_selection=False),
        current_scope_id="current",
        memory_candidates=groups,
    )
    assert ordinary == explicit and ordinary.fragments == ()
    assert ordinary.context.content is not None
    item = json.loads(ordinary.context.content.splitlines()[-2])["items"][0]
    assert item["content"] == groups[0].hits[0].text and item["truncated"] is False
    assert "start" not in item and "end" not in item
