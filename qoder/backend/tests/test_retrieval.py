"""Retrieval helpers: hit shaping, reciprocal rank fusion, citation formatting."""

from __future__ import annotations

from typing import Any

from app.services.retrieval import _fuse, _row_to_hit, format_citations


def _keyword_hit(chunk_id: str, rank: int, fts_score: float) -> dict[str, Any]:
    return _row_to_hit(
        {
            "chunk_id": chunk_id,
            "doc_id": f"doc_{chunk_id}",
            "chunk_index": 0,
            "page_no": 1,
            "content": f"content-{chunk_id}",
            "doc_title": f"title-{chunk_id}",
            "doc_topic": "3D 场景记忆",
            "doc_file_name": "paper.pdf",
            "fts_score": fts_score,
        },
        rank,
        "keyword",
    )


def _vector_hit(chunk_id: str, rank: int, distance: float) -> dict[str, Any]:
    return _row_to_hit(
        {
            "chunk_id": chunk_id,
            "doc_id": f"doc_{chunk_id}",
            "chunk_index": 0,
            "page_no": 1,
            "content": f"content-{chunk_id}",
            "doc_title": f"title-{chunk_id}",
            "doc_topic": None,
            "doc_file_name": "notes.md",
            "l2_distance": distance,
        },
        rank,
        "vector",
    )


def test_row_to_hit_converts_distance_to_similarity() -> None:
    hit = _vector_hit("a", 1, 0.25)
    assert hit["score"] == 0.8
    assert hit["l2_distance"] == 0.25
    assert hit["mode"] == "vector"
    assert hit["matched_by"] == ["vector"]
    assert hit["fts_score"] is None


def test_row_to_hit_keeps_fulltext_score() -> None:
    hit = _keyword_hit("a", 2, 3.5)
    assert hit["fts_score"] == 3.5
    assert hit["score"] is None
    assert hit["matched_by"] == ["fulltext"]
    assert hit["rank"] == 2


def test_fuse_orders_by_reciprocal_rank_and_records_both_legs() -> None:
    keyword = [_keyword_hit("a", 1, 3.5), _keyword_hit("b", 2, 2.0)]
    vector = [_vector_hit("b", 1, 0.25), _vector_hit("c", 2, 0.5)]

    fused = _fuse(keyword, vector, limit=10)

    assert [hit["chunk_id"] for hit in fused] == ["b", "a", "c"]
    assert [hit["rank"] for hit in fused] == [1, 2, 3]
    assert all(hit["mode"] == "hybrid" for hit in fused)
    assert fused[0]["matched_by"] == ["fulltext", "vector"]
    assert fused[1]["matched_by"] == ["fulltext"]
    assert fused[2]["matched_by"] == ["vector"]
    # b appears in both legs, so its RRF score is the sum of both reciprocals.
    assert fused[0]["rrf_score"] == round(1 / 61 + 1 / 62, 6)
    assert fused[1]["rrf_score"] == round(1 / 61, 6)
    assert fused[2]["rrf_score"] == round(1 / 62, 6)


def test_fuse_fills_missing_scores_from_the_other_leg() -> None:
    fused = _fuse([_keyword_hit("a", 1, 3.5)], [_vector_hit("a", 1, 0.25)], limit=5)
    assert fused[0]["fts_score"] == 3.5
    assert fused[0]["score"] == 0.8
    assert fused[0]["l2_distance"] == 0.25


def test_fuse_respects_limit() -> None:
    keyword = [_keyword_hit(chunk_id, rank, 1.0) for rank, chunk_id in enumerate("abcd", start=1)]
    fused = _fuse(keyword, [], limit=2)
    assert [hit["chunk_id"] for hit in fused] == ["a", "b"]
    assert [hit["rank"] for hit in fused] == [1, 2]


def test_format_citations_uses_page_number_when_present() -> None:
    citations = format_citations([_vector_hit("a", 1, 0.1) | {"page_no": 12}])
    assert citations[0]["location"] == "第 12 页"
    assert citations[0]["page_no"] == 12
    assert citations[0]["title"] == "title-a"
    assert citations[0]["chunk_id"] == "a"


def test_format_citations_marks_markdown_without_pages_as_full_text() -> None:
    hit = _vector_hit("a", 1, 0.1) | {"page_no": None, "doc_file_name": "notes.md"}
    assert format_citations([hit])[0]["location"] == "全文"


def test_format_citations_flags_pdf_chunks_with_no_page() -> None:
    hit = _vector_hit("a", 1, 0.1) | {"page_no": None, "doc_file_name": "scanned.pdf"}
    assert format_citations([hit])[0]["location"] == "未标注页码"


def test_format_citations_truncates_excerpt_and_prefers_rrf_score() -> None:
    hit = _vector_hit("a", 1, 0.1) | {"content": "字" * 900, "rrf_score": 0.0325}
    citation = format_citations([hit])[0]
    assert len(citation["excerpt"]) == 600
    assert citation["score"] == 0.0325
    assert citation["matched_by"] == ["vector"]


def test_format_citations_returns_empty_list_for_no_hits() -> None:
    assert format_citations([]) == []
