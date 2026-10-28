"""Weekly report rendering: every number must come from a stored record."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

import pytest

from app.services.reports import _range, _render_markdown, default_report_range, generate_report, kind_label


def _data(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "project": "EQA 与 3D 场景记忆",
        "range": {"start": "2026-10-20", "end": "2026-10-26"},
        "documents": [],
        "experiments": [],
        "memories": {},
        "handoff": None,
    }
    base.update(overrides)
    return base


def test_range_covers_the_whole_end_day() -> None:
    start, end = _range(date(2026, 10, 20), date(2026, 10, 26))
    assert start == datetime(2026, 10, 20, 0, 0)
    assert end == datetime(2026, 10, 26, 23, 59, 59)


def test_default_report_range_is_a_seven_day_window() -> None:
    start, end = default_report_range(date(2026, 10, 27))
    assert (start, end) == (date(2026, 10, 21), date(2026, 10, 27))


def test_kind_label_falls_back_to_the_raw_kind() -> None:
    assert kind_label("decision") == "研究决策"
    assert kind_label("custom_kind") == "custom_kind"


def test_markdown_states_explicitly_when_a_section_has_no_records() -> None:
    markdown = _render_markdown(_data(), None)

    assert "本区间内没有新导入的论文或文档。" in markdown
    assert "本区间内没有新建或更新的实验记录。" in markdown
    assert "没有已保存的决策记忆。" in markdown
    assert "没有已保存的失败记录。" in markdown
    assert "没有已保存的进展记忆。" in markdown
    assert "没有已保存的后续计划。" in markdown
    assert "_（未配置大模型 API，本节为空）_" in markdown
    # Nothing may be invented: an empty report carries no metric-looking numbers.
    body = markdown.split("## 一、本周阅读的论文")[1]
    assert not any(char.isdigit() for char in body)


def test_markdown_uses_the_default_heading_and_accepts_an_override() -> None:
    assert _render_markdown(_data(), None).startswith(
        "# EQA 与 3D 场景记忆 科研周报（2026-10-20 ~ 2026-10-26）"
    )
    assert _render_markdown(_data(), "第 43 周周报").startswith("# 第 43 周周报")


def test_markdown_renders_documents_with_their_real_counts() -> None:
    markdown = _render_markdown(
        _data(
            documents=[
                {
                    "title": "3D Scene Memory 综述",
                    "topic": "场景记忆",
                    "file_name": "sample-3d-mem.md",
                    "page_count": 0,
                    "chunk_count": 12,
                }
            ]
        ),
        None,
    )
    assert "**3D Scene Memory 综述**" in markdown
    assert "sample-3d-mem.md" in markdown
    assert "12 个分块" in markdown
    assert "主题：场景记忆" in markdown


def test_markdown_renders_experiment_metrics_from_the_record() -> None:
    markdown = _render_markdown(
        _data(
            experiments=[
                {
                    "experiment_id": "exp_abc123",
                    "name": "HSM v1 物体摘要记忆",
                    "status": "completed",
                    "dataset": "EQA-Long",
                    "model_config": {"lr": 0.001},
                    "metrics": {"accuracy": 58.7, "vram_gb": 4.2},
                    "result_summary": "准确率 58.7%",
                    "issues": None,
                    "failure_reason": None,
                    "next_steps": "复测计数类问题",
                }
            ]
        ),
        None,
    )
    assert "### HSM v1 物体摘要记忆 （exp_abc123）" in markdown
    assert "accuracy=58.7" in markdown
    assert "vram_gb=4.2" in markdown
    assert '`{"lr": 0.001}`' in markdown
    assert "下一步改进：复测计数类问题" in markdown
    assert "失败原因" not in markdown


def test_markdown_renders_failure_details_when_present() -> None:
    markdown = _render_markdown(
        _data(
            experiments=[
                {
                    "experiment_id": "exp_def456",
                    "name": "HSM v2 全局外观嵌入",
                    "status": "abandoned",
                    "failure_reason": "视角变化导致相似度阈值失效",
                    "issues": "同一物体被拆成多条记忆",
                }
            ]
        ),
        None,
    )
    assert "失败原因：视角变化导致相似度阈值失效" in markdown
    assert "遇到的问题：同一物体被拆成多条记忆" in markdown


def test_markdown_renders_memory_sections_by_kind() -> None:
    markdown = _render_markdown(
        _data(
            memories={
                "decision": [{"text": "停止投入全局外观嵌入方向"}],
                "failure": [{"text": "阈值 0.85 过严"}],
                "progress": [{"text": "完成 baseline 评测"}],
                "next_action": [{"text": "实现 HSM v3"}],
            }
        ),
        None,
    )
    assert "- 停止投入全局外观嵌入方向" in markdown
    assert "- 阈值 0.85 过严" in markdown
    assert "- 完成 baseline 评测" in markdown
    assert "- 实现 HSM v3" in markdown


def test_markdown_includes_handoff_next_action_and_omissions() -> None:
    markdown = _render_markdown(
        _data(
            handoff={
                "next_action": {"text": "在 EQA-Long 上复测"},
                "omissions": [{"text": "计数类问题仍偏低"}],
            }
        ),
        None,
    )
    assert "最近一次保存的研究进度（Handoff）下一步：在 EQA-Long 上复测" in markdown
    assert "- 未解决问题：计数类问题仍偏低" in markdown
    assert "没有已保存的后续计划。" not in markdown


def test_markdown_declares_its_data_sources() -> None:
    markdown = _render_markdown(_data(), None)
    assert "OceanBase seekdb" in markdown
    assert "PowerContext" in markdown
    assert "而非仅本区间新增" in markdown


async def test_generate_report_rejects_an_inverted_range() -> None:
    with pytest.raises(ValueError, match="must not be earlier than"):
        await generate_report(
            None,
            None,
            None,
            project_id="prj_1",
            project_name="p",
            scope_id=None,
            start=date(2026, 10, 26),
            end=date(2026, 10, 20),
        )
