"""Intent routing and the no-LLM evidence-only answer path."""

from __future__ import annotations

import pytest

from app.services.assistant import (
    _SYSTEM_PROMPT,
    _evidence_only_answer,
    _experiment_brief,
    classify_intent,
)


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        ("这篇论文的相关工作是怎么写的？", "paper"),
        ("baseline 的 accuracy 是多少", "experiment"),
        ("我们之前决定的研究方向是什么", "memory"),
        ("之前那篇论文的模型结构是什么样的", "mixed"),
        ("你好", "mixed"),
    ],
)
def test_classify_intent_routes_by_question_type(question: str, expected: str) -> None:
    assert classify_intent(question) == expected


def test_classify_intent_is_case_insensitive() -> None:
    assert classify_intent("What does the PAPER say about Related Work") == "paper"


def test_evidence_only_answer_refuses_to_guess_without_evidence() -> None:
    answer = _evidence_only_answer([], "HSM v3 的准确率是多少")
    assert "无法给出有依据的回答" in answer
    assert "没有检索到相关证据" in answer
    # No number may appear: the answer must not invent a metric.
    assert not any(char.isdigit() for char in answer.replace("HSM", "").replace("v3", ""))


def test_evidence_only_answer_lists_numbered_evidence() -> None:
    evidence = [
        {
            "id": 1,
            "type": "experiment",
            "label": "HSM v1 (exp_1)",
            "content": "准确率 58.7%，显存 4.2 GB",
            "ref": {},
        },
        {"id": 2, "type": "paper", "label": "综述 第 3 页", "content": "三段式记忆结构", "ref": {}},
    ]
    answer = _evidence_only_answer(evidence, "目前最好的结果是什么")

    assert "[1] (experiment) HSM v1 (exp_1)" in answer
    assert "[2] (paper) 综述 第 3 页" in answer
    assert "58.7%" in answer
    assert "未配置 LLM" in answer


def test_evidence_only_answer_truncates_long_excerpts() -> None:
    evidence = [{"id": 1, "type": "paper", "label": "长文", "content": "字" * 900, "ref": {}}]
    answer = _evidence_only_answer(evidence, "问题")
    assert "…" in answer
    assert "字" * 301 not in answer


def test_experiment_brief_includes_only_populated_fields() -> None:
    brief = _experiment_brief(
        {
            "name": "HSM v2",
            "status": "abandoned",
            "objective": "验证全局外观嵌入",
            "metrics": {"accuracy": 53.9},
            "failure_reason": "视角变化导致阈值失效",
            "hypothesis": None,
            "dataset": None,
        }
    )
    assert "实验名称：HSM v2" in brief
    assert "状态：abandoned" in brief
    assert '"accuracy": 53.9' in brief
    assert "失败原因：视角变化导致阈值失效" in brief
    assert "假设：" not in brief
    assert "数据集：" not in brief


def test_system_prompt_forbids_fabrication() -> None:
    assert "不得" in _SYSTEM_PROMPT
    assert "现有证据无法确认" in _SYSTEM_PROMPT
    assert "[n]" in _SYSTEM_PROMPT
