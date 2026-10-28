"""Live end-to-end suite against a running LabTrace backend.

Skipped by default. Run it with a backend that is already connected to a real
OceanBase seekdb and a real PowerContext server:

    LABTRACE_LIVE=1 LABTRACE_API_URL=http://127.0.0.1:8100 pytest tests/test_live_api.py -v

Nothing here is stubbed: every assertion below was produced by real SQL against
seekdb (FULLTEXT MATCH...AGAINST, VECTOR l2_distance ANN) and real HTTP calls to
PowerContext (Source capture, Memory remember/list/revise/retire, Handoff
finalize/commit/continue, PreparedContext). The suite creates one throwaway
project and deletes it at the end, so it is repeatable.
"""

from __future__ import annotations

import uuid
from typing import Any

import httpx
import pytest

from tests.conftest import live_base_url, live_enabled

pytestmark = pytest.mark.skipif(not live_enabled(), reason="set LABTRACE_LIVE=1 to run the live suite")

RUN_ID = uuid.uuid4().hex[:8]

SAMPLE_DOC = """# 示例文档：三段式 3D 场景记忆（自动化测试用示例数据）

本文件由 LabTrace 的 pytest 端到端测试生成，属于示例资料，不是真实科研成果，
也不代表任何已发表工作的实验结论。文中的数字仅用于验证检索、引用与周报链路。

## 一、逐帧缓冲

逐帧缓冲（frame buffer）把最近 N 帧的原始特征直接保留在显存中，问答时把全部帧特征
拼接后送入解码器。它的优点是不做任何信息取舍，因此对时序细节最敏感；缺点也很明确：
显存随帧数线性增长。在 64 帧设置下峰值显存达到 11.8 GB，推理延迟 480 毫秒，
而 EQA-Long 上的准确率只有 52.4%，其中依赖长程历史的问题准确率仅 39.8%。
这说明单纯堆叠帧数并不能解决长时序问题，反而会因为无关帧的干扰而稀释有效信息。

## 二、物体摘要记忆

物体摘要记忆（object-level summary memory）为每个检测到的物体保存一条结构化记录，
记录内容包括类别、三维位置、外观嵌入与最近一次观测时间。合并策略使用 IoU 阈值 0.5，
并对每个房间保留 top-k 为 8 的物体。相比逐帧缓冲，它把峰值显存从 11.8 GB 降到 4.2 GB，
同时把 EQA-Long 上的准确率从 41.2% 提升到 58.7%，依赖长程历史的问题准确率提升到 54.1%。
计数类问题的错误率仍然偏高，达到 0.31，说明同一物体被重复记录的情况依然存在。

## 三、全局外观嵌入重识别

全局外观嵌入重识别在合并同一物体的多条记忆时，用外观嵌入的余弦相似度作为判据，
阈值设为 0.85。实验显示该判据对视角变化过于敏感：同一物体在不同视角下的嵌入距离
经常超过阈值，导致本该合并的记忆被拆开；不同物体在相似视角下反而被误合并。
结果是准确率下降到 53.9%，计数错误率没有减少，因此该方案被放弃。
失败的根本原因是外观嵌入缺乏视角不变性，而不是阈值调得不够精细。

## 四、房间 ID 硬约束合并

房间 ID 硬约束合并先要求两条记忆位于同一房间，再用多视角平均嵌入做二次确认。
多视角平均把同一物体在不同视角下的嵌入取均值，从而降低单次观测的视角噪声。
该策略是下一步要实现的方向，目标是在不增加显存的前提下把计数类问题的错误率
从 0.31 降到 0.15 以下，并在 EQA-Long 的计数子集上单独复测。
"""


@pytest.fixture(scope="module")
def client() -> Any:
    with httpx.Client(base_url=live_base_url(), timeout=120.0) as http:
        yield http


@pytest.fixture(scope="module")
def project(client: httpx.Client) -> Any:
    response = client.post(
        "/api/projects",
        json={
            "name": f"自动化测试项目 {RUN_ID}",
            "description": "pytest 端到端测试创建的临时项目（示例数据，测试结束后自动删除）",
            "research_profile": "研究方向：Embodied Question Answering 与 3D 场景记忆（测试用示例）",
        },
    )
    assert response.status_code == 200, response.text
    created = response.json()
    assert created["project_id"].startswith("prj_")
    assert created["pc_scope_id"], "project must be backed by a real PowerContext scope"
    try:
        yield created
    finally:
        deleted = client.delete(f"/api/projects/{created['project_id']}")
        assert deleted.status_code == 200, deleted.text
        body = deleted.json()
        assert body["deleted"] is True
        assert body["memory_errors"] == [], body["memory_errors"]


def test_01_health_reports_real_service_versions(client: httpx.Client) -> None:
    body = client.get("/api/health").json()
    assert body["seekdb"]["connected"] is True
    assert "seekdb" in body["seekdb"]["version"]
    assert body["powercontext"]["reachable"] is True
    assert body["powercontext"]["ready"] is True
    # The LLM is optional; the report only has to say honestly whether it is configured.
    assert isinstance(body["llm"]["configured"], bool)
    assert body["embedding"]["dimension"] > 0


def test_02_meta_exposes_runtime_limits_without_leaking_secrets(client: httpx.Client) -> None:
    body = client.get("/api/meta").json()
    assert body["app"] == "LabTrace"
    assert body["max_upload_mb"] >= 1
    assert body["embedding_dimension"] > 0
    assert body["embedding_provider"] in {"openai-compatible", "local-hash-fallback"}
    assert body["seekdb_mode"] in {"embedded", "remote"}
    # Only non-secret runtime facts are published to the browser.
    serialized = str(body).lower()
    for forbidden in ("api_key", "password", "token", "authorization"):
        assert forbidden not in serialized


def test_03_upload_rejects_unsupported_and_oversized_files(client: httpx.Client, project: dict) -> None:
    bad_type = client.post(
        "/api/documents/upload",
        data={"project_id": project["project_id"]},
        files={"file": ("payload.exe", b"MZ\x90\x00", "application/octet-stream")},
    )
    assert bad_type.status_code == 400
    assert "unsupported file type" in bad_type.json()["detail"]

    fake_pdf = client.post(
        "/api/documents/upload",
        data={"project_id": project["project_id"]},
        files={"file": ("paper.pdf", b"<!DOCTYPE html>", "application/pdf")},
    )
    assert fake_pdf.status_code == 400
    assert "not a valid PDF" in fake_pdf.json()["detail"]


def test_04_upload_stores_chunks_in_seekdb(client: httpx.Client, project: dict) -> None:
    response = client.post(
        "/api/documents/upload",
        data={
            "project_id": project["project_id"],
            "title": "三段式 3D 场景记忆（示例）",
            "topic": "场景记忆",
        },
        files={"file": ("sample-scene-memory.md", SAMPLE_DOC.encode(), "text/markdown")},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["doc_id"].startswith("doc_")
    assert body["chunk_count"] >= 2
    assert body["page_count"] >= 1
    assert body["embedding_provider"]
    assert body["file_type"] == "markdown"
    project["doc_id"] = body["doc_id"]

    chunks = client.get(
        f"/api/documents/{body['doc_id']}/chunks", params={"project_id": project["project_id"]}
    ).json()
    assert chunks["total"] == body["chunk_count"]
    assert chunks["chunks"][0]["content"]
    assert [chunk["chunk_index"] for chunk in chunks["chunks"]] == list(range(chunks["total"]))
    # Chunking must not drop source text: every section of the upload is still retrievable.
    indexed = "".join(chunk["content"] for chunk in chunks["chunks"])
    for section in ("逐帧缓冲", "物体摘要记忆", "全局外观嵌入重识别", "房间 ID 硬约束合并"):
        assert section in indexed


def test_05_documents_are_isolated_per_project(client: httpx.Client, project: dict) -> None:
    listing = client.get("/api/documents", params={"project_id": project["project_id"]}).json()
    assert listing["total"] == 1
    assert listing["topics"] == ["场景记忆"]
    stored = listing["documents"][0]
    assert stored["doc_id"] == project["doc_id"]
    # Markdown is stored verbatim, so the recorded size must equal what was uploaded.
    assert stored["char_count"] == len(SAMPLE_DOC)
    assert stored["status"] == "ready"

    other = client.get("/api/documents", params={"project_id": "prj_does_not_exist"}).json()
    assert other["total"] == 0

    chunks = client.get(
        f"/api/documents/{project['doc_id']}/chunks", params={"project_id": "prj_does_not_exist"}
    )
    assert chunks.status_code == 404


def test_06_hybrid_search_runs_both_seekdb_legs(client: httpx.Client, project: dict) -> None:
    body = client.post(
        "/api/search",
        json={
            "project_id": project["project_id"],
            "query": "全局外观嵌入重识别为什么被放弃",
            "mode": "hybrid",
            "limit": 5,
        },
    ).json()

    assert "seekdb" in body["engine"]
    assert "FULLTEXT" in body["sql_mode"]
    assert "APPROXIMATE" in body["sql_mode"]
    assert body["total"] >= 1
    hit = body["hits"][0]
    assert hit["matched_by"]
    assert hit["chunk_id"].startswith("chk_")
    citation = body["citations"][0]
    assert citation["doc_id"] == project["doc_id"]
    assert citation["title"] == "三段式 3D 场景记忆（示例）"
    assert citation["excerpt"]


def test_07_keyword_and_vector_search_report_their_own_sql(client: httpx.Client, project: dict) -> None:
    keyword = client.post(
        "/api/search",
        json={"project_id": project["project_id"], "query": "房间 ID 硬约束", "mode": "keyword"},
    ).json()
    assert "MATCH...AGAINST" in keyword["sql_mode"]
    assert keyword["total"] >= 1
    assert all("fulltext" in hit["matched_by"] for hit in keyword["hits"])

    vector = client.post(
        "/api/search",
        json={"project_id": project["project_id"], "query": "显存占用下降", "mode": "vector"},
    ).json()
    assert "l2_distance" in vector["sql_mode"]
    assert vector["total"] >= 1
    assert all(hit["l2_distance"] is not None for hit in vector["hits"])


def test_08_search_returns_nothing_rather_than_inventing_hits(client: httpx.Client, project: dict) -> None:
    body = client.post(
        "/api/search",
        json={
            "project_id": project["project_id"],
            # No token of this query appears in the corpus. Note that the ik parser does index
            # particles such as 的, so an off-topic probe must avoid them (see docs/TECH_INTEGRATION.md).
            "query": "量子退火催化剂转化率 zzqx",
            "mode": "keyword",
        },
    ).json()
    assert body["total"] == 0
    assert body["hits"] == []
    assert body["citations"] == []


def test_09_experiment_records_round_trip(client: httpx.Client, project: dict) -> None:
    response = client.post(
        "/api/experiments",
        json={
            "project_id": project["project_id"],
            "name": "HSM v2 全局外观嵌入重识别（示例）",
            "objective": "验证外观嵌入能否合并同一物体的多条记忆",
            "hypothesis": "同类物体的外观嵌入具备足够区分度",
            "method": "余弦相似度阈值 0.85 合并",
            "model_config": {"detector": "example-det", "threshold": 0.85},
            "dataset": "EQA-Long",
            "result_summary": "准确率下降到 53.9%，计数错误未减少",
            "metrics": {"accuracy": 53.9, "vram_gb": 4.6},
            "issues": "同一物体被拆成多条记忆",
            "failure_reason": "外观嵌入对视角变化过于敏感，阈值 0.85 过严",
            "next_steps": "实现房间 ID 硬约束合并\n在 EQA-Long 上复测计数类问题",
            "status": "abandoned",
            "log_markdown": "## 训练日志（示例）\n- epoch 1: accuracy 0.41",
        },
    )
    assert response.status_code == 200, response.text
    created = response.json()
    assert created["experiment_id"].startswith("exp_")
    assert created["metrics"] == {"accuracy": 53.9, "vram_gb": 4.6}
    assert created["model_config"] == {"detector": "example-det", "threshold": 0.85}
    assert "searchable_text" not in created
    project["experiment_id"] = created["experiment_id"]

    baseline = client.post(
        "/api/experiments",
        json={
            "project_id": project["project_id"],
            "name": "HSM v1 物体摘要记忆（示例）",
            "dataset": "EQA-Long",
            "metrics": {"accuracy": 58.7, "vram_gb": 4.2},
            "result_summary": "准确率 58.7%，显存 4.2 GB",
            "status": "completed",
        },
    ).json()
    project["baseline_id"] = baseline["experiment_id"]


def test_10_experiment_search_answers_why_a_plan_was_dropped(client: httpx.Client, project: dict) -> None:
    body = client.post(
        "/api/experiments/search",
        json={"project_id": project["project_id"], "query": "为什么放弃外观嵌入方案", "limit": 5},
    ).json()
    assert "MATCH" in body["sql_mode"]
    assert body["total"] >= 1
    names = [row["name"] for row in body["experiments"]]
    assert any("外观嵌入" in name for name in names)
    matched = next(row for row in body["experiments"] if "外观嵌入" in row["name"])
    assert matched["failure_reason"]
    assert matched["relevance"] > 0


def test_11_comparison_and_best_metric_use_stored_numbers(client: httpx.Client, project: dict) -> None:
    compare = client.get(
        "/api/experiments/compare",
        params={
            "project_id": project["project_id"],
            "left": project["baseline_id"],
            "right": project["experiment_id"],
        },
    ).json()
    deltas = {item["metric"]: item["delta"] for item in compare["metric_deltas"]}
    assert deltas["accuracy"] == pytest.approx(-4.8)
    assert deltas["vram_gb"] == pytest.approx(0.4)
    assert {item["field"] for item in compare["differences"]} >= {"name", "status"}

    best = client.get(
        "/api/experiments/best",
        params={"project_id": project["project_id"], "metric": "accuracy", "higher_is_better": "true"},
    ).json()
    assert best["best"]["experiment_id"] == project["baseline_id"]

    missing = client.get(
        "/api/experiments/best",
        params={"project_id": project["project_id"], "metric": "latency_ms"},
    ).json()
    assert missing["best"] is None
    assert "没有实验记录了指标 latency_ms" in missing["note"]


def test_12_json_import_rejects_cross_project_records(client: httpx.Client, project: dict) -> None:
    response = client.post(
        "/api/experiments/import",
        params={"project_id": project["project_id"]},
        json=[{"name": "外部记录", "project_id": "prj_someone_else"}],
    )
    assert response.status_code == 400
    assert "must belong to the target project" in response.json()["detail"]


def test_13_experiment_to_memory_tags_the_seekdb_record(client: httpx.Client, project: dict) -> None:
    response = client.post(
        f"/api/experiments/{project['experiment_id']}/to-memory",
        json={"project_id": project["project_id"], "include_failure": True},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["scope_id"] == project["pc_scope_id"]
    assert body["evidence"]["experiment_id"] == project["experiment_id"]
    assert body["written"], "an abandoned experiment with a failure reason must produce memories"

    kinds = {entry["kind"] for entry in body["written"]}
    assert {"progress", "failure", "next_action"} <= kinds
    tag = f" [exp:{project['experiment_id']}]"
    # reason is write-only in PowerContext, so the traceable link lives in the entry text.
    assert all(entry["text"].endswith(tag) for entry in body["written"])
    assert all(entry["citation"]["entry_id"].startswith("mem_ent_") for entry in body["written"])


def test_14_memory_listing_is_grouped_by_kind(client: httpx.Client, project: dict) -> None:
    body = client.get("/api/memory", params={"project_id": project["project_id"]}).json()
    assert body["scope_id"] == project["pc_scope_id"]
    assert body["total"] >= 3
    assert set(body["grouped"]) == {
        "research_profile",
        "project_context",
        "decision",
        "failure",
        "progress",
        "next_action",
    }
    assert body["grouped"]["failure"]
    assert body["grouped"]["failure"][0]["kind_label"] == "失败记录"


def test_15_memory_search_reports_fts_mode_and_may_miss(client: httpx.Client, project: dict) -> None:
    body = client.post(
        "/api/memory/search",
        json={"project_id": project["project_id"], "query": "外观嵌入", "limit": 5},
    ).json()
    assert body["mode"] == "fts"
    assert isinstance(body["hits"], list)

    missed = client.post(
        "/api/memory/search",
        json={"project_id": project["project_id"], "query": "zzqx-not-in-any-memory", "limit": 5},
    ).json()
    assert missed["hits"] == []


def test_16_memory_can_be_revised_and_retired(client: httpx.Client, project: dict) -> None:
    written = client.post(
        "/api/memory",
        json={
            "project_id": project["project_id"],
            "kind": "decision",
            "text": "待纠正的决策：继续使用全局外观嵌入（示例）",
            "reason": "自动化测试写入",
            "evidence": {"origin": "pytest-live"},
        },
    ).json()
    citation = written["citation"]
    assert written["version"] == 1

    revised = client.post(
        "/api/memory/revise",
        json={
            "project_id": project["project_id"],
            "citation": citation,
            "kind": "decision",
            "text": "已纠正：放弃全局外观嵌入，改用房间 ID 硬约束（示例）",
            "reason": "用户纠正过期记忆",
        },
    ).json()
    assert revised["version"] == 2
    assert revised["text"].startswith("已纠正")

    retired = client.post(
        "/api/memory/retire",
        json={
            "project_id": project["project_id"],
            "citation": revised["citation"],
            "reason": "自动化测试清理",
        },
    ).json()
    assert retired["retired"] is True
    assert retired["entry"]["state"] == "inactive"

    active = client.get("/api/memory", params={"project_id": project["project_id"]}).json()
    assert all(entry["citation"]["entry_id"] != citation["entry_id"] for entry in active["entries"])
    inactive = client.get(
        "/api/memory", params={"project_id": project["project_id"], "include_inactive": "true"}
    ).json()
    assert inactive["total"] > active["total"]


def test_17_unknown_memory_kind_is_rejected(client: httpx.Client, project: dict) -> None:
    response = client.post(
        "/api/memory",
        json={"project_id": project["project_id"], "kind": "model_guess", "text": "模型猜测"},
    )
    assert response.status_code == 400
    assert "unknown memory kind" in response.json()["detail"]


def test_18_save_progress_commits_a_handoff(client: httpx.Client, project: dict) -> None:
    body = client.post(
        "/api/memory/save-progress",
        json={
            "project_id": project["project_id"],
            "session_id": f"pytest-{RUN_ID}",
            "summary": "验证 HSM v2 全局外观嵌入方案不可行，转向房间 ID 硬约束（示例）",
            "messages": [
                {"role": "user", "content": "之前为什么放弃外观嵌入方案？"},
                {"role": "assistant", "content": "因为外观嵌入对视角变化过于敏感。"},
            ],
            "completed": ["完成 HSM v2 全局外观嵌入实验（示例）"],
            "conclusions": ["外观嵌入阈值 0.85 过严，方案不可行（示例）"],
            "open_questions": ["计数类问题准确率仍偏低"],
            "next_steps": ["实现房间 ID 硬约束 + 多视角平均嵌入"],
            "decisions": [{"text": "停止投入外观嵌入方向（示例）", "reason": "准确率下降 4.8 个百分点"}],
            "failures": [{"text": "外观嵌入重识别失败（示例）", "reason": "视角变化导致阈值失效"}],
            "evidence": {"origin": "pytest-live"},
        },
    ).json()

    assert body["handoff"]["status"] == "committed"
    reference = body["handoff"]["reference"]
    assert reference["artifact_id"]
    assert reference["revision"] >= 1
    assert body["source"]["source_id"]
    assert body["source"]["name"]
    assert body["scope_id"] == project["pc_scope_id"]
    kinds = {entry["kind"] for entry in body["memories"]}
    assert {"progress", "decision", "failure", "next_action"} <= kinds


def test_19_restore_returns_the_saved_context(client: httpx.Client, project: dict) -> None:
    body = client.post("/api/memory/restore", params={"project_id": project["project_id"]}).json()

    assert body["scope_id"] == project["pc_scope_id"]
    assert body["handoff"] is not None
    content = body["handoff"]["content"]
    assert "外观嵌入" in content["objective"]
    assert content["state"], "the committed handoff must carry citable state statements"
    assert content["next_action"]["text"]
    assert content["omissions"]
    assert body["memories"]
    assert "已从 PowerContext 恢复" in body["answer"]
    assert body["prepared_context"] is not None


def test_20_prepared_context_reports_its_real_status(client: httpx.Client, project: dict) -> None:
    body = client.post(
        "/api/memory/context",
        json={"project_id": project["project_id"], "query": "当前研究进展与下一步计划"},
    ).json()
    assert body["scope_id"] == project["pc_scope_id"]
    assert body["schema"] == "powercontext.prepared-context.v1"
    assert body["max_bytes"] == 8000
    assert body["content_bytes"] <= 8000

    # PowerContext documents "empty context is normal". Assembling it needs the server-side
    # extract / topic-memory capabilities, which are unavailable without a model provider.
    # Verified against PowerContext 1.2.0: /v1/memory/flush -> 422 capability_not_supported
    # (capability "extract"), /v1/topic-memory/flush -> 503, /v1/profile/flush -> status disabled.
    if body["status"] == "empty":
        assert body["content"] is None
        assert body["content_bytes"] == 0
    else:
        assert body["status"] == "ready"
        assert body["content"]


def test_21_chat_routes_to_the_right_sources_and_cites_them(client: httpx.Client, project: dict) -> None:
    body = client.post(
        "/api/chat",
        json={
            "project_id": project["project_id"],
            "message": "之前为什么放弃全局外观嵌入方案？下一步计划是什么？",
            "session_id": f"pytest-chat-{RUN_ID}",
        },
    ).json()

    assert body["intent"] in {"experiment", "memory", "mixed"}
    assert body["answer"].strip()
    assert body["data_sources"], "the explainability panel must list the data actually used"
    kinds = {source["kind"] for source in body["data_sources"]}
    assert kinds & {"seekdb.experiments", "powercontext.prepared_context", "powercontext.memory_search"}
    assert body["citations"]
    assert all(item["id"] for item in body["citations"])
    if not body["llm_used"]:
        assert "未配置大模型 API" in (body.get("notice") or "")


def test_22_off_topic_question_gets_no_keyword_confirmed_evidence(
    client: httpx.Client, project: dict
) -> None:
    """Vector ANN always returns its k nearest rows, so `matched_by` is what separates
    "the corpus talks about this" from "these are merely the closest vectors"."""
    off_topic = "量子退火催化剂转化率 zzqx"

    keyword = client.post(
        "/api/search",
        json={"project_id": project["project_id"], "query": off_topic, "mode": "keyword"},
    ).json()
    assert keyword["total"] == 0

    body = client.post(
        "/api/chat",
        json={"project_id": project["project_id"], "message": off_topic, "session_id": f"pytest-{RUN_ID}"},
    ).json()
    papers = [citation for citation in body["citations"] if citation["type"] == "paper"]
    confirmed = [
        citation for citation in papers if "fulltext" in ((citation.get("ref") or {}).get("matched_by") or [])
    ]
    assert confirmed == []
    # ANN still returns its nearest neighbours; the response has to say they are vector-only.
    assert papers
    assert all((citation["ref"]["matched_by"] or []) == ["vector"] for citation in papers)
    if not body["llm_used"]:
        assert "未配置大模型 API" in (body.get("notice") or "")


def test_23_report_is_built_from_stored_records_only(client: httpx.Client, project: dict) -> None:
    default_range = client.get("/api/reports/default-range").json()
    body = client.post(
        "/api/reports/generate",
        json={
            "project_id": project["project_id"],
            "start_date": default_range["start_date"],
            "end_date": default_range["end_date"],
            "title": f"自动化测试周报 {RUN_ID}",
        },
    ).json()

    assert body["counts"]["experiments"] == 2
    assert body["counts"]["documents"] == 1
    assert body["counts"]["failures"] >= 1
    assert body["memory_error"] is None
    markdown = body["markdown"]
    assert markdown.startswith(f"# 自动化测试周报 {RUN_ID}")
    assert "accuracy=53.9" in markdown
    assert "accuracy=58.7" in markdown
    assert project["experiment_id"] in markdown
    assert "三段式 3D 场景记忆（示例）" in markdown
    assert "OceanBase seekdb" in markdown


def test_24_report_rejects_an_inverted_range(client: httpx.Client, project: dict) -> None:
    response = client.post(
        "/api/reports/generate",
        json={"project_id": project["project_id"], "start_date": "2026-10-26", "end_date": "2026-10-20"},
    )
    assert response.status_code == 400


def test_25_session_history_can_be_cleared(client: httpx.Client, project: dict) -> None:
    session_id = f"pytest-chat-{RUN_ID}"
    history = client.get(f"/api/chat/sessions/{session_id}").json()
    assert history["messages"], "the previous turns must have been stored server-side"

    cleared = client.delete(f"/api/chat/sessions/{session_id}").json()
    assert cleared["cleared"] is True
    assert client.get(f"/api/chat/sessions/{session_id}").json()["messages"] == []
