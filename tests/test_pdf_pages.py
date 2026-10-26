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

import hashlib
import io
from unittest.mock import AsyncMock

import pytest
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, NameObject

from powercontext.sources import SourceDefinitionRegistry, SourceMaterialization, TextEvidence
from powercontext.sources.pdf_pages import (
    PDF_PAGE_SOURCE_DEFINITION,
    PDFDocumentInput,
    PDFPageInput,
    parse_pdf_document,
    search_pdf_pages,
)
from powercontext.sources.projections import TEXT_EVIDENCE_PROJECTION_KEY


def test_password_protected_pdf_is_rejected_without_returning_pages() -> None:
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=300)
    writer.encrypt("required-password")
    output = io.BytesIO()
    writer.write(output)
    with pytest.raises(ValueError):
        parse_pdf_document(PDFDocumentInput(document_id="locked", content=output.getvalue()))


def test_failure_in_later_page_rejects_the_entire_document() -> None:
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=300)
    page = writer.add_blank_page(width=200, height=300)
    broken = DecodedStreamObject()
    broken.set_data(b"BT (unterminated string")
    page[NameObject("/Contents")] = broken
    output = io.BytesIO()
    writer.write(output)
    with pytest.raises(ValueError):
        parse_pdf_document(PDFDocumentInput(document_id="broken", content=output.getvalue()))


@pytest.mark.parametrize("document_id", ["", " \t\n"])
def test_blank_document_identity_is_rejected(document_id: str) -> None:
    with pytest.raises(ValueError):
        parse_pdf_document(PDFDocumentInput(document_id=document_id, content=b"%PDF-1.7"))


@pytest.mark.parametrize("page_number", [True, 1.0, 0, -1])
def test_page_identity_requires_positive_integral_physical_page_numbers(page_number: object) -> None:
    with pytest.raises(ValueError):
        PDFPageInput.model_validate({
            "document_id": "d",
            "document_sha256": "a" * 64,
            "page_number": page_number,
            "text": "",
        })


async def test_identity_components_are_unambiguous_and_read_projection_are_exact() -> None:
    registry = SourceDefinitionRegistry((PDF_PAGE_SOURCE_DEFINITION,))
    original = PDFPageInput(
        document_id="文档:" * 300,
        document_sha256=hashlib.sha256(b"first bytes").hexdigest(),
        page_number=3,
        text=" revenue 001\n cost 02 \n",
    )
    names = set()
    for page in (
        original,
        original.model_copy(update={"document_id": original.document_id + "x"}),
        original.model_copy(update={"document_sha256": hashlib.sha256(b"revision").hexdigest()}),
        original.model_copy(update={"page_number": 4}),
    ):
        source = await registry.resolve(page)
        assert source.name == (await registry.resolve(page)).name and len(source.name) <= 256
        assert source.materialization is SourceMaterialization.CAPTURED
        assert await registry.read(source) == page
        evidence = TextEvidence.model_validate(registry.project(source, TEXT_EVIDENCE_PROJECTION_KEY))
        assert evidence.content == page.document_id + "\n" + page.text
        assert evidence.source_id == source.name
        assert evidence.metadata == {
            "document_id": page.document_id,
            "document_sha256": page.document_sha256,
            "page_number": page.page_number,
        }
        names.add(source.name)
    assert len(names) == 4


@pytest.mark.parametrize("question,limit", [("", 1), (" \n", 1), ("q", 0), ("q", -1), ("q", True), ("q", 1.5)])
async def test_search_bounds_fail_before_memory_io(question: str, limit: int) -> None:
    memory = AsyncMock()
    with pytest.raises(ValueError):
        await search_pdf_pages(memory, question, limit)
    memory.search.assert_not_awaited()
    memory.list.assert_not_awaited()
