"""Retrieval over seekdb: keyword (FULLTEXT), vector (ANN) and hybrid fused search.

Every code path issues real SQL against OceanBase seekdb. Keyword search uses
`MATCH ... AGAINST ... IN NATURAL LANGUAGE MODE` over the parser-selected fulltext index,
vector search uses `ORDER BY l2_distance(...) APPROXIMATE LIMIT k` over the HNSW index, and
hybrid search runs both legs and fuses them with reciprocal rank fusion. Nothing here is
cached, mocked or precomputed.
"""

from __future__ import annotations

import logging
from typing import Any, Literal

from app.db.seekdb import SeekDB
from app.services.embeddings import EmbeddingService, format_vector

logger = logging.getLogger(__name__)

SearchMode = Literal["hybrid", "keyword", "vector"]

_RRF_K = 60.0

# seekdb leg -> the label reported to the UI as `matched_by`.
_LEG_SOURCES = {"keyword": ("fulltext",), "vector": ("vector",)}

_BASE_SELECT = (
    "SELECT c.chunk_id, c.doc_id, c.chunk_index, c.page_no, c.content, "
    "d.title AS doc_title, d.topic AS doc_topic, d.file_name AS doc_file_name"
)
_FROM = " FROM lt_document_chunks c JOIN lt_documents d ON d.doc_id = c.doc_id"
_MATCH_EXPR = "MATCH(c.searchable_text) AGAINST (%s IN NATURAL LANGUAGE MODE)"


def _distance_expr(vector_literal: str) -> str:
    return f"l2_distance(c.embedding, '{vector_literal}')"


def _row_to_hit(row: dict[str, Any], rank: int, mode: str) -> dict[str, Any]:
    distance = row.pop("l2_distance", None)
    fts_score = row.pop("fts_score", None)
    return {
        "rank": rank,
        "mode": mode,
        # Which seekdb leg produced this row. Single-leg searches report themselves so the UI
        # shows the same field in every mode; `_fuse` overwrites it for hybrid results.
        "matched_by": list(_LEG_SOURCES[mode]),
        "score": round(1.0 / (1.0 + float(distance)), 4) if distance is not None else None,
        "l2_distance": round(float(distance), 6) if distance is not None else None,
        "fts_score": round(float(fts_score), 6) if fts_score is not None else None,
        **row,
    }


async def _keyword_leg(
    db: SeekDB, *, project_id: str, query: str, limit: int, doc_id: str | None
) -> list[dict[str, Any]]:
    # Placeholder order follows the statement text: the projected MATCH score comes first,
    # then the WHERE predicates.
    params: list[Any] = [query, project_id]
    where = ["c.project_id = %s"]
    if doc_id:
        where.append("c.doc_id = %s")
        params.append(doc_id)
    where.append(_MATCH_EXPR)
    params.append(query)
    sql = (
        f"{_BASE_SELECT}, {_MATCH_EXPR} AS fts_score{_FROM} "
        f"WHERE {' AND '.join(where)} ORDER BY fts_score DESC, c.chunk_index LIMIT {limit}"
    )
    rows = await db.query(sql, params)
    return [_row_to_hit(row, rank, "keyword") for rank, row in enumerate(rows, start=1)]


async def _vector_leg(
    db: SeekDB, *, project_id: str, vector_literal: str, limit: int, doc_id: str | None
) -> list[dict[str, Any]]:
    params: list[Any] = [project_id]
    where = ["c.project_id = %s"]
    if doc_id:
        where.append("c.doc_id = %s")
        params.append(doc_id)
    distance = _distance_expr(vector_literal)
    sql = (
        f"{_BASE_SELECT}, {distance} AS l2_distance{_FROM} "
        f"WHERE {' AND '.join(where)} ORDER BY {distance} APPROXIMATE LIMIT {limit}"
    )
    rows = await db.query(sql, params)
    return [_row_to_hit(row, rank, "vector") for rank, row in enumerate(rows, start=1)]


async def search_chunks(
    db: SeekDB,
    embeddings: EmbeddingService,
    *,
    project_id: str,
    query: str,
    mode: SearchMode = "hybrid",
    limit: int = 8,
    doc_id: str | None = None,
) -> list[dict[str, Any]]:
    query = query.strip()
    if not query:
        return []
    limit = max(1, min(limit, 50))

    vector_literal: str | None = None
    if mode in {"hybrid", "vector"}:
        vector = await embeddings.embed_one(query)
        vector_literal = format_vector(vector).replace("'", "''")

    if mode == "keyword":
        hits = await _keyword_leg(db, project_id=project_id, query=query, limit=limit, doc_id=doc_id)
    elif mode == "vector":
        assert vector_literal is not None
        hits = await _vector_leg(
            db, project_id=project_id, vector_literal=vector_literal, limit=limit, doc_id=doc_id
        )
    else:
        assert vector_literal is not None
        candidate_limit = min(limit * 3, 60)
        keyword_hits, vector_hits = (
            await _keyword_leg(db, project_id=project_id, query=query, limit=candidate_limit, doc_id=doc_id),
            await _vector_leg(
                db,
                project_id=project_id,
                vector_literal=vector_literal,
                limit=candidate_limit,
                doc_id=doc_id,
            ),
        )
        hits = _fuse(keyword_hits, vector_hits, limit)

    logger.info("seekdb %s search: %d hits for project %s", mode, len(hits), project_id)
    return hits


def _fuse(
    keyword_hits: list[dict[str, Any]], vector_hits: list[dict[str, Any]], limit: int
) -> list[dict[str, Any]]:
    """Reciprocal rank fusion over the two seekdb legs."""
    merged: dict[str, dict[str, Any]] = {}
    for hits, key in ((keyword_hits, "keyword_rank"), (vector_hits, "vector_rank")):
        for hit in hits:
            entry = merged.setdefault(hit["chunk_id"], {**hit, "mode": "hybrid"})
            entry[key] = hit["rank"]
            for field in ("l2_distance", "score", "fts_score"):
                if entry.get(field) is None and hit.get(field) is not None:
                    entry[field] = hit[field]

    fused: list[dict[str, Any]] = []
    for entry in merged.values():
        rrf = 0.0
        for key in ("keyword_rank", "vector_rank"):
            rank = entry.get(key)
            if rank:
                rrf += 1.0 / (_RRF_K + rank)
        entry["rrf_score"] = round(rrf, 6)
        entry["matched_by"] = [
            name for name, key in (("fulltext", "keyword_rank"), ("vector", "vector_rank")) if entry.get(key)
        ]
        fused.append(entry)

    fused.sort(key=lambda item: (-item["rrf_score"], item.get("vector_rank") or 999))
    for rank, entry in enumerate(fused[:limit], start=1):
        entry["rank"] = rank
    return fused[:limit]


async def get_chunk(db: SeekDB, chunk_id: str, project_id: str) -> dict[str, Any] | None:
    rows = await db.query(
        f"{_BASE_SELECT}{_FROM} WHERE c.chunk_id = %s AND c.project_id = %s LIMIT 1",
        (chunk_id, project_id),
    )
    return rows[0] if rows else None


def format_citations(hits: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Shape retrieval hits into citation records shown in the UI."""
    citations = []
    for hit in hits:
        page = hit.get("page_no")
        if page:
            location = f"第 {page} 页"
        elif str(hit.get("doc_file_name", "")).lower().endswith((".md", ".markdown", ".txt")):
            location = "全文"
        else:
            location = "未标注页码"
        citations.append(
            {
                "chunk_id": hit["chunk_id"],
                "doc_id": hit["doc_id"],
                "title": hit.get("doc_title"),
                "topic": hit.get("doc_topic"),
                "page_no": page,
                "location": location,
                "excerpt": hit["content"][:600],
                "score": hit.get("rrf_score") or hit.get("score"),
                "mode": hit.get("mode"),
                "matched_by": hit.get("matched_by"),
            }
        )
    return citations
