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

"""CSV boundary cases beyond the competition's airport workload."""

from __future__ import annotations

import asyncio
import json

import pytest

from powercontext.sources import SourceDefinitionRegistry, SourceMaterialization, TextEvidence
from powercontext.sources.csv_rows import (
    CSV_ROW_SOURCE_DEFINITION,
    CSVDocumentInput,
    CSVRowInput,
    csv_row_source_id,
    parse_csv_document,
)
from powercontext.sources.projections import TEXT_EVIDENCE_PROJECTION_KEY


@pytest.mark.parametrize(
    "content",
    [
        b"\nid,name\n1,one\n",  # A blank first record is not a header to skip.
        b'id\n""\n',  # A quoted empty field is a record, not an empty physical line.
        b'id,name\n1,valid\n2,"invalid"tail\n',
        b"id,name\n1,valid\n2,too,many\n",
        b"id,name\n1,valid\n \t,blank-key\n",
        b"id,name\n1,valid\n\xff,invalid-encoding\n",
    ],
)
def test_invalid_documents_raise_before_returning_any_rows(content: bytes) -> None:
    with pytest.raises(ValueError):
        parse_csv_document(CSVDocumentInput(document_id="table", primary_key="id", content=content))


def test_one_column_records_and_empty_physical_lines_are_distinct() -> None:
    rows = parse_csv_document(
        CSVDocumentInput(document_id="table", primary_key="id", content=b"id\r\n\r\nfirst\r\n\r\nsecond\r\n")
    )
    assert [row.values for row in rows] == [("first",), ("second",)]


def test_identity_length_is_checked_after_percent_encoding() -> None:
    assert len(csv_row_source_id("d", "x" * 250)) == 256
    with pytest.raises(ValueError):
        csv_row_source_id("d", "x" * 251)
    assert csv_row_source_id("d", "界" * 27) == "csv:d:" + "%E7%95%8C" * 27
    with pytest.raises(ValueError):
        csv_row_source_id("d", "界" * 28)
    assert csv_row_source_id("a:b", "c") != csv_row_source_id("a", "b:c")
    assert csv_row_source_id("a%3Ab", "c") != csv_row_source_id("a:b", "c")


def test_captured_evidence_keeps_unicode_column_order_and_string_types() -> None:
    row = parse_csv_document(
        CSVDocumentInput(
            document_id="中文/表",
            primary_key=" id ",
            content='" id ",城市,number,empty,flag\r\n key ,杭州,001,,false\r\n'.encode(),
        )
    )[0]
    registry = SourceDefinitionRegistry((CSV_ROW_SOURCE_DEFINITION,))
    source = asyncio.run(registry.resolve(row))
    assert source.materialization is SourceMaterialization.CAPTURED
    assert asyncio.run(registry.read(source)) == row
    evidence = TextEvidence.model_validate(registry.project(source, TEXT_EVIDENCE_PROJECTION_KEY))
    assert evidence.content == '{" id ":" key ","城市":"杭州","number":"001","empty":"","flag":"false"}'
    assert list(json.loads(evidence.content)) == list(row.columns)
    assert evidence.metadata == {
        "document_id": row.document_id,
        "primary_key": row.primary_key,
        "primary_key_value": row.primary_key_value,
        "columns": list(row.columns),
        "row": dict(zip(row.columns, row.values, strict=True)),
    }


@pytest.mark.parametrize(
    "updates",
    [
        {"primary_key_value": "different"},
        {"values": ("1",)},
        {"columns": ("id", "id")},
        {"document_id": " table"},
    ],
)
def test_direct_row_resolution_rejects_inconsistent_evidence(updates: dict[str, object]) -> None:
    fields = {
        "document_id": "table",
        "primary_key": "id",
        "primary_key_value": "1",
        "columns": ("id", "name"),
        "values": ("1", "one"),
    }
    row = CSVRowInput.model_validate(fields | updates)
    registry = SourceDefinitionRegistry((CSV_ROW_SOURCE_DEFINITION,))
    with pytest.raises(ValueError):
        asyncio.run(registry.resolve(row))
