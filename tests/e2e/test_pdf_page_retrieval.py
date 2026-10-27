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

import io
from pathlib import Path

import pytest
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from powercontext.builtin.artifacts.memory import MemoryEntryInput
from powercontext.builtin.artifacts.memory.errors import InvalidMemoryCandidateError, InvalidMemoryEvidenceError
from powercontext.builtin.persistence.sqlite import SQLiteConfig
from powercontext.builtin.runtime import (
    BuiltinConfig,
    GetMemoryEntryRequest,
    RememberMemoryRequest,
    SubmitSourceObservation,
    open_builtin_contexts,
    open_builtin_runtime,
)
from powercontext.builtin.scope import ScopeDraft
from powercontext.sources import (
    SourceDefinitionRegistry,
    SourceObservation,
    manifest_for_definition,
    project_source_for_transport,
)
from powercontext.sources.pdf_pages import (
    PDF_PAGE_SOURCE_DEFINITION,
    PDFDocumentInput,
    parse_pdf_document,
    search_pdf_pages,
)
from powercontext.sources.projections import TEXT_EVIDENCE_PROJECTION_KEY, TextEvidence


def _pdf(texts: tuple[str, ...]) -> bytes:
    writer = PdfWriter()
    for text in texts:
        page = writer.add_blank_page(width=612, height=792)
        if not text:
            continue
        font = DictionaryObject({
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        })
        page[NameObject("/Resources")] = DictionaryObject({
            NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})
        })
        stream = DecodedStreamObject()
        escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        stream.set_data(f"BT /F1 12 Tf 24 700 Td ({escaped}) Tj ET".encode("ascii"))
        page[NameObject("/Contents")] = stream
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


def test_physical_boundaries_preserve_all_table_numbers_and_blank_pages() -> None:
    pages = parse_pdf_document(
        PDFDocumentInput(document_id="sample", content=_pdf(("Revenue 001 Cost 02 Total 003", "", "Cash 88 Tax 99")))
    )
    assert [page.page_number for page in pages] == [1, 2, 3]
    assert pages[0].text == "Revenue 001 Cost 02 Total 003"
    assert pages[1].text == ""
    assert pages[2].text == "Cash 88 Tax 99"


class _EvidencePipeline:
    async def extract(self, request, /):
        return tuple(
            MemoryEntryInput(
                kind=f"page-evidence-{copy}",
                text=TextEvidence.model_validate(source.projection(TEXT_EVIDENCE_PROJECTION_KEY)).content,
                sources=(source,),
            )
            for source in request.sources
            for copy in range(2)
        )


@pytest.mark.parametrize("company", ["NORTHSTAR", "3R"])
async def test_financial_expansion_distinct_pages_scopes_and_exact_citations_after_restart(
    tmp_path: Path, company: str
) -> None:
    text = (
        "Consolidated Statements of Income. Operating income 130. Net sales 900.",
        "Consolidated Statements of Cash Flows. Depreciation and amortization 20. Capital expenditures 40.",
        "Legal proceedings. Outstanding litigation remains pending.",
    )
    registry = SourceDefinitionRegistry((PDF_PAGE_SOURCE_DEFINITION,))
    observations = []
    for document in (f"{company}_2024_10K", "SOUTHERN_2024_10K"):
        for page in parse_pdf_document(PDFDocumentInput(document_id=document, content=_pdf(text))):
            observations.append(project_source_for_transport(registry, await registry.resolve(page)))
    config = BuiltinConfig(database=SQLiteConfig(url=f"sqlite+aiosqlite:///{tmp_path / 'pages.db'}"))
    async with open_builtin_runtime(config) as runtime:
        assert runtime.scopes is not None
        scope = await runtime.scopes.create(ScopeDraft(title="Reports", summary="Pages", idempotency_key="pages"))
        other = await runtime.scopes.create(ScopeDraft(title="Other", summary="Empty", idempotency_key="other"))
        await runtime.ingestion.register(manifest_for_definition(PDF_PAGE_SOURCE_DEFINITION))
        for observation in observations:
            await runtime.ingestion.submit(SubmitSourceObservation(scope_id=scope.scope_id, observation=observation))
    async with open_builtin_runtime(config, candidate_pipeline=_EvidencePipeline()) as runtime:
        memory = runtime.memory.for_scope(scope.scope_id)
        for _ in range(len(observations) + 1):
            if not (await memory.flush()).processed:
                break
        await memory.remember(
            RememberMemoryRequest(entries=(MemoryEntryInput(kind="noise", text=f"{company} EBITDA cash flows noise"),))
        )
    async with open_builtin_contexts(config) as contexts:
        journal = await (await contexts.get(scope.scope_id)).sources.journal.entries()
        stored = {entry.source_ref.source_id: entry.source for entry in journal}
    async with open_builtin_runtime(config) as runtime:
        memory = runtime.memory.for_scope(scope.scope_id)
        citations = await search_pdf_pages(
            memory, f"Calculate {company} EBITDA using operating income and D&A.", limit=2
        )
        assert len(citations) == 2
        pages = set()
        for citation in citations:
            entry = (await memory.get(GetMemoryEntryRequest(citation=citation))).entry
            observation = stored[entry.sources[0].source_id]
            assert isinstance(observation, SourceObservation)
            evidence = TextEvidence.model_validate(observation.projection(TEXT_EVIDENCE_PROJECTION_KEY))
            assert evidence.metadata["document_id"] == f"{company}_2024_10K"
            assert entry.text == evidence.content.strip()
            pages.add(evidence.metadata["page_number"])
        assert pages == {1, 2}
        legal = await search_pdf_pages(memory, f"{company} ongoing legal battles", limit=1)
        assert len(legal) == 1
        entry = (await memory.get(GetMemoryEntryRequest(citation=legal[0]))).entry
        source = stored[entry.sources[0].source_id]
        assert isinstance(source, SourceObservation)
        legal_page = TextEvidence.model_validate(source.projection(TEXT_EVIDENCE_PROJECTION_KEY))
        assert legal_page.metadata["page_number"] == 3
        assert legal_page.metadata["document_id"] == f"{company}_2024_10K"
        assert len(await search_pdf_pages(memory, f"{company} income cash flows", limit=10**50)) == 2
        assert await search_pdf_pages(runtime.memory.for_scope(other.scope_id), f"{company} EBITDA") == ()


@pytest.mark.parametrize("company,statement", [("ORBIT", "Earnings"), ("NOVA", "Operations")])
async def test_retrieval_covers_statement_and_region_evidence_among_many_keyword_mentions(
    tmp_path: Path, company: str, statement: str
) -> None:
    boilerplate = "Employee policy and administrative terms apply to every employee. " * 25
    distractors = tuple(
        f"Administrative exhibit {number}. {boilerplate} "
        "The unadjusted EBITDA analysis references the income statement and cash flow statement. "
        "Geographies and regions, countries, domestic and international markets are discussed elsewhere. "
        "Table of Contents. Risk Factors. Legal Proceedings. Properties. Controls and Procedures. Financial Statements. "
        "Customer concentration and operating margin are discussed elsewhere."
        for number in range(30)
    )
    evidence = (
        f"Consolidated Statements of {statement}. Net sales 900. Operating profit 130. Income before taxes 110.",
        "Consolidated Statements of Cash Flows. Depreciation and amortization 20. Capital expenditures 40.",
        "Our business is organized into reportable segments across North America, Latin America and Europe.",
        "Our Asia Pacific and Africa business comprises another segment with manufacturing and distribution.",
        "Consolidated Balance Shee t. Current assets 250, including cash 70, receivables 80 and inventory 100. "
        "Current liabilities 120. Property, plant and equipment 600. Total assets 900.",
        "Property descriptions and facilities. " * 50 + "\nItem 3. Legal Proceedings.\nMaterial litigation is pending.",
        "One customer accounted for 19% of consolidated revenue. Losing this customer would reduce sales.",
        "Management's Discussion and Analysis. The operating margin change reflects higher material costs.",
    )
    registry = SourceDefinitionRegistry((PDF_PAGE_SOURCE_DEFINITION,))
    pages = parse_pdf_document(
        PDFDocumentInput(document_id=f"{company}_2025_10K", content=_pdf(distractors + evidence))
    )
    config = BuiltinConfig(database=SQLiteConfig(url=f"sqlite+aiosqlite:///{tmp_path / 'facets.db'}"))
    async with open_builtin_runtime(config, candidate_pipeline=_EvidencePipeline()) as runtime:
        assert runtime.scopes is not None
        scope = await runtime.scopes.create(
            ScopeDraft(title="Reports", summary="Page evidence", idempotency_key="facets")
        )
        await runtime.ingestion.register(manifest_for_definition(PDF_PAGE_SOURCE_DEFINITION))
        locations = {}
        for page in pages:
            observation = project_source_for_transport(registry, await registry.resolve(page))
            locations[observation.name] = page.page_number
            await runtime.ingestion.submit(SubmitSourceObservation(scope_id=scope.scope_id, observation=observation))
        while (await runtime.memory.for_scope(scope.scope_id).flush()).processed:
            pass
    async with open_builtin_runtime(config) as runtime:
        memory = runtime.memory.for_scope(scope.scope_id)
        for question, required in (
            (
                f"Calculate the unadjusted EBITDA for {company} from operating income and depreciation and amortization.",
                {31, 32},
            ),
            (f"In which geographies and regions does {company} operate?", {33, 34}),
            (f"Does {company} have a healthy liquidity profile based on its quick ratio?", {35}),
            (f"Is {company} a capital-intensive business?", {31, 32, 35}),
            (f"Calculate the inventory turnover of {company}.", {31, 35}),
            (f"What is the net PPNE for {company} according to its balance sheet?", {35}),
            (f"Does {company} have improving free cashflow conversion?", {32}),
            (f"Calculate {company} DPO using COGS and the balance sheet.", {31, 35}),
            (f"Has {company} reported material ongoing legal battles?", {36}),
            (f"Does {company} have customer concentration?", {37}),
            (f"What drove operating margin change for {company}?", {38}),
        ):
            citations = await search_pdf_pages(memory, question, limit=20)
            found = set()
            for citation in citations:
                entry = (await memory.get(GetMemoryEntryRequest(citation=citation))).entry
                found.update(locations[source.source_id] for source in entry.sources)
            assert len(citations) <= 20 and len(citations) == len(found)
            assert required <= found


@pytest.mark.parametrize(
    "earlier,current,period",
    [
        ("2023", "2024", "FY2024"),
        ("2023", "2024", "FY24"),
        ("2024Q1", "2024Q2", "FY2024 Q2"),
        ("2024Q1", "2024Q2", "the second quarter of 2024"),
    ],
)
async def test_query_period_distinguishes_reports_of_the_same_company(
    tmp_path: Path, earlier: str, current: str, period: str
) -> None:
    registry = SourceDefinitionRegistry((PDF_PAGE_SOURCE_DEFINITION,))
    documents = (
        (
            f"ORBIT_{earlier}_REPORT",
            "Consolidated Statements of Income. Operating income 10. Operating income 11. Operating income 12.",
        ),
        (f"ORBIT_{current}_REPORT", "Consolidated Statements of Income. Operating income 130. Net sales 900."),
    )
    config = BuiltinConfig(database=SQLiteConfig(url=f"sqlite+aiosqlite:///{tmp_path / 'years.db'}"))
    locations = {}
    async with open_builtin_runtime(config, candidate_pipeline=_EvidencePipeline()) as runtime:
        assert runtime.scopes is not None
        scope = await runtime.scopes.create(ScopeDraft(title="Reports", summary="Years", idempotency_key="years"))
        await runtime.ingestion.register(manifest_for_definition(PDF_PAGE_SOURCE_DEFINITION))
        for document, text in documents:
            for page in parse_pdf_document(PDFDocumentInput(document_id=document, content=_pdf((text,)))):
                observation = project_source_for_transport(registry, await registry.resolve(page))
                locations[observation.name] = document
                await runtime.ingestion.submit(
                    SubmitSourceObservation(scope_id=scope.scope_id, observation=observation)
                )
        while (await runtime.memory.for_scope(scope.scope_id).flush()).processed:
            pass
    async with open_builtin_runtime(config) as runtime:
        memory = runtime.memory.for_scope(scope.scope_id)
        citations = await search_pdf_pages(memory, f"What was ORBIT operating income in {period}?", limit=1)
        assert len(citations) == 1
        entry = (await memory.get(GetMemoryEntryRequest(citation=citations[0]))).entry
        assert {locations[source.source_id] for source in entry.sources} == {f"ORBIT_{current}_REPORT"}


async def test_dense_pdf_page_exceeding_memory_body_limit_survives_restart_and_index_rebuild(tmp_path: Path) -> None:
    body = "Warranty commitments and reserves 12345. " * 500 + "Exact final evidence: cobalt obligation 6789."
    document = "AURORA_2025_10K"
    pages = parse_pdf_document(PDFDocumentInput(document_id=document, content=_pdf((body, "", "Net income 900."))))
    original = f"{document}\n{pages[0].text}".strip()
    assert len(original.encode()) > 8192
    registry = SourceDefinitionRegistry((PDF_PAGE_SOURCE_DEFINITION,))
    config = BuiltinConfig(database=SQLiteConfig(url=f"sqlite+aiosqlite:///{tmp_path / 'dense.db'}"))
    async with open_builtin_runtime(config, candidate_pipeline=_EvidencePipeline()) as runtime:
        assert runtime.scopes is not None
        scope = await runtime.scopes.create(ScopeDraft(title="Dense pages", summary="PDF", idempotency_key="dense"))
        await runtime.ingestion.register(manifest_for_definition(PDF_PAGE_SOURCE_DEFINITION))
        captured: list[SourceObservation] = []
        for page in pages:
            observation = project_source_for_transport(registry, await registry.resolve(page))
            captured.append(observation)
            await runtime.ingestion.submit(SubmitSourceObservation(scope_id=scope.scope_id, observation=observation))
        memory = runtime.memory.for_scope(scope.scope_id)
        while (await memory.flush()).processed:
            pass
        with pytest.raises(InvalidMemoryCandidateError, match="8192"):
            await memory.remember(RememberMemoryRequest(entries=(MemoryEntryInput(kind="fact", text=original),)))
        with pytest.raises(InvalidMemoryEvidenceError):
            await memory.remember(
                RememberMemoryRequest(entries=(MemoryEntryInput(kind="fact", text=original, sources=(captured[0],)),))
            )
    async with open_builtin_contexts(config) as contexts:
        await (await contexts.get(scope.scope_id)).artifacts.memory.rebuild_projections()
        journal = await (await contexts.get(scope.scope_id)).sources.journal.entries()
        stored = {item.source_ref.source_id: item.source for item in journal}
    async with open_builtin_runtime(config) as runtime:
        memory = runtime.memory.for_scope(scope.scope_id)
        citations = await search_pdf_pages(memory, "AURORA cobalt obligation", limit=1)
        assert len(citations) == 1
        entry = (await memory.get(GetMemoryEntryRequest(citation=citations[0]))).entry
        assert entry.text == original
        assert entry.sources
        source = stored[entry.sources[0].source_id]
        assert isinstance(source, SourceObservation)
        evidence = TextEvidence.model_validate(source.projection(TEXT_EVIDENCE_PROJECTION_KEY))
        assert evidence.content.strip() == original
        assert evidence.metadata == {
            "document_id": document,
            "document_sha256": pages[0].document_sha256,
            "page_number": 1,
        }
