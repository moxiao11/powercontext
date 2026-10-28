"""AI research assistant: routes a question to the right evidence sources,
then answers with citations. Paper/experiment evidence comes from seekdb,
research memory comes from PowerContext.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Literal

import httpx

from app.config import Settings
from app.db.seekdb import SeekDB
from app.services import experiments as exp_service
from app.services import retrieval
from app.services.memory import KIND_LABELS, list_memories, prepare_research_context, search_memories
from app.services.powercontext import PowerContextClient

logger = logging.getLogger(__name__)

Intent = Literal["paper", "experiment", "memory", "mixed"]

_PAPER_HINTS = (
    "论文",
    "paper",
    "文献",
    "相关工作",
    "related work",
    "方法",
    "架构",
    "模型结构",
    "pdf",
    "引用",
)
_EXPERIMENT_HINTS = (
    "实验",
    "experiment",
    "指标",
    "metric",
    "准确率",
    "accuracy",
    "数据集",
    "dataset",
    "参数",
    "对比",
    "baseline",
    "消融",
    "ablation",
    "放弃",
    "失败",
    "方案",
    "训练",
    "调参",
    "版本",
    "结果",
    "复现",
    "显存",
    "延迟",
)
_MEMORY_HINTS = (
    "上次",
    "之前",
    "昨天",
    "进展",
    "进度",
    "决定",
    "决策",
    "为什么放弃",
    "下一步",
    "计划",
    "记忆",
    "继续",
    "历史",
)

_SYSTEM_PROMPT = """你是 LabTrace 科研助手，服务对象是一名正在进行 Embodied AI / 3D 场景记忆方向研究的科研人员。

回答规则：
1. 只能基于下方提供的【证据】作答，不得使用证据之外的知识编造论文内容或实验数字。
2. 引用证据时使用 [n] 标记，n 对应证据编号。
3. 如果证据不足以回答问题，必须明确说明“现有证据无法确认”，并指出缺少什么信息。
4. 回答结构：直接结论 → 依据与引用 → 相关历史决策（如有）→ 建议的下一步。
5. 区分“证据中的事实”与“你的推断”，推断需明确标注为推断。
"""


def classify_intent(message: str) -> Intent:
    text = message.lower()
    paper = any(hint in text for hint in _PAPER_HINTS)
    experiment = any(hint in text for hint in _EXPERIMENT_HINTS)
    memory = any(hint in text for hint in _MEMORY_HINTS)
    matched = sum([paper, experiment, memory])
    if matched >= 2:
        return "mixed"
    if paper:
        return "paper"
    if experiment:
        return "experiment"
    if memory:
        return "memory"
    return "mixed"


class Assistant:
    def __init__(self, settings: Settings, embeddings: Any) -> None:
        self._settings = settings
        self._embeddings = embeddings
        self._client: httpx.AsyncClient | None = None

    @property
    def llm_enabled(self) -> bool:
        return self._settings.llm_enabled

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def answer(
        self,
        db: SeekDB,
        pc: PowerContextClient,
        *,
        project_id: str,
        scope_id: str,
        message: str,
        history: list[dict[str, str]] | None = None,
    ) -> dict[str, Any]:
        intent = classify_intent(message)
        evidence: list[dict[str, Any]] = []
        data_sources: list[dict[str, Any]] = []

        if intent in {"paper", "mixed"}:
            hits = await retrieval.search_chunks(
                db, self._embeddings, project_id=project_id, query=message, mode="hybrid", limit=6
            )
            for hit in hits:
                page = hit.get("page_no")
                evidence.append(
                    {
                        "type": "paper",
                        "label": f"{hit.get('doc_title')}" + (f" 第 {page} 页" if page else ""),
                        "content": hit["content"],
                        "ref": {
                            "doc_id": hit["doc_id"],
                            "chunk_id": hit["chunk_id"],
                            "page_no": page,
                            "title": hit.get("doc_title"),
                            # Which seekdb leg confirmed this chunk. A vector-only match is just
                            # the nearest neighbour, not evidence the corpus covers the question.
                            "matched_by": hit.get("matched_by"),
                        },
                    }
                )
            if hits:
                data_sources.append(
                    {
                        "kind": "seekdb.paper_chunks",
                        "description": f"seekdb 混合检索命中 {len(hits)} 个论文段落",
                        "items": [
                            {
                                "title": h.get("doc_title"),
                                "page_no": h.get("page_no"),
                                "chunk_id": h["chunk_id"],
                            }
                            for h in hits
                        ],
                    }
                )

        if intent in {"experiment", "mixed"}:
            rows = await exp_service.search_experiments(db, project_id, message, limit=6)
            if not rows:
                rows = (await exp_service.list_experiments(db, project_id, limit=10))[:6]
            for row in rows:
                evidence.append(
                    {
                        "type": "experiment",
                        "label": f"{row['name']} ({row['experiment_id']})",
                        "content": _experiment_brief(row),
                        "ref": {"experiment_id": row["experiment_id"], "name": row["name"]},
                    }
                )
            if rows:
                data_sources.append(
                    {
                        "kind": "seekdb.experiments",
                        "description": f"seekdb 实验记录检索命中 {len(rows)} 条",
                        "items": [
                            {
                                "experiment_id": r["experiment_id"],
                                "name": r["name"],
                                "status": r.get("status"),
                            }
                            for r in rows
                        ],
                    }
                )

        if intent in {"memory", "mixed"}:
            try:
                prepared = await prepare_research_context(pc, scope_id=scope_id, query=message)
                if prepared.get("content"):
                    evidence.append(
                        {
                            "type": "memory",
                            "label": "PowerContext 研究记忆（PreparedContext）",
                            "content": prepared["content"],
                            "ref": {"scope_id": scope_id, "status": prepared.get("status")},
                        }
                    )
                    data_sources.append(
                        {
                            "kind": "powercontext.prepared_context",
                            "description": f"PowerContext 上下文准备（status={prepared.get('status')}）",
                            "items": [],
                        }
                    )
                hits = await search_memories(pc, scope_id=scope_id, query=message, limit=5)
                for hit in hits.get("hits", []):
                    evidence.append(
                        {
                            "type": "memory",
                            "label": f"记忆 · {KIND_LABELS.get(hit.get('kind', ''), hit.get('kind'))}",
                            "content": hit.get("text", ""),
                            "ref": {"citation": hit.get("citation"), "kind": hit.get("kind")},
                        }
                    )
                if hits.get("hits"):
                    data_sources.append(
                        {
                            "kind": "powercontext.memory_search",
                            "description": f"PowerContext 记忆检索命中 {len(hits['hits'])} 条",
                            "items": [
                                {"kind": h.get("kind"), "text": (h.get("text") or "")[:120]}
                                for h in hits["hits"]
                            ],
                        }
                    )
                elif not prepared.get("content"):
                    # Query-time retrieval matched nothing, but the scope may still hold saved
                    # research state. Fall back to the stored entries so a "where did I leave
                    # off" question is answered from real memory instead of returning nothing.
                    stored = await list_memories(pc, scope_id=scope_id)
                    entries = stored.get("entries", [])
                    for entry in entries[:12]:
                        evidence.append(
                            {
                                "type": "memory",
                                "label": f"记忆 · {entry.get('kind_label') or entry.get('kind')}",
                                "content": entry.get("text", ""),
                                "ref": {"citation": entry.get("citation"), "kind": entry.get("kind")},
                            }
                        )
                    if entries:
                        data_sources.append(
                            {
                                "kind": "powercontext.memory_list",
                                "description": (
                                    f"PowerContext 记忆检索未命中，回退读取该项目全部 {stored.get('total')} 条记忆"
                                ),
                                "items": [
                                    {"kind": e.get("kind"), "text": (e.get("text") or "")[:120]}
                                    for e in entries[:12]
                                ],
                            }
                        )
            except Exception as exc:  # noqa: BLE001 - memory failures must not block answering
                logger.warning("memory evidence unavailable: %s", exc)
                data_sources.append(
                    {"kind": "powercontext.error", "description": f"PowerContext 不可用：{exc}", "items": []}
                )

        numbered = [
            {
                "id": index,
                "type": item["type"],
                "label": item["label"],
                "content": item["content"],
                "ref": item["ref"],
            }
            for index, item in enumerate(evidence, start=1)
        ]

        if not self.llm_enabled:
            return {
                "intent": intent,
                "answer": _evidence_only_answer(numbered, message),
                "llm_used": False,
                "notice": "未配置大模型 API（OPENAI_BASE_URL / OPENAI_API_KEY / CHAT_MODEL），"
                "以下仅展示从 seekdb 与 PowerContext 检索到的真实证据。",
                "citations": numbered,
                "data_sources": data_sources,
            }

        prompt_evidence = (
            "\n\n".join(
                f"[{item['id']}] ({item['type']}) {item['label']}\n{item['content'][:2500]}"
                for item in numbered
            )
            or "（没有检索到任何证据）"
        )
        user_prompt = (
            f"【证据】\n{prompt_evidence}\n\n【问题】\n{message}\n\n"
            "请按回答规则输出，并在结尾列出使用的证据编号。"
        )
        messages = [{"role": "system", "content": _SYSTEM_PROMPT}]
        for item in (history or [])[-6:]:
            messages.append({"role": item["role"], "content": item["content"]})
        messages.append({"role": "user", "content": user_prompt})

        answer_text, error = await self._chat(messages)
        return {
            "intent": intent,
            "answer": answer_text,
            "llm_used": error is None,
            "llm_error": error,
            "citations": numbered,
            "data_sources": data_sources,
        }

    async def _chat(self, messages: list[dict[str, str]]) -> tuple[str, str | None]:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=120.0)
        try:
            response = await self._client.post(
                f"{self._settings.openai_base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self._settings.openai_api_key}"},
                json={"model": self._settings.chat_model, "messages": messages, "temperature": 0.2},
            )
        except httpx.HTTPError as exc:
            return "", f"LLM 请求失败：{exc}"
        if response.status_code != 200:
            return "", f"LLM 返回 HTTP {response.status_code}: {response.text[:300]}"
        try:
            payload = response.json()
            return payload["choices"][0]["message"]["content"].strip(), None
        except (KeyError, IndexError, json.JSONDecodeError) as exc:
            return "", f"LLM 响应解析失败：{exc}"


def _experiment_brief(row: dict[str, Any]) -> str:
    parts = [
        f"实验名称：{row.get('name')}",
        f"状态：{row.get('status')}",
        f"目标：{row.get('objective')}" if row.get("objective") else None,
        f"假设：{row.get('hypothesis')}" if row.get("hypothesis") else None,
        f"方法：{row.get('method')}" if row.get("method") else None,
        f"数据集：{row.get('dataset')}" if row.get("dataset") else None,
        f"模型配置：{json.dumps(row.get('model_config'), ensure_ascii=False)}"
        if row.get("model_config")
        else None,
        f"结果：{row.get('result_summary')}" if row.get("result_summary") else None,
        f"指标：{json.dumps(row.get('metrics'), ensure_ascii=False)}" if row.get("metrics") else None,
        f"问题：{row.get('issues')}" if row.get("issues") else None,
        f"失败原因：{row.get('failure_reason')}" if row.get("failure_reason") else None,
        f"下一步：{row.get('next_steps')}" if row.get("next_steps") else None,
    ]
    return "\n".join(part for part in parts if part)


def _evidence_only_answer(evidence: list[dict[str, Any]], question: str) -> str:
    if not evidence:
        return (
            f"关于「{question}」，seekdb 与 PowerContext 中都没有检索到相关证据，"
            "因此无法给出有依据的回答。请先导入论文、记录实验或保存研究进度。"
        )
    lines = [f"关于「{question}」，检索到以下真实证据（未配置 LLM，未做生成式总结）：", ""]
    for item in evidence:
        lines.append(f"[{item['id']}] ({item['type']}) {item['label']}")
        excerpt = item["content"].strip().replace("\n", " ")
        lines.append(f"    {excerpt[:300]}{'…' if len(excerpt) > 300 else ''}")
        lines.append("")
    return "\n".join(lines)
