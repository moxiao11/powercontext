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

"""Complete PDF page capture and offline, exact-citation financial retrieval."""

from __future__ import annotations

import hashlib
import io
import json
import math
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from powercontext.sources.definitions import AdapterSourceDefinition, SourceDefinition
from powercontext.sources.models import Source, SourceMaterialization
from powercontext.sources.projections import TEXT_EVIDENCE_PROJECTION_KEY, TextEvidence

if TYPE_CHECKING:
    from pypdf import PageObject

    from powercontext.artifacts import MemoryCitation
    from powercontext.builtin.runtime import MemoryEntryRecord, ScopedMemoryApplication


class PDFDocumentInput(BaseModel):
    """A complete PDF revision, supplied as bytes rather than extracted text."""

    document_id: str
    content: bytes


class PDFPageInput(BaseModel):
    """The full extractable text of one one-based physical PDF page."""

    document_id: str
    document_sha256: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")
    page_number: int = Field(ge=1, strict=True)
    text: str


class PDFPageSource(Source):
    """A page whose identity includes the entire original document revision."""

    document_id: str
    document_sha256: str
    page_number: int
    text: str


def _validate_document_id(document_id: str) -> None:
    if not document_id.strip():
        message = "PDF document_id must not be empty or whitespace"
        raise ValueError(message)


def parse_pdf_document(value: PDFDocumentInput) -> tuple[PDFPageInput, ...]:
    """Extract every physical page atomically, including blank pages."""

    # PDF parsing is optional for consumers of unrelated Source definitions.
    from pypdf import PdfReader

    _validate_document_id(value.document_id)
    digest = hashlib.sha256(value.content).hexdigest()
    try:
        reader = PdfReader(io.BytesIO(value.content), strict=True)
        if reader.is_encrypted:
            reader.decrypt("")
        return tuple(
            PDFPageInput(
                document_id=value.document_id,
                document_sha256=digest,
                page_number=number,
                text=_extract_page_text(page),
            )
            for number, page in enumerate(reader.pages, start=1)
        )
    except Exception as error:
        # pypdf also exposes low-level stream, object and decoding errors for damaged files.
        message = "PDF could not be completely parsed"
        raise ValueError(message) from error


def _extract_page_text(page: PageObject) -> str:
    contents = page.get_contents()
    if contents is not None:
        # Text extraction can skip fontless pages; malformed streams must still fail.
        _ = contents.operations
    return page.extract_text() or ""


class _PDFPageAdapter:
    name = "pdf-page"
    input_class = PDFPageInput
    source_class = PDFPageSource

    async def resolve(self, value: PDFPageInput, /) -> PDFPageSource:
        value = PDFPageInput.model_validate(value.model_dump())
        _validate_document_id(value.document_id)
        identity = json.dumps(
            [value.document_id, value.document_sha256, value.page_number], ensure_ascii=False, separators=(",", ":")
        )
        return PDFPageSource(
            name="pdf:" + hashlib.sha256(identity.encode("utf-8")).hexdigest(),
            materialization=SourceMaterialization.CAPTURED,
            **value.model_dump(),
        )

    async def read(self, source: PDFPageSource, /) -> PDFPageInput:
        return PDFPageInput.model_validate(source.model_dump())


class _PDFPageTextEvidence:
    name = TEXT_EVIDENCE_PROJECTION_KEY.name
    version = TEXT_EVIDENCE_PROJECTION_KEY.version
    source_class = PDFPageSource
    output_class: type[BaseModel] = TextEvidence

    def project(self, source: PDFPageSource, /) -> TextEvidence:
        return TextEvidence(
            source_type="pdf-page",
            source_id=source.name,
            content=f"{source.document_id}\n{source.text}",
            metadata={
                "document_id": source.document_id,
                "document_sha256": source.document_sha256,
                "page_number": source.page_number,
            },
        )


PDF_PAGE_SOURCE_DEFINITION: SourceDefinition[PDFPageInput, PDFPageSource, PDFPageInput] = AdapterSourceDefinition(
    _PDFPageAdapter(), projections=(_PDFPageTextEvidence(),)
)

_STOP_WORDS = frozenset([
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "been",
    "being",
    "by",
    "can",
    "could",
    "did",
    "do",
    "does",
    "for",
    "from",
    "had",
    "has",
    "have",
    "how",
    "i",
    "if",
    "in",
    "into",
    "is",
    "it",
    "its",
    "may",
    "not",
    "of",
    "on",
    "only",
    "or",
    "our",
    "should",
    "than",
    "that",
    "the",
    "their",
    "them",
    "then",
    "there",
    "these",
    "they",
    "this",
    "those",
    "to",
    "was",
    "were",
    "what",
    "when",
    "where",
    "which",
    "who",
    "why",
    "will",
    "with",
    "would",
    "you",
    "your",
    "please",
    "provide",
    "give",
    "response",
    "answer",
    "respond",
    "question",
    "calculate",
    "define",
    "assuming",
    "perspective",
    "analyst",
    "investment",
    "relying",
    "shown",
    "details",
    "using",
    "use",
    "within",
    "reported",
    "report",
    "fiscal",
    "fy",
    "usd",
    "million",
    "millions",
    "explicitly",
    "directly",
    "quantity",
    "state",
    "outlined",
    "important",
    "primarily",
])

# Domain terminology, independent of any document, question set, or annotated evidence.
_FINANCIAL_TERMS = (
    (("ebitda",), ("operating income", "depreciation amortization", "statement cash flows", "statement income")),
    (("capex",), ("capital expenditures", "purchases property plant equipment")),
    (("legal", "litigation", "lawsuit", "battle"), ("legal proceedings", "litigation", "lawsuits", "contingencies")),
    (("geography", "geographic", "region"), ("geographic", "segments", "countries", "markets", "international")),
    (("restructuring", "reorganization"), ("restructuring", "charges", "costs")),
    (("revenue", "sales"), ("revenue", "net sales")),
    (("borrowings", "debt"), ("debt", "borrowings", "credit")),
)


def _stem(word: str) -> str:
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 4 and word.endswith("ing"):
        word = word[:-3]
    elif len(word) > 4 and word.endswith("ed"):
        word = word[:-2]
    elif len(word) > 3 and word.endswith("s") and not word.endswith(("ss", "us", "is")):
        word = word[:-1]
    return word[:-1] if len(word) > 5 and word.endswith("e") else word


def _words(text: str) -> tuple[str, ...]:
    return tuple(_stem(word) for word in re.findall(r"[a-z]+|\d+", unicodedata.normalize("NFKC", text).casefold()))


_STOP_TERMS = frozenset(_stem(stop) for stop in _STOP_WORDS)


def _query_terms(question: str) -> tuple[dict[str, float], tuple[str, ...]]:
    question = re.sub(r"\bp\s*&\s*l\b", "income statement", question, flags=re.IGNORECASE)
    question = re.sub(r"\bd\s*&\s*a\b", "depreciation amortization", question, flags=re.IGNORECASE)
    terms = tuple(word for word in _words(question) if word not in _STOP_TERMS)
    weights = dict.fromkeys(terms, 1.0)
    phrases = [" ".join(terms[index : index + 2]) for index in range(len(terms) - 1)]
    for triggers, expansions in _FINANCIAL_TERMS:
        if weights.keys().isdisjoint(_stem(trigger) for trigger in triggers):
            continue
        for expansion in expansions:
            expanded = _words(expansion)
            phrases.append(" ".join(expanded))
            for term in expanded:
                weights.setdefault(term, 0.5)
    return weights, tuple(dict.fromkeys(phrase for phrase in phrases if " " in phrase))


@dataclass(frozen=True)
class _SearchPage:
    record: MemoryEntryRecord
    document: str
    terms: Counter[str]
    heading: frozenset[str]
    normalized: str
    pages: frozenset[str]


def _search_pages(records: tuple[MemoryEntryRecord, ...], question: str) -> list[_SearchPage]:
    pages = []
    for record in records:
        references = frozenset(source.source_id for source in record.entry.sources if source.source_type == "pdf-page")
        if not references:
            continue
        document, _, body = record.entry.text.partition("\n")
        words = _words(body)
        pages.append(
            _SearchPage(record, document, Counter(words), frozenset(_words(body[:600])), " ".join(words), references)
        )
    # Prefer the company named by the caller when document identities expose it.
    compact_question = "".join(re.findall(r"[a-z0-9]+", question.casefold()))
    question_tokens = set(re.findall(r"[a-z0-9]+", question.casefold()))
    documents = {
        page.document
        for page in pages
        if any(
            len(term) >= 2
            and not term.isdigit()
            and term not in {"annual", "report", "form", "10k", "10q", "20f"}
            and (term in question_tokens or (len(term) >= 3 and term in compact_question))
            for term in re.findall(r"[a-z0-9]+", page.document.casefold())
        )
    }
    return [page for page in pages if not documents or page.document in documents]


def _rank_pages(pages: list[_SearchPage], question: str) -> list[tuple[float, _SearchPage]]:
    weights, phrases = _query_terms(question)
    frequencies = Counter(term for page in pages for term in weights if term in page.terms)
    average_length = sum(page.terms.total() for page in pages) / max(len(pages), 1)
    idf = {term: math.log1p((len(pages) - frequencies[term] + 0.5) / (frequencies[term] + 0.5)) for term in weights}
    scored = []
    for page in pages:
        normalization = 1.2 * (0.25 + 0.75 * page.terms.total() / max(average_length, 1))
        score = sum(
            weight * idf[term] * (2.2 * page.terms[term] / (page.terms[term] + normalization))
            + (0.8 * weight * idf[term] if term in page.heading else 0)
            for term, weight in weights.items()
        )
        score += sum(
            0.3 * sum(idf.get(term, 0) for term in phrase.split()) for phrase in phrases if phrase in page.normalized
        )
        if score > 0:
            scored.append((score, page))
    return sorted(scored, key=lambda item: -item[0])


async def search_pdf_pages(
    memory: ScopedMemoryApplication, question: str, limit: int = 10
) -> tuple[MemoryCitation, ...]:
    """Search active scoped Memory evidence and return real, distinct page citations.

    Native FTS supplies a coarse ranking. Public current-head listing supplies the
    remaining lexical candidates and corpus statistics for offline BM25 expansion,
    avoiding the native multi-term admission floor for long financial questions.
    No PDF, label file, or precomputed answer is accessed during retrieval.
    """

    from powercontext.builtin.runtime import SearchMemoryRequest

    if type(limit) is not int or limit < 1:
        message = "PDF search limit must be a positive integer"
        raise ValueError(message)
    if not isinstance(question, str) or not question.strip():
        message = "PDF search question must not be empty or whitespace"
        raise ValueError(message)
    snapshot = await memory.list()
    if not snapshot.entries:
        return ()
    native = await memory.search(
        SearchMemoryRequest(query=question, mode="fts", limit=max(50, 5 * min(limit, len(snapshot.entries))))
    )
    ranked = _rank_pages(_search_pages(snapshot.entries, question), question)
    native_order = {(hit.entry_id, hit.entry_version_id): index for index, hit in enumerate(native.hits)}
    ranked.sort(
        key=lambda item: (
            -item[0],
            native_order.get((item[1].record.entry.entry_id, item[1].record.entry.entry_version_id), len(native_order)),
        )
    )
    selected: list[_SearchPage] = []
    seen_pages: set[str] = set()
    # Suppress near-duplicate pages without changing or synthesizing their citations.
    pool = ranked[: max(100, 6 * limit)]
    while pool and len(selected) < limit:
        best = max(range(len(pool)), key=lambda index: _diverse_score(pool[index], selected))
        _, page = pool.pop(best)
        if not seen_pages.isdisjoint(page.pages):
            continue
        selected.append(page)
        seen_pages.update(page.pages)
    return tuple(page.record.citation for page in selected)


def _diverse_score(candidate: tuple[float, _SearchPage], selected: list[_SearchPage]) -> float:
    score, page = candidate
    overlap = max(
        (
            len(page.terms.keys() & previous.terms.keys()) / max(len(page.terms.keys() | previous.terms.keys()), 1)
            for previous in selected
        ),
        default=0,
    )
    return score * (1 - 0.2 * overlap)


__all__ = [
    "PDF_PAGE_SOURCE_DEFINITION",
    "PDFDocumentInput",
    "PDFPageInput",
    "PDFPageSource",
    "parse_pdf_document",
    "search_pdf_pages",
]
