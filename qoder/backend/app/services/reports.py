"""Weekly research report: aggregates real seekdb records and PowerContext memory.

Every metric and completed item comes from stored records; the optional LLM pass
only rewrites a narrative overview from that same data and never invents numbers.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, date, datetime, timedelta
from typing import Any

from app.db.seekdb import SeekDB
from app.services import experiments as exp_service
from app.services.assistant import Assistant
from app.services.memory import KIND_LABELS, list_memories
from app.services.powercontext import PowerContextClient, PowerContextError

logger = logging.getLogger(__name__)


def _range(start: date, end: date) -> tuple[datetime, datetime]:
    start_dt = datetime.combine(start, datetime.min.time())
    end_dt = datetime.combine(end, datetime.max.time()).replace(microsecond=0)
    return start_dt, end_dt


async def generate_report(
    db: SeekDB,
    pc: PowerContextClient,
    assistant: Assistant,
    *,
    project_id: str,
    project_name: str,
    scope_id: str | None,
    start: date,
    end: date,
    title: str | None = None,
) -> dict[str, Any]:
    if end < start:
        raise ValueError("end_date must not be earlier than start_date")
    start_dt, end_dt = _range(start, end)

    documents = await exp_service.documents_in_range(db, project_id, start_dt, end_dt)
    experiments = await exp_service.experiments_in_range(db, project_id, start_dt, end_dt)

    memories: dict[str, list[dict[str, Any]]] = {}
    memory_error: str | None = None
    handoff: dict[str, Any] | None = None
    if scope_id:
        try:
            listing = await list_memories(pc, scope_id=scope_id)
            memories = listing.get("grouped", {})
        except Exception as exc:  # noqa: BLE001
            memory_error = str(exc)
        try:
            resolution = await pc.continue_handoff(scope_id=scope_id, selection="latest")
            handoff = resolution.get("content")
        except PowerContextError as exc:
            logger.info("no committed handoff for scope %s: %s", scope_id, exc)

    data = {
        "project": project_name,
        "range": {"start": start.isoformat(), "end": end.isoformat()},
        "documents": documents,
        "experiments": experiments,
        "memories": memories,
        "handoff": handoff,
    }
    markdown = _render_markdown(data, title)

    llm_used = False
    overview = None
    if assistant.llm_enabled:
        overview, llm_used = await _llm_overview(assistant, data)
        if overview:
            markdown = markdown.replace(
                "## 本周概述\n\n_（未配置大模型 API，本节为空）_", f"## 本周概述\n\n{overview}"
            )

    return {
        "markdown": markdown,
        "data": data,
        "llm_used": llm_used,
        "memory_error": memory_error,
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "counts": {
            "documents": len(documents),
            "experiments": len(experiments),
            "decisions": len(memories.get("decision", [])),
            "failures": len(memories.get("failure", [])),
            "next_actions": len(memories.get("next_action", [])),
        },
    }


async def _llm_overview(assistant: Assistant, data: dict[str, Any]) -> tuple[str | None, bool]:
    compact = {
        "documents": [{"title": d.get("title"), "topic": d.get("topic")} for d in data["documents"]],
        "experiments": [
            {
                "name": e.get("name"),
                "status": e.get("status"),
                "metrics": e.get("metrics"),
                "failure_reason": e.get("failure_reason"),
                "next_steps": e.get("next_steps"),
            }
            for e in data["experiments"]
        ],
        "decisions": [m.get("text") for m in data["memories"].get("decision", [])],
        "failures": [m.get("text") for m in data["memories"].get("failure", [])],
        "next_actions": [m.get("text") for m in data["memories"].get("next_action", [])],
    }
    prompt = (
        "以下是本周科研记录的结构化数据（JSON）。请用中文写一段 150-250 字的本周概述，"
        "只能基于这些数据，不得编造任何数字、论文或结论。若数据为空，请说明本周没有记录。\n\n"
        + json.dumps(compact, ensure_ascii=False)
    )
    text, error = await assistant._chat([{"role": "user", "content": prompt}])
    if error:
        logger.warning("report overview generation failed: %s", error)
        return None, False
    return text, True


def _render_markdown(data: dict[str, Any], title: str | None) -> str:
    start = data["range"]["start"]
    end = data["range"]["end"]
    heading = title or f"{data['project']} 科研周报（{start} ~ {end}）"
    lines = [f"# {heading}", "", f"> 项目：{data['project']} · 统计区间：{start} 至 {end}", ""]

    lines += ["## 本周概述", "", "_（未配置大模型 API，本节为空）_", ""]

    lines += ["## 一、本周阅读的论文", ""]
    if data["documents"]:
        for doc in data["documents"]:
            topic = f" · 主题：{doc['topic']}" if doc.get("topic") else ""
            lines.append(
                f"- **{doc.get('title')}**（{doc.get('file_name')}，{doc.get('page_count')} 页 / "
                f"{doc.get('chunk_count')} 个分块{topic}）"
            )
    else:
        lines.append("- 本区间内没有新导入的论文或文档。")
    lines.append("")

    lines += ["## 二、完成的实验与结果", ""]
    if data["experiments"]:
        for exp in data["experiments"]:
            lines.append(f"### {exp.get('name')} （{exp.get('experiment_id')}）")
            lines.append(f"- 状态：{exp.get('status')}")
            if exp.get("dataset"):
                lines.append(f"- 数据集：{exp.get('dataset')}")
            if exp.get("model_config"):
                lines.append(f"- 模型配置：`{json.dumps(exp.get('model_config'), ensure_ascii=False)}`")
            if exp.get("metrics"):
                metrics = ", ".join(f"{k}={v}" for k, v in exp["metrics"].items())
                lines.append(f"- 指标：{metrics}")
            if exp.get("result_summary"):
                lines.append(f"- 结果：{exp['result_summary']}")
            if exp.get("issues"):
                lines.append(f"- 遇到的问题：{exp['issues']}")
            if exp.get("failure_reason"):
                lines.append(f"- 失败原因：{exp['failure_reason']}")
            if exp.get("next_steps"):
                lines.append(f"- 下一步改进：{exp['next_steps']}")
            lines.append("")
    else:
        lines += ["- 本区间内没有新建或更新的实验记录。", ""]

    lines += ["## 三、技术决策（来自 PowerContext 记忆）", ""]
    decisions = data["memories"].get("decision", [])
    if decisions:
        for item in decisions:
            lines.append(f"- {item.get('text')}")
    else:
        lines.append("- 没有已保存的决策记忆。")
    lines.append("")

    lines += ["## 四、失败与教训", ""]
    failures = data["memories"].get("failure", [])
    if failures:
        for item in failures:
            lines.append(f"- {item.get('text')}")
    else:
        lines.append("- 没有已保存的失败记录。")
    lines.append("")

    lines += ["## 五、进展", ""]
    progress = data["memories"].get("progress", [])
    if progress:
        for item in progress:
            lines.append(f"- {item.get('text')}")
    else:
        lines.append("- 没有已保存的进展记忆。")
    lines.append("")

    lines += ["## 六、尚未完成的任务与下周计划", ""]
    next_actions = data["memories"].get("next_action", [])
    handoff = data.get("handoff") or {}
    next_action = handoff.get("next_action") or {}
    if next_action.get("text"):
        lines.append(f"- 最近一次保存的研究进度（Handoff）下一步：{next_action['text']}")
    for omission in handoff.get("omissions", []) or []:
        if omission.get("text"):
            lines.append(f"- 未解决问题：{omission['text']}")
    if next_actions:
        for item in next_actions:
            lines.append(f"- {item.get('text')}")
    if not next_actions and not next_action.get("text"):
        lines.append("- 没有已保存的后续计划。")
    lines.append("")

    lines += [
        "---",
        "",
        (
            "说明：论文与实验数据来自 OceanBase seekdb 的真实记录，决策/失败/进展/计划来自 PowerContext "
            "中当前有效的记忆条目（PowerContext 记忆列表接口不返回时间戳，因此该部分为截至生成时刻的有效记忆，"
            "而非仅本区间新增）。"
        ),
    ]
    return "\n".join(lines)


def default_report_range(today: date | None = None) -> tuple[date, date]:
    today = today or date.today()
    return today - timedelta(days=6), today


def kind_label(kind: str) -> str:
    return KIND_LABELS.get(kind, kind)
