from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from app.api.deps import DbDep, EmbeddingsDep
from app.config import get_settings
from app.schemas import SearchRequest
from app.services import documents as doc_service
from app.services import retrieval
from app.services.documents import DocumentError

router = APIRouter(prefix="/api", tags=["library"])


@router.post("/documents/upload")
async def upload_document(
    db: DbDep,
    embeddings: EmbeddingsDep,
    project_id: Annotated[str, Form()],
    file: Annotated[UploadFile, File()],
    title: Annotated[str | None, Form()] = None,
    topic: Annotated[str | None, Form()] = None,
) -> dict[str, Any]:
    settings = get_settings()
    data = await file.read(settings.max_upload_bytes + 1)
    filename = file.filename or "unnamed"
    try:
        result = await doc_service.ingest_document(
            db,
            embeddings,
            project_id=project_id,
            title=(title or filename).strip(),
            topic=topic.strip() if topic else None,
            filename=filename,
            data=data,
            max_bytes=settings.max_upload_bytes,
            max_chunk_chars=settings.document_chunk_max_chars,
        )
    except DocumentError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return result


@router.get("/documents")
async def list_documents(db: DbDep, project_id: str, topic: str | None = None) -> dict[str, Any]:
    rows = await doc_service.list_documents(db, project_id, topic)
    topics = sorted({row["topic"] for row in rows if row.get("topic")})
    return {"documents": rows, "topics": topics, "total": len(rows)}


@router.get("/documents/{doc_id}/chunks")
async def get_document_chunks(db: DbDep, doc_id: str, project_id: str) -> dict[str, Any]:
    chunks = await doc_service.get_document_chunks(db, doc_id, project_id)
    if not chunks:
        raise HTTPException(status_code=404, detail="document not found in this project")
    return {"doc_id": doc_id, "chunks": chunks, "total": len(chunks)}


@router.delete("/documents/{doc_id}")
async def delete_document(db: DbDep, doc_id: str, project_id: str) -> dict[str, Any]:
    deleted = await doc_service.delete_document(db, doc_id, project_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="document not found in this project")
    return {"deleted": True, "doc_id": doc_id}


@router.post("/search")
async def search_documents(db: DbDep, embeddings: EmbeddingsDep, payload: SearchRequest) -> dict[str, Any]:
    hits = await retrieval.search_chunks(
        db,
        embeddings,
        project_id=payload.project_id,
        query=payload.query,
        mode=payload.mode,
        limit=payload.limit,
        doc_id=payload.doc_id,
    )
    return {
        "query": payload.query,
        "mode": payload.mode,
        "engine": f"OceanBase seekdb {db.version}",
        "sql_mode": {
            "hybrid": "seekdb FULLTEXT (MATCH...AGAINST) + VECTOR ANN (l2_distance APPROXIMATE), RRF fusion",
            "keyword": "seekdb FULLTEXT MATCH...AGAINST IN NATURAL LANGUAGE MODE",
            "vector": "seekdb VECTOR ANN ORDER BY l2_distance(...) APPROXIMATE",
        }[payload.mode],
        "hits": hits,
        "citations": retrieval.format_citations(hits),
        "total": len(hits),
    }
