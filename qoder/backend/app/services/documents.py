"""Document ingestion: extraction, paragraph chunking with page numbers, seekdb storage."""

from __future__ import annotations

import logging
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from app.db.seekdb import SeekDB
from app.services.embeddings import EmbeddingService, format_vector

logger = logging.getLogger(__name__)

ALLOWED_EXTENSIONS = {".pdf", ".md", ".markdown", ".txt"}
PDF_MAGIC = b"%PDF-"
DEFAULT_MAX_CHUNK_CHARS = 700
MIN_CHUNK_CHARS = 120

_WHITESPACE_RE = re.compile(r"[ \t]+")
_HEADING_RE = re.compile(r"(?m)^(?=#{1,6}\s)")


class DocumentError(ValueError):
    pass


@dataclass
class ExtractedPage:
    page_no: int | None
    text: str


@dataclass
class DocumentChunk:
    chunk_index: int
    page_no: int | None
    content: str


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _searchable_text(title: str, topic: str | None, content: str) -> str:
    """Fulltext payload for one chunk: document metadata plus the chunk body."""
    parts = [title, topic or "", content]
    return "\n".join(part.strip() for part in parts if part and part.strip())


def validate_upload(filename: str, data: bytes, max_bytes: int) -> str:
    if len(data) > max_bytes:
        raise DocumentError(f"file exceeds the {max_bytes // (1024 * 1024)} MB upload limit")
    if not filename:
        raise DocumentError("missing file name")
    suffix = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if suffix not in ALLOWED_EXTENSIONS:
        raise DocumentError(f"unsupported file type '{suffix or filename}'; allowed: pdf, md, txt")
    if suffix == ".pdf" and not data.startswith(PDF_MAGIC):
        raise DocumentError("file has a .pdf extension but is not a valid PDF")
    return "pdf" if suffix == ".pdf" else ("markdown" if suffix in {".md", ".markdown"} else "text")


def extract_pages(data: bytes, file_type: str) -> list[ExtractedPage]:
    if file_type == "pdf":
        return _extract_pdf(data)
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise DocumentError("text file is not valid UTF-8") from exc
    if not text.strip():
        raise DocumentError("document is empty")
    return [ExtractedPage(page_no=None, text=text)]


def _extract_pdf(data: bytes) -> list[ExtractedPage]:
    try:
        import pymupdf
    except ImportError as exc:  # pragma: no cover
        raise DocumentError("PyMuPDF is not installed") from exc
    try:
        document = pymupdf.open(stream=data, filetype="pdf")
    except Exception as exc:
        raise DocumentError(f"cannot parse PDF: {exc}") from exc
    pages: list[ExtractedPage] = []
    try:
        for index, page in enumerate(document, start=1):
            text = page.get_text("text") or ""
            text = _WHITESPACE_RE.sub(" ", text)
            if text.strip():
                pages.append(ExtractedPage(page_no=index, text=text))
    finally:
        document.close()
    if not pages:
        raise DocumentError("PDF contains no extractable text (scanned image?)")
    return pages


def _append_chunk(chunks: list[DocumentChunk], page_no: int | None, content: str, max_chars: int) -> None:
    content = content.strip()
    if not content:
        return
    if len(content) < MIN_CHUNK_CHARS and chunks and chunks[-1].page_no == page_no:
        merged = f"{chunks[-1].content}\n\n{content}"
        if len(merged) <= max_chars * 2:
            chunks[-1] = DocumentChunk(chunk_index=chunks[-1].chunk_index, page_no=page_no, content=merged)
            return
    chunks.append(DocumentChunk(chunk_index=len(chunks), page_no=page_no, content=content))


def chunk_pages(pages: list[ExtractedPage], max_chars: int = DEFAULT_MAX_CHUNK_CHARS) -> list[DocumentChunk]:
    """Split page text on heading and paragraph boundaries, keeping each chunk's page number.

    Short trailing fragments are merged into the previous chunk rather than dropped so that
    no source text is lost from the retrieval index.
    """
    chunks: list[DocumentChunk] = []
    for page in pages:
        text = _HEADING_RE.sub("\n\n", page.text)
        paragraphs = [part.strip() for part in re.split(r"\n\s*\n|\r\n\s*\r\n", text) if part.strip()]
        buffer: list[str] = []
        buffer_len = 0

        for paragraph in paragraphs:
            if len(paragraph) > max_chars:
                _append_chunk(chunks, page.page_no, "\n\n".join(buffer), max_chars)
                buffer, buffer_len = [], 0
                for start in range(0, len(paragraph), max_chars):
                    _append_chunk(chunks, page.page_no, paragraph[start : start + max_chars], max_chars)
                continue
            if buffer_len + len(paragraph) > max_chars:
                _append_chunk(chunks, page.page_no, "\n\n".join(buffer), max_chars)
                buffer, buffer_len = [], 0
            buffer.append(paragraph)
            buffer_len += len(paragraph) + 2
        _append_chunk(chunks, page.page_no, "\n\n".join(buffer), max_chars)

    for index, chunk in enumerate(chunks):
        chunk.chunk_index = index
    return chunks


async def ingest_document(
    db: SeekDB,
    embeddings: EmbeddingService,
    *,
    project_id: str,
    title: str,
    topic: str | None,
    filename: str,
    data: bytes,
    max_bytes: int,
    max_chunk_chars: int = DEFAULT_MAX_CHUNK_CHARS,
) -> dict[str, Any]:
    file_type = validate_upload(filename, data, max_bytes)
    pages = extract_pages(data, file_type)
    chunks = chunk_pages(pages, max_chunk_chars)
    if not chunks:
        raise DocumentError("no text chunks could be produced from this document")

    vectors = await embeddings.embed([chunk.content for chunk in chunks])
    doc_id = f"doc_{uuid.uuid4().hex[:16]}"
    now = _now()
    statements: list[tuple[str, tuple[Any, ...]]] = [
        (
            (
                "INSERT INTO lt_documents (doc_id, project_id, title, topic, file_name, file_type, "
                "page_count, char_count, chunk_count, status, created_at) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)"
            ),
            (
                doc_id,
                project_id,
                title,
                topic,
                filename,
                file_type,
                len(pages),
                sum(len(page.text) for page in pages),
                len(chunks),
                "ready",
                now,
            ),
        )
    ]
    for chunk, vector in zip(chunks, vectors, strict=True):
        statements.append(
            (
                (
                    "INSERT INTO lt_document_chunks "
                    "(chunk_id, doc_id, project_id, chunk_index, page_no, content, searchable_text, "
                    "embedding, created_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)"
                ),
                (
                    f"chk_{uuid.uuid4().hex[:16]}",
                    doc_id,
                    project_id,
                    chunk.chunk_index,
                    chunk.page_no,
                    chunk.content,
                    _searchable_text(title, topic, chunk.content),
                    format_vector(vector),
                    now,
                ),
            )
        )
    await db.execute_batch(statements)
    logger.info("ingested document %s (%d chunks)", doc_id, len(chunks))
    return {
        "doc_id": doc_id,
        "project_id": project_id,
        "title": title,
        "topic": topic,
        "file_name": filename,
        "file_type": file_type,
        "page_count": len(pages),
        "chunk_count": len(chunks),
        "embedding_provider": embeddings.provider,
        "created_at": now.isoformat(),
    }


async def list_documents(db: SeekDB, project_id: str, topic: str | None = None) -> list[dict[str, Any]]:
    sql = (
        "SELECT doc_id, project_id, title, topic, file_name, file_type, page_count, "
        "char_count, chunk_count, status, created_at FROM lt_documents WHERE project_id = %s"
    )
    params: list[Any] = [project_id]
    if topic:
        sql += " AND topic = %s"
        params.append(topic)
    sql += " ORDER BY created_at DESC"
    rows = await db.query(sql, params)
    for row in rows:
        row["created_at"] = _iso(row.get("created_at"))
    return rows


async def get_document_chunks(db: SeekDB, doc_id: str, project_id: str) -> list[dict[str, Any]]:
    rows = await db.query(
        "SELECT chunk_id, chunk_index, page_no, content FROM lt_document_chunks "
        "WHERE doc_id = %s AND project_id = %s ORDER BY chunk_index",
        (doc_id, project_id),
    )
    return rows


async def delete_document(db: SeekDB, doc_id: str, project_id: str) -> bool:
    await db.execute(
        "DELETE FROM lt_document_chunks WHERE doc_id = %s AND project_id = %s", (doc_id, project_id)
    )
    affected = await db.execute(
        "DELETE FROM lt_documents WHERE doc_id = %s AND project_id = %s", (doc_id, project_id)
    )
    return bool(affected)


def _iso(value: Any) -> str | None:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value) if value is not None else None
