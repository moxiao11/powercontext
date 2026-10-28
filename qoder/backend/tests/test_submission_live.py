"""Additional real-service checks: PDF page citations and corrected session recovery."""

import uuid
from pathlib import Path

import httpx
import pytest

from tests.conftest import live_base_url, live_enabled

pytestmark = pytest.mark.skipif(not live_enabled(), reason="set LABTRACE_LIVE=1 for real services")


@pytest.fixture
def workspace():
    with httpx.Client(base_url=live_base_url(), timeout=120) as client:
        response = client.post("/api/projects", json={"name": f"提交验证（示例）{uuid.uuid4().hex[:8]}"})
        response.raise_for_status()
        project = response.json()
        try:
            yield client, project
        finally:
            cleanup = client.delete(f"/api/projects/{project['project_id']}")
            cleanup.raise_for_status()


def test_original_pdf_is_searchable_with_exact_page_and_project_isolation(workspace):
    client, project = workspace
    project_id = project["project_id"]
    fixture = Path(__file__).resolve().parents[2] / "sample-data/papers/sample-pdf-eqa.pdf"
    response = client.post(
        "/api/documents/upload",
        data={"project_id": project_id, "title": "原创 PDF 示例"},
        files={"file": (fixture.name, fixture.read_bytes(), "application/pdf")},
    )
    response.raise_for_status()
    document = response.json()
    assert document["page_count"] == 2
    result = client.post(
        "/api/search",
        json={
            "project_id": project_id,
            "doc_id": document["doc_id"],
            "query": "ROOMMERGE2026",
            "mode": "keyword",
        },
    )
    result.raise_for_status()
    citations = result.json()["citations"]
    assert citations and all(item["page_no"] == 2 for item in citations)
    assert all("ROOMMERGE2026" in item["excerpt"] for item in citations)
    isolated = client.post(
        "/api/search",
        json={
            "project_id": "prj_nonexistent_isolation_probe",
            "query": "ROOMMERGE2026",
            "mode": "hybrid",
        },
    )
    isolated.raise_for_status()
    assert isolated.json()["total"] == 0
    chunks = client.get(f"/api/documents/{document['doc_id']}/chunks", params={"project_id": project_id})
    assert {item["page_no"] for item in chunks.json()["chunks"]} == {1, 2}


def test_new_http_session_recovers_correction_and_conflicting_edit_does_not_win(workspace):
    client, project = workspace
    project_id = project["project_id"]
    saved = client.post(
        "/api/memory/save-progress",
        json={
            "project_id": project_id,
            "session_id": uuid.uuid4().hex,
            "summary": "验证跨会话研究计划",
            "next_steps": ["原计划：使用外观合并"],
            "decisions": [{"text": "比较房间约束", "reason": "避免跨房间误合并"}],
            "failures": [{"text": "旧方案失败", "reason": "视角变化导致误匹配"}],
            "open_questions": ["还需要测量峰值内存"],
        },
    )
    saved.raise_for_status()
    assert saved.json()["status"] == "saved"
    assert saved.json()["handoff"]["status"] == "committed"
    listing = client.get("/api/memory", params={"project_id": project_id}).json()
    entry = next(item for item in listing["entries"] if item["kind"] == "next_action")
    updated = client.post(
        "/api/memory/revise",
        json={
            "project_id": project_id,
            "citation": entry["citation"],
            "kind": "next_action",
            "text": "修订计划：先验证房间 ID 硬约束",
            "reason": "用户确认",
        },
    )
    updated.raise_for_status()
    stale = client.post(
        "/api/memory/revise",
        json={
            "project_id": project_id,
            "citation": entry["citation"],
            "kind": "next_action",
            "text": "陈旧覆盖",
        },
    )
    assert stale.status_code >= 400
    with httpx.Client(base_url=live_base_url(), timeout=120) as fresh_session:
        restored = fresh_session.post("/api/memory/restore", params={"project_id": project_id})
        restored.raise_for_status()
    data = restored.json()
    assert "修订计划：先验证房间 ID 硬约束" in data["answer"]
    assert "原计划：使用外观合并" not in data["answer"]
    assert "避免跨房间误合并" in data["answer"]
    assert "视角变化导致误匹配" in data["answer"]
    assert data["handoff"]["content"]["omissions"][0]["text"] == "还需要测量峰值内存"
    assert "原计划" in data["handoff"]["content"]["next_action"]["text"]
