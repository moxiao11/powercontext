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

"""Capture CSV records as stable, independently readable evidence."""

from __future__ import annotations

import csv
import io
import json
from urllib.parse import quote

from pydantic import BaseModel
from typing_extensions import override

from powercontext.limits import MAX_SOURCE_ID_LENGTH
from powercontext.sources.definitions import SourceDefinition, SourceProjection
from powercontext.sources.models import Source, SourceMaterialization
from powercontext.sources.projections import TEXT_EVIDENCE_PROJECTION_KEY, TextEvidence


class CSVDocumentInput(BaseModel):
    """One complete UTF-8 CSV document and its exact primary-key column."""

    document_id: str
    primary_key: str
    content: bytes


class CSVRowInput(BaseModel):
    """One record with the original column order and string values."""

    document_id: str
    primary_key: str
    primary_key_value: str
    columns: tuple[str, ...]
    values: tuple[str, ...]


class CSVRowSource(Source):
    """A captured record whose identity is independent of row position."""

    source_id: str
    document_id: str
    primary_key: str
    primary_key_value: str
    columns: tuple[str, ...]
    values: tuple[str, ...]


def _validate_document_id(document_id: str) -> None:
    if not isinstance(document_id, str) or not document_id or document_id != document_id.strip():
        message = "document_id must be non-empty and have no surrounding whitespace"
        raise ValueError(message)


def csv_row_source_id(document_id: str, primary_key_value: str) -> str:
    """Encode each identity component separately, preserving significant spaces."""

    _validate_document_id(document_id)
    if not isinstance(primary_key_value, str) or not primary_key_value.strip():
        message = "primary_key_value must not be empty or whitespace"
        raise ValueError(message)
    identity = f"csv:{quote(document_id, safe='')}:{quote(primary_key_value, safe='')}"
    if len(identity) > MAX_SOURCE_ID_LENGTH:
        message = f"CSV source identity must not exceed {MAX_SOURCE_ID_LENGTH} characters"
        raise ValueError(message)
    return identity


def _primary_key_index(columns: tuple[str, ...], primary_key: str) -> int:
    if not columns or any(not column.strip() for column in columns):
        message = "CSV header must contain non-empty column names"
        raise ValueError(message)
    if len(set(columns)) != len(columns):
        message = "CSV header must contain unique column names"
        raise ValueError(message)
    if not primary_key or primary_key not in columns:
        message = "primary_key must exactly match a CSV column name"
        raise ValueError(message)
    return columns.index(primary_key)


def _validate_row(value: CSVRowInput) -> str:
    identity = csv_row_source_id(value.document_id, value.primary_key_value)
    key_index = _primary_key_index(value.columns, value.primary_key)
    if len(value.values) != len(value.columns):
        message = "CSV record width must match its header"
        raise ValueError(message)
    if value.values[key_index] != value.primary_key_value:
        message = "primary_key_value must match the record's primary-key field"
        raise ValueError(message)
    return identity


def parse_csv_document(value: CSVDocumentInput) -> tuple[CSVRowInput, ...]:
    """Validate the whole document before exposing any captured rows."""

    _validate_document_id(value.document_id)
    text = value.content.decode("utf-8-sig", errors="strict")
    reader = csv.reader(io.StringIO(text, newline=""), delimiter=",", quotechar='"', doublequote=True, strict=True)
    rows: list[CSVRowInput] = []
    seen_keys: set[str] = set()
    try:
        columns = tuple(next(reader, ()))
        key_index = _primary_key_index(columns, value.primary_key)
        for record in reader:
            if not record:
                continue
            if len(record) != len(columns):
                message = f"CSV record ending at line {reader.line_num} has the wrong width"
                raise ValueError(message)
            row = CSVRowInput(
                document_id=value.document_id,
                primary_key=value.primary_key,
                primary_key_value=record[key_index],
                columns=columns,
                values=tuple(record),
            )
            _validate_row(row)
            if row.primary_key_value in seen_keys:
                message = f"Duplicate CSV primary key at line {reader.line_num}"
                raise ValueError(message)
            seen_keys.add(row.primary_key_value)
            rows.append(row)
    except csv.Error as error:
        message = f"Invalid CSV at line {reader.line_num}: {error}"
        raise ValueError(message) from error
    return tuple(rows)


class _CSVRowTextEvidence:
    name = TEXT_EVIDENCE_PROJECTION_KEY.name
    version = TEXT_EVIDENCE_PROJECTION_KEY.version
    source_class = CSVRowSource
    output_class: type[BaseModel] = TextEvidence

    def project(self, source: CSVRowSource, /) -> TextEvidence:
        row = dict(zip(source.columns, source.values, strict=True))
        return TextEvidence(
            source_type="csv-row",
            source_id=source.source_id,
            content=json.dumps(row, ensure_ascii=False, separators=(",", ":")),
            metadata={
                "document_id": source.document_id,
                "primary_key": source.primary_key,
                "primary_key_value": source.primary_key_value,
                "columns": list(source.columns),
                "row": row,
            },
        )


class _CSVRowDefinition(SourceDefinition[CSVRowInput, CSVRowSource, CSVRowInput]):
    name = "csv-row"
    version = "1"
    input_class = CSVRowInput
    source_class = CSVRowSource
    projections: tuple[SourceProjection[CSVRowSource], ...] = (_CSVRowTextEvidence(),)

    @override
    async def resolve(self, value: CSVRowInput, /) -> CSVRowSource:
        identity = _validate_row(value)
        return CSVRowSource(
            name=identity,
            source_id=identity,
            definition_version=self.version,
            materialization=SourceMaterialization.CAPTURED,
            **value.model_dump(),
        )

    @override
    async def read(self, source: CSVRowSource, /) -> CSVRowInput:
        return CSVRowInput(
            document_id=source.document_id,
            primary_key=source.primary_key,
            primary_key_value=source.primary_key_value,
            columns=source.columns,
            values=source.values,
        )


CSV_ROW_SOURCE_DEFINITION: SourceDefinition[CSVRowInput, CSVRowSource, CSVRowInput] = _CSVRowDefinition()

__all__ = [
    "CSV_ROW_SOURCE_DEFINITION",
    "CSVDocumentInput",
    "CSVRowInput",
    "CSVRowSource",
    "csv_row_source_id",
    "parse_csv_document",
]
