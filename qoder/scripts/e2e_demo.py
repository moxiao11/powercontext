#!/usr/bin/env python3
"""LabTrace end-to-end demo: exercises demos A-D against a running backend.

Usage:
    python scripts/e2e_demo.py [--api http://127.0.0.1:8100] [--keep]

Creates a fresh demo project, imports the sample papers into seekdb, runs hybrid
retrieval, imports the sample experiments, saves research progress to
PowerContext, restores it in a brand-new "session", and generates a weekly report.
Every assertion prints the real values returned by the services.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path

import httpx

QODER_DIR = Path(__file__).resolve().parent.parent
SAMPLE_DIR = QODER_DIR / "sample-data"

PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"
failures: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    print(
        f"  [{PASS if condition else FAIL}] {label}{(' — ' + detail) if detail else ''}"
    )
    if not condition:
        failures.append(label)


def section(title: str) -> None:
    print(f"\n=== {title} ===")


def unwrap(response: httpx.Response, label: str) -> dict:
    """Return the JSON body, or record a failure and return {} so the run keeps going."""
    if response.status_code >= 400:
        check(label, False, f"HTTP {response.status_code}: {response.text[:300]}")
        return {}
    return response.json()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api", default="http://127.0.0.1:8100")
    parser.add_argument(
        "--keep", action="store_true", help="do not delete the demo project at the end"
    )
    args = parser.parse_args()

    client = httpx.Client(base_url=args.api, timeout=180.0)

    section("0. 服务健康检查")
    health = client.get("/api/health").json()
    print(json.dumps(health, ensure_ascii=False, indent=2))
    check("seekdb 已连接", health["seekdb"]["connected"], health["seekdb"]["version"])
    check(
        "PowerContext 就绪",
        health["powercontext"]["ready"],
        health["powercontext"]["url"],
    )

    section("1. 创建演示项目（绑定 PowerContext Scope）")
    project = client.post(
        "/api/projects",
        json={
            "name": "3D-MEM 场景记忆研究（演示）",
            "description": "示例项目：研究 Embodied QA 中的 3D 场景记忆机制（LabTrace 演示数据）",
            "research_profile": "研究方向：Embodied Question Answering 与 3D Scene Memory；"
            "长期目标：在长时序具身问答中用可控内存的记忆机制提升历史依赖型问题准确率。",
        },
    ).json()
    project_id = project["project_id"]
    print(f"  project_id={project_id} pc_scope_id={project.get('pc_scope_id')}")
    check("项目创建成功", bool(project_id))
    check("PowerContext Scope 已绑定", bool(project.get("pc_scope_id")))
    check(
        "研究方向已写入 PowerContext 记忆",
        bool(project.get("research_profile")),
        (project.get("research_profile") or {}).get("kind", ""),
    )

    section("2. 演示 A：导入样例论文并在 seekdb 建立索引")
    papers = sorted((SAMPLE_DIR / "papers").glob("*.md"))
    for paper in papers:
        response = client.post(
            "/api/documents/upload",
            data={
                "project_id": project_id,
                "title": paper.stem,
                "topic": "Embodied QA / 3D Scene Memory",
            },
            files={"file": (paper.name, paper.read_bytes(), "text/markdown")},
        )
        response.raise_for_status()
        result = response.json()
        print(
            f"  {result['title']}: chunks={result['chunk_count']} pages={result['page_count']} "
            f"embeddings={result['embedding_provider']}"
        )
        check(
            f"{paper.name} 已分块入库",
            result["chunk_count"] > 0,
            f"{result['chunk_count']} chunks",
        )

    documents = client.get("/api/documents", params={"project_id": project_id}).json()
    check(
        "seekdb 中可查询到全部文档",
        documents["total"] == len(papers),
        f"total={documents['total']}",
    )

    section("3. 演示 A：混合检索（真实经过 seekdb）")
    question = "这些论文分别使用了什么记忆架构？它们之间有什么不同？"
    search = unwrap(
        client.post(
            "/api/search",
            json={
                "project_id": project_id,
                "query": question,
                "mode": "hybrid",
                "limit": 6,
            },
        ),
        "混合检索请求",
    )
    print(f"  engine={search.get('engine')}")
    print(f"  sql_mode={search.get('sql_mode')}")
    for citation in search.get("citations", []):
        print(
            f"    [{citation.get('score')}] {citation['title']} · {citation['location']} "
            f"· matched_by={citation.get('matched_by')}"
        )
    check(
        "混合检索返回证据", search.get("total", 0) > 0, f"{search.get('total', 0)} hits"
    )
    check(
        "检索引擎为 OceanBase seekdb",
        "seekdb" in str(search.get("engine", "")).lower(),
        str(search.get("engine")),
    )
    check(
        "命中多篇不同论文", len({c["doc_id"] for c in search.get("citations", [])}) >= 2
    )

    keyword = unwrap(
        client.post(
            "/api/search",
            json={
                "project_id": project_id,
                "query": "体素 记忆",
                "mode": "keyword",
                "limit": 5,
            },
        ),
        "关键词检索请求",
    )
    check(
        "关键词检索（FULLTEXT）可用",
        keyword.get("total", 0) > 0,
        f"{keyword.get('total', 0)} hits",
    )

    vector = unwrap(
        client.post(
            "/api/search",
            json={
                "project_id": project_id,
                "query": "voxel memory navigation",
                "mode": "vector",
                "limit": 5,
            },
        ),
        "向量检索请求",
    )
    check(
        "向量检索（ANN）可用",
        vector.get("total", 0) > 0,
        f"{vector.get('total', 0)} hits",
    )

    if search.get("citations"):
        first = search["citations"][0]
        chunks = client.get(
            f"/api/documents/{first['doc_id']}/chunks",
            params={"project_id": project_id},
        ).json()
        check(
            "引用可回溯到原始分块", chunks["total"] > 0, f"doc chunks={chunks['total']}"
        )

    section("4. 演示 B：导入实验记录并对比")
    payload = json.loads(
        (SAMPLE_DIR / "experiments" / "sample-experiments.json").read_text(
            encoding="utf-8"
        )
    )
    imported = client.post(
        "/api/experiments/import", params={"project_id": project_id}, json=payload
    ).json()
    print(f"  imported={imported['imported']}")
    check("实验记录导入成功", imported["imported"] == len(payload))

    experiments = client.get(
        "/api/experiments", params={"project_id": project_id}
    ).json()["experiments"]
    by_name = {item["name"]: item for item in experiments}
    baseline = by_name.get("No-Memory Baseline (EQA-Long)")
    hsm = by_name.get("HSM v1：物体摘要 + IoU 合并")
    check("baseline 实验存在", baseline is not None)
    check("HSM v1 实验存在", hsm is not None)

    if baseline and hsm:
        comparison = client.get(
            "/api/experiments/compare",
            params={
                "project_id": project_id,
                "left": baseline["experiment_id"],
                "right": hsm["experiment_id"],
            },
        ).json()
        print(f"  差异字段数={len(comparison['differences'])}")
        for delta in comparison["metric_deltas"]:
            print(
                f"    {delta['metric']}: {delta['left']} → {delta['right']} (Δ={delta['delta']})"
            )
        acc = next(
            (d for d in comparison["metric_deltas"] if d["metric"] == "accuracy"), None
        )
        check(
            "准确率差异来自数据库真实记录",
            bool(acc and acc["delta"]),
            f"Δ={acc['delta'] if acc else None}",
        )

    best = client.get(
        "/api/experiments/best", params={"project_id": project_id, "metric": "accuracy"}
    ).json()
    check(
        "可查询效果最好的实验",
        best.get("best") is not None,
        (best.get("best") or {}).get("name", ""),
    )

    exp_search = client.post(
        "/api/experiments/search",
        json={"project_id": project_id, "query": "放弃 外观嵌入", "limit": 5},
    ).json()
    check(
        "实验全文检索命中失败记录",
        exp_search["total"] > 0,
        f"{exp_search['total']} hits · {exp_search['sql_mode']}",
    )

    abandoned = client.get(
        "/api/experiments", params={"project_id": project_id, "status": "abandoned"}
    ).json()["experiments"]
    check("可按状态筛选已放弃的实验", len(abandoned) == 1, f"{len(abandoned)} 条")
    if abandoned:
        print(f"    放弃原因：{abandoned[0]['failure_reason']}")

    section("5. 演示 C：保存研究进度到 PowerContext")
    session_id = "demo-session-day1"
    saved = client.post(
        "/api/memory/save-progress",
        json={
            "project_id": project_id,
            "session_id": session_id,
            "summary": "确定采用 YOLO-World + SAM 生成物体级摘要的检测方案；HSM v1 已达到 58.7% 准确率，"
            "HSM v2 的全局外观嵌入方案已放弃。",
            "messages": [
                {
                    "role": "user",
                    "content": "我准备采用 YOLO-World + SAM 进行实例检测，先测试无记忆 baseline。",
                },
                {
                    "role": "assistant",
                    "content": "已记录：baseline 准确率 41.2%，历史依赖型问题 22.6%。",
                },
                {
                    "role": "user",
                    "content": "HSM v2 的外观嵌入方案效果反而变差，我打算放弃它。",
                },
            ],
            "completed": [
                "完成无记忆 baseline 评测（accuracy 41.2%）",
                "完成 Frame-Buffer 64 帧对照实验（accuracy 52.4%，显存 11.8 GB）",
                "完成 HSM v1 物体摘要记忆（accuracy 58.7%，显存 4.2 GB）",
            ],
            "conclusions": [
                "符号化物体摘要在显存与准确率上同时优于稠密帧缓存",
                "全局外观嵌入重识别方案不可行：视角变化导致相似度阈值失效，已放弃",
            ],
            "open_questions": [
                "计数类问题错误率仍占 23%，需要房间 ID 硬约束的合并策略"
            ],
            "next_steps": [
                "实现房间 ID 硬约束 + 多视角平均嵌入的合并策略（HSM v3）",
                "在 EQA-Long 上复测计数类问题子集",
            ],
            "failures": [
                {
                    "text": "HSM v2 全局外观嵌入重识别使准确率从 58.7% 降到 53.9%",
                    "reason": "experiment HSM v2 abandoned",
                }
            ],
            "evidence": {
                "project_id": project_id,
                "experiment_ids": [item["experiment_id"] for item in experiments],
            },
        },
    ).json()
    print(f"  source={saved.get('source')}")
    print(
        f"  memories={len(saved.get('memories', []))} handoff={saved.get('handoff', {}).get('status')}"
    )
    check(
        "会话已作为 Source 写入 PowerContext",
        bool(saved.get("source", {}).get("source_id")),
    )
    check(
        "记忆条目已写入",
        len(saved.get("memories", [])) >= 5,
        f"{len(saved.get('memories', []))} 条",
    )
    check(
        "Handoff 已提交（持久化研究进度里程碑）",
        saved.get("handoff", {}).get("status") == "committed",
        json.dumps(saved.get("handoff", {}), ensure_ascii=False)[:200],
    )

    section("6. 演示 C：全新会话恢复研究上下文")
    restored = client.post(
        "/api/memory/restore", params={"project_id": project_id}
    ).json()
    print("  --- 恢复结果 ---")
    print("  " + str(restored.get("answer", "")).replace("\n", "\n  "))
    check(
        "Handoff 可在新会话中读取",
        (restored.get("handoff") or {}).get("status") == "resolved",
        str((restored.get("handoff") or {}).get("status")),
    )
    check("恢复内容包含下一步计划", "下一步" in str(restored.get("answer", "")))
    check(
        "记忆条目总数 >= 6",
        len(restored.get("memories", [])) >= 6,
        f"{len(restored.get('memories', []))} 条",
    )

    memories = client.get("/api/memory", params={"project_id": project_id}).json()
    grouped = memories.get("grouped", {})
    print(f"  记忆分类统计：{ {k: len(v) for k, v in grouped.items() if v} }")
    check(
        "记忆按类别隔离存储",
        len(grouped.get("decision", [])) >= 1
        and len(grouped.get("next_action", [])) >= 1,
    )

    section("7. 演示 C：AI 助手按问题类型选择数据源")
    for question, expected_source in [
        ("这些论文分别使用了什么记忆架构？", "seekdb.paper_chunks"),
        ("之前为什么放弃 HSM v2 这个方案？", "seekdb.experiments"),
        ("我上次研究到哪里了？下一步做什么？", "powercontext."),
    ]:
        chat = client.post(
            "/api/chat",
            json={
                "project_id": project_id,
                "message": question,
                "session_id": "demo-session-day2",
            },
        ).json()
        kinds = [source["kind"] for source in chat.get("data_sources", [])]
        print(f"  Q: {question}")
        print(
            f"    intent={chat.get('intent')} llm_used={chat.get('llm_used')} sources={kinds}"
        )
        check(
            f"数据源包含 {expected_source}",
            any(expected_source in kind for kind in kinds),
            ", ".join(kinds),
        )

    section("8. 演示 D：生成科研周报")
    today = date.today()
    report = client.post(
        "/api/reports/generate",
        json={
            "project_id": project_id,
            "start_date": (today - timedelta(days=6)).isoformat(),
            "end_date": today.isoformat(),
        },
    ).json()
    print(
        f"  counts={json.dumps(report['counts'], ensure_ascii=False)} llm_used={report['llm_used']}"
    )
    markdown = report["markdown"]
    check(
        "周报包含本周论文",
        "sample-sequential-eqa" in markdown or "Sequential-EQA" in markdown,
    )
    check("周报包含真实实验指标", "58.7" in markdown, "HSM v1 accuracy")
    check("周报包含失败原因", "放弃" in markdown or "外观嵌入" in markdown)
    check("周报包含下一步计划", "HSM v3" in markdown)
    out = QODER_DIR / "sample-data" / "generated-sample-report.md"
    out.write_text(markdown, encoding="utf-8")
    print(f"  已导出：{out}")

    section("9. 记忆管理：修订与停用")
    decisions = grouped.get("decision", [])
    if decisions:
        target = decisions[0]
        revised = client.post(
            "/api/memory/revise",
            json={
                "project_id": project_id,
                "citation": target["citation"],
                "kind": "decision",
                "text": target["text"] + "（已由用户复核确认）",
                "reason": "用户在 Memory 界面复核",
            },
        ).json()
        check(
            "记忆修订返回新版本",
            (revised.get("version") or 0) >= 2,
            f"version={revised.get('version')}",
        )

        retired = client.post(
            "/api/memory/retire",
            json={
                "project_id": project_id,
                "citation": revised.get("citation") or target["citation"],
                "reason": "演示：停用过期记忆",
            },
        ).json()
        check("记忆停用成功", bool(retired.get("retired")))

        active = client.get("/api/memory", params={"project_id": project_id}).json()
        inactive = client.get(
            "/api/memory", params={"project_id": project_id, "include_inactive": True}
        ).json()
        check(
            "停用后默认列表不再包含该条，但历史可追溯",
            active["total"] == inactive["total"] - 1,
            f"active={active['total']} all={inactive['total']}",
        )

    if not args.keep:
        section("10. 清理演示项目")
        client.delete(f"/api/projects/{project_id}")
        print(
            f"  已删除演示项目 {project_id}（PowerContext Scope 中的记忆保留以便审计）"
        )

    print("\n" + "=" * 60)
    if failures:
        print(f"{FAIL} {len(failures)} 项检查未通过：")
        for item in failures:
            print(f"  - {item}")
        return 1
    print(f"{PASS} 全部检查通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
