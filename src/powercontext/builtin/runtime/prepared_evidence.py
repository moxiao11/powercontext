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

"""Query-driven literal evidence selection with an exact rendering budget."""

from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from functools import lru_cache

_WORDS = re.compile(r"[^\W_]+", re.UNICODE)
_BOUNDARY = re.compile(r"(?<=[。！？])|(?<=[.!?])[ \t]+|[\r\n]+")  # noqa: RUF001 - Chinese sentence punctuation
_CJK = re.compile(r"[\u3400-\u9fff]+")
_FINDING = re.compile(
    r"\b(?:results?|conclusions?|found|showed|demonstrated|revealed|observed|we show)\b", re.IGNORECASE
)
_FINITE_VERBS = frozenset({
    "is",
    "are",
    "was",
    "were",
    "found",
    "show",
    "shows",
    "showed",
    "demonstrates",
    "demonstrated",
    "suggest",
    "suggests",
    "suggested",
    "associated",
    "induces",
    "causes",
    "increase",
    "increases",
    "decrease",
    "decreases",
    "reduces",
    "reduced",
    "increased",
    "decreased",
    "suppresses",
    "inhibits",
    "promotes",
    "regulates",
    "correlates",
    "improves",
    "requires",
    "required",
    "confirmed",
    "reveals",
    "revealed",
})
_STOPWORDS = frozenset([
    "a",
    "an",
    "the",
    "and",
    "or",
    "of",
    "to",
    "in",
    "for",
    "on",
    "with",
    "by",
    "from",
    "as",
    "at",
    "is",
    "are",
    "was",
    "were",
    "be",
    "been",
    "being",
    "that",
    "this",
    "these",
    "those",
    "it",
    "its",
    "their",
    "which",
    "has",
    "have",
    "had",
    "can",
    "may",
    "could",
    "would",
    "should",
    "will",
    "did",
    "do",
    "does",
    "than",
    "then",
    "also",
    "such",
    "our",
    "we",
    "they",
    "not",
    "no",
    "into",
    "between",
    "both",
    "through",
])


@dataclass(frozen=True, order=True)
class EvidenceSpan:
    document: int
    start: int
    end: int


def _term(value: str) -> str:
    word = value.casefold()
    if not word.isascii() or not word.isalpha():
        return word
    if len(word) > 4 and word.endswith("ies"):
        word = word[:-3] + "y"
    elif len(word) > 3 and word.endswith("s") and not word.endswith(("ss", "us", "is")):
        word = word[:-1]
    if len(word) > 5 and word.endswith("ing"):
        word = word[:-3]
    elif len(word) > 4 and word.endswith("ed"):
        word = word[:-2]
    if len(word) > 5 and word.endswith("ly"):
        word = word[:-2]
    if len(word) > 6 and word.endswith("al"):
        word = word[:-2]
    if len(word) > 4 and word.endswith("e"):
        word = word[:-1]
    return word


def _tokens(text: str) -> tuple[str, ...]:
    terms = []
    for match in _WORDS.finditer(text):
        value = match.group()
        if _CJK.fullmatch(value):
            terms.extend(value[index : index + 2] for index in range(max(1, len(value) - 1)))
        elif value.casefold() not in _STOPWORDS:
            terms.append(_term(value))
    return tuple(terms)


def _sentences(document: int, text: str) -> tuple[EvidenceSpan, ...]:
    spans = []
    start = 0
    for boundary in _BOUNDARY.finditer(text):
        end = boundary.start()
        # Common scientific abbreviations do not end a sentence.
        previous = text[start:end].rsplit(None, 1)[-1:] or [""]
        if boundary.group().strip() == "" and previous[0].casefold() in {
            "e.g.",
            "i.e.",
            "fig.",
            "dr.",
            "vs.",
            "et al.",
        }:
            continue
        while start < end and text[start].isspace():
            start += 1
        if start < end:
            spans.append(EvidenceSpan(document, start, end))
        start = boundary.end()
    end = len(text)
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    if start < end:
        spans.append(EvidenceSpan(document, start, end))
    return tuple(spans)


def select_evidence_spans(  # noqa: C901 - bounded, pure search over literal ranges
    query: str,
    texts: Sequence[str],
    *,
    max_bytes: int,
    render: Callable[[tuple[EvidenceSpan, ...]], str],
    fragment_limit: int = 8,
) -> tuple[EvidenceSpan, ...]:
    """Choose ranges using only query/text, charging every serialized output byte."""

    query_terms = frozenset(_tokens(query))
    sentences = tuple(span for document, text in enumerate(texts) for span in _sentences(document, text))
    if not query_terms or not sentences or fragment_limit < 1:
        return ()
    tokens = {span: _tokens(texts[span.document][span.start : span.end]) for span in sentences}
    frequencies = Counter(term for words in tokens.values() for term in set(words) if term in query_terms)
    weights = {
        term: math.log(1 + (len(sentences) - frequencies[term] + 0.5) / (frequencies[term] + 0.5))
        for term in query_terms
    }
    average = sum(map(len, tokens.values())) / max(1, len(sentences))
    total_weight = sum(weights.values())

    def relevance(words: tuple[str, ...]) -> float:
        counts = Counter(words)
        score = sum(
            weight * counts[term] * 2.2 / (counts[term] + 1.2 * (0.75 + 0.25 * len(words) / max(1, average)))
            for term, weight in weights.items()
            if counts[term]
        )
        coverage = sum(weight for term, weight in weights.items() if counts[term])
        return (score + 0.35 * coverage) / max(total_weight, 1e-12)

    scores = {span: relevance(tokens[span]) for span in sentences}
    for document, text in enumerate(texts):
        local = [span for span in sentences if span.document == document]
        for span in local:
            body = text[span.start : span.end]
            if _FINDING.search(body):
                scores[span] *= 1.2
        if len(local) >= 3:
            first = local[0]
            words = {match.group().casefold() for match in _WORDS.finditer(text[first.start : first.end])}
            # A nominal title is useful for retrieval but is weaker evidence
            # than the findings in the body of the same recalled document.
            if len(tokens[first]) < 30 and words.isdisjoint(_FINITE_VERBS):
                scores[first] *= 0.6
    if not any(scores.values()):
        return ()
    document_terms = [frozenset(_tokens(text)) for text in texts]
    priors = [sum(weights[term] for term in query_terms & words) / total_weight for words in document_terms]

    @lru_cache(maxsize=8192)
    def cost(spans: tuple[EvidenceSpan, ...]) -> int:
        return len(render(spans).encode("utf-8"))

    def merge(spans: tuple[EvidenceSpan, ...]) -> tuple[EvidenceSpan, ...]:
        combined: list[EvidenceSpan] = []
        for span in sorted(spans):
            if combined and combined[-1].document == span.document:
                previous = combined[-1]
                joined = EvidenceSpan(span.document, previous.start, max(previous.end, span.end))
                # Joining a short gap can save a repeated citation. It keeps
                # the gap's original text rather than inserting synthetic text.
                if span.start <= previous.end or cost((joined,)) <= cost((previous, span)):
                    combined[-1] = joined
                    continue
            combined.append(span)
        return tuple(combined)

    @lru_cache(maxsize=8192)
    def utility(spans: tuple[EvidenceSpan, ...]) -> float:
        value = 0.0
        seen: set[tuple[int, str]] = set()
        for sentence in sentences:
            overlaps = [
                (max(sentence.start, span.start), min(sentence.end, span.end))
                for span in spans
                if span.document == sentence.document and span.start < sentence.end and span.end > sentence.start
            ]
            for start, end in overlaps:
                body = texts[sentence.document][start:end]
                key = (sentence.document, body)
                if key in seen:
                    continue
                seen.add(key)
                score = scores[sentence] if (start, end) == (sentence.start, sentence.end) else relevance(_tokens(body))
                value += (score * score + 0.015) * (0.5 + 0.5 * priors[sentence.document])
        return value

    choices: set[EvidenceSpan] = set()
    for document, text in enumerate(texts):
        local = [span for span in sentences if span.document == document]
        for index, span in enumerate(local):
            if not scores[span]:
                continue
            for before, after in ((0, 0), (1, 0), (0, 1), (1, 1), (2, 0), (0, 2)):
                candidate = EvidenceSpan(
                    document, local[max(0, index - before)].start, local[min(len(local) - 1, index + after)].end
                )
                if cost((candidate,)) <= max_bytes:
                    choices.add(candidate)
            if cost((span,)) > max_bytes:
                # An oversized sentence is clipped around query occurrences,
                # never blindly at its prefix. Coordinates remain characters.
                anchors = _query_anchors(text, span, query_terms, weights)
                for anchor in anchors:
                    low, high = 1, span.end - span.start
                    fitted = None
                    while low <= high:
                        size = (low + high) // 2
                        start = max(span.start, min(anchor - size // 2, span.end - size))
                        trial = EvidenceSpan(document, start, min(span.end, start + size))
                        if cost((trial,)) <= max_bytes:
                            fitted = trial
                            low = size + 1
                        else:
                            high = size - 1
                    if fitted is not None and relevance(_tokens(text[fitted.start : fitted.end])):
                        choices.add(fitted)
    ranked = sorted(choices, key=lambda span: (-utility((span,)), cost((span,)), span))[:96]
    beam: list[tuple[EvidenceSpan, ...]] = [()]
    best: tuple[EvidenceSpan, ...] = ()
    for _ in range(4):
        proposals = set(beam)
        for state in beam:
            for candidate in ranked:
                expanded = merge((*state, candidate))
                if len(expanded) <= fragment_limit and cost(expanded) <= max_bytes:
                    proposals.add(expanded)
        beam = sorted(proposals, key=lambda state: (-utility(state), cost(state), state))[:16]
        if not beam or beam[0] == best:
            break
        best = beam[0]
    return _extend_whitespace(best, texts, render, max_bytes)


def _extend_whitespace(
    spans: tuple[EvidenceSpan, ...],
    texts: Sequence[str],
    render: Callable[[tuple[EvidenceSpan, ...]], str],
    max_bytes: int,
) -> tuple[EvidenceSpan, ...]:
    # Preserve original formatting around a selected sentence when it fits.
    # Otherwise a whole sentence's leading/trailing whitespace could be lost.
    expanded = list(spans)
    for index, span in enumerate(expanded):
        text = texts[span.document]
        start, end = span.start, span.end
        while start > 0 and text[start - 1].isspace():
            start -= 1
        while end < len(text) and text[end].isspace():
            end += 1
        proposal = list(expanded)
        proposal[index] = EvidenceSpan(span.document, start, end)
        if len(render(tuple(proposal)).encode("utf-8")) <= max_bytes:
            expanded = proposal
    return tuple(expanded)


def _query_anchors(text: str, span: EvidenceSpan, terms: frozenset[str], weights: dict[str, float]) -> tuple[int, ...]:
    anchors = []
    for match in _WORDS.finditer(text, span.start, span.end):
        term = _term(match.group())
        if term in terms:
            anchors.append((match.start(), term))
    for term in terms:
        if _CJK.fullmatch(term):
            position = text.find(term, span.start, span.end)
            while position >= 0:
                anchors.append((position, term))
                position = text.find(term, position + 1, span.end)
    counts = Counter(term for position, term in anchors)
    # Repeated generic words must not crowd a rare query match at the tail
    # out of the bounded set of clipping anchors.
    return tuple(
        position
        for position, term in sorted(anchors, key=lambda item: (-weights[item[1]] / counts[item[1]], item[0]))[:32]
    )


__all__ = ["EvidenceSpan", "select_evidence_spans"]
