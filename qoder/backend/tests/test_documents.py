"""Document validation, extraction and chunking."""

from __future__ import annotations

import pytest

from app.services.documents import (
    DocumentError,
    ExtractedPage,
    _searchable_text,
    chunk_pages,
    extract_pages,
    validate_upload,
)


def test_validate_upload_accepts_supported_types() -> None:
    assert validate_upload("notes.md", b"# title", 1024) == "markdown"
    assert validate_upload("notes.MARKDOWN", b"# title", 1024) == "markdown"
    assert validate_upload("notes.txt", b"plain", 1024) == "text"
    assert validate_upload("paper.pdf", b"%PDF-1.7\n", 1024) == "pdf"


@pytest.mark.parametrize("filename", ["paper.exe", "paper", "archive.zip", "paper.pdf.html"])
def test_validate_upload_rejects_unsupported_extension(filename: str) -> None:
    with pytest.raises(DocumentError, match="unsupported file type"):
        validate_upload(filename, b"%PDF-1.7", 1024)


def test_validate_upload_rejects_oversize_file() -> None:
    with pytest.raises(DocumentError, match="upload limit"):
        validate_upload("notes.md", b"x" * 2048, 1024)


def test_validate_upload_rejects_fake_pdf() -> None:
    with pytest.raises(DocumentError, match="not a valid PDF"):
        validate_upload("paper.pdf", b"<!DOCTYPE html>", 1024)


def test_validate_upload_rejects_missing_filename() -> None:
    with pytest.raises(DocumentError, match="missing file name"):
        validate_upload("", b"body", 1024)


def test_extract_pages_reads_utf8_text() -> None:
    pages = extract_pages("三段式场景记忆综述".encode(), "text")
    assert len(pages) == 1
    assert pages[0].page_no is None
    assert pages[0].text == "三段式场景记忆综述"


def test_extract_pages_rejects_non_utf8() -> None:
    with pytest.raises(DocumentError, match="not valid UTF-8"):
        extract_pages(b"\xff\xfe\x00bad", "text")


def test_extract_pages_rejects_empty_document() -> None:
    with pytest.raises(DocumentError, match="empty"):
        extract_pages(b"   \n\t ", "text")


def test_chunk_pages_keeps_page_numbers() -> None:
    pages = [
        ExtractedPage(page_no=1, text="第一段内容。\n\n第二段内容。"),
        ExtractedPage(page_no=2, text="# 小节标题\n\n第二页的正文段落。"),
    ]
    chunks = chunk_pages(pages, max_chars=700)

    assert [chunk.page_no for chunk in chunks] == [1, 2]
    assert [chunk.chunk_index for chunk in chunks] == [0, 1]
    assert "第一段内容。" in chunks[0].content
    assert "第二页的正文段落。" in chunks[1].content
    assert "小节标题" in chunks[1].content


def test_chunk_pages_splits_long_paragraph_without_losing_text() -> None:
    paragraph = "记忆单元" * 800  # 3200 chars, no whitespace so slices rejoin exactly
    pages = [ExtractedPage(page_no=7, text=paragraph)]

    chunks = chunk_pages(pages, max_chars=700)

    assert len(chunks) == 5
    assert all(chunk.page_no == 7 for chunk in chunks)
    assert "".join(chunk.content for chunk in chunks) == paragraph
    assert [chunk.chunk_index for chunk in chunks] == list(range(len(chunks)))


def test_chunk_pages_merges_short_trailing_fragment_instead_of_dropping_it() -> None:
    long_paragraph = "长" * 1500
    pages = [ExtractedPage(page_no=3, text=f"{long_paragraph}\n\n短尾巴")]

    chunks = chunk_pages(pages, max_chars=700)

    assert len(chunks) == 2
    assert chunks[-1].content.endswith("短尾巴")
    assert all(chunk.page_no == 3 for chunk in chunks)


def test_chunk_pages_returns_nothing_for_blank_input() -> None:
    assert chunk_pages([ExtractedPage(page_no=1, text="  \n\n  ")], max_chars=700) == []


def test_searchable_text_combines_metadata_and_body() -> None:
    assert _searchable_text("标题", "3D 场景记忆", "正文") == "标题\n3D 场景记忆\n正文"
    assert _searchable_text("标题", None, "正文") == "标题\n正文"
