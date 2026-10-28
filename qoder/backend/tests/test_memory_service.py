"""PowerContext memory service: provenance string, traceability tags, stale-citation retry."""

from __future__ import annotations

from typing import Any

import pytest

from app.services.memory import (
    KIND_LABELS,
    MEMORY_KINDS,
    _reason,
    _render_restore_answer,
    _render_source,
    _render_transcript,
    _retry_on_stale_revision,
    _shape_entry,
    list_memories,
    retire_memory,
    revise_memory,
    write_memory,
)
from app.services.powercontext import PowerContextError, source_citation, statement


class FakePowerContext:
    """Stands in for PowerContextClient so the retry logic can be exercised offline."""

    def __init__(
        self,
        *,
        stale_times: int = 0,
        entries: list[dict[str, Any]] | None = None,
        list_failures: int = 0,
    ) -> None:
        self.stale_times = stale_times
        self.entries = entries or []
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.list_failures = list_failures

    async def list_entries(self, *, scope_id: str, include_inactive: bool = False) -> dict[str, Any]:
        self.calls.append(("list_entries", {"scope_id": scope_id, "include_inactive": include_inactive}))
        if self.list_failures:
            self.list_failures -= 1
            raise PowerContextError("powercontext unavailable", status_code=503)
        return {
            "memory": {"family": "memory", "artifact_id": "memory", "revision": 9},
            "entries": self.entries,
        }

    async def retire_entry(self, *, scope_id: str, citation: dict[str, Any], reason: str | None = None):
        self.calls.append(("retire_entry", {"scope_id": scope_id, "citation": citation, "reason": reason}))
        if self.stale_times:
            self.stale_times -= 1
            raise PowerContextError(
                "HTTP 409", status_code=409, detail={"error": {"code": "revision_conflict"}}
            )
        return {
            "memory": {"family": "memory", "artifact_id": "memory", "revision": 10},
            "entry": {**_entry("mem_ent_target", revision=10), "state": "inactive"},
        }

    async def revise_entry(
        self, *, scope_id: str, citation: dict[str, Any], kind: str, text: str, reason: str | None = None
    ):
        self.calls.append(("revise_entry", {"scope_id": scope_id, "citation": citation}))
        if self.stale_times:
            self.stale_times -= 1
            raise PowerContextError(
                "HTTP 409", status_code=409, detail={"error": {"code": "revision_conflict"}}
            )
        return {
            "memory": {"family": "memory", "artifact_id": "memory", "revision": 11},
            "entry": _entry("mem_ent_target", kind=kind, text=text, version=2, revision=11),
        }

    async def remember(self, *, scope_id: str, kind: str, text: str, reason: str | None = None):
        self.calls.append(("remember", {"scope_id": scope_id, "kind": kind, "text": text, "reason": reason}))
        return {
            "memory": {"family": "memory", "artifact_id": "memory", "revision": 1},
            "entry": _entry("mem_ent_new", kind=kind, text=text, revision=1),
        }


def _entry(
    entry_id: str,
    *,
    kind: str = "decision",
    text: str = "停止投入全局外观嵌入",
    version: int = 1,
    revision: int = 5,
) -> dict[str, Any]:
    return {
        "citation": {
            "memory_ref": {"family": "memory", "artifact_id": "memory", "revision": revision},
            "entry_id": entry_id,
            "entry_version_id": f"mem_ver_{entry_id}",
        },
        "kind": kind,
        "text": text,
        "version": version,
        "state": "active",
        "source_refs": [],
        "artifact_refs": [],
    }


def _conflict() -> PowerContextError:
    return PowerContextError("HTTP 409", status_code=409, detail={"error": {"code": "revision_conflict"}})


def test_every_memory_kind_has_a_chinese_label() -> None:
    assert set(KIND_LABELS) == set(MEMORY_KINDS)
    assert len(MEMORY_KINDS) == 6


def test_reason_is_none_without_content() -> None:
    assert _reason(None, None) is None
    assert _reason("   ", None) is None
    assert _reason(None, {}) is None


def test_reason_keeps_human_readable_head() -> None:
    assert _reason("来自实验记录 HSM v2", None) == "来自实验记录 HSM v2"


def test_reason_appends_evidence_when_it_fits() -> None:
    composed = _reason("head", {"experiment_id": "exp_1", "project_id": "prj_1"})
    assert composed is not None
    assert composed.startswith("head | evidence: ")
    assert '"experiment_id": "exp_1"' in composed
    assert len(composed) <= 512


def test_reason_never_exceeds_the_powercontext_cap() -> None:
    # RememberMemoryRequest.reason is capped at 512 chars; an over-long value is a hard 422.
    composed = _reason("实验" * 400, {"experiment_id": "exp_" + "x" * 200})
    assert composed is not None
    assert len(composed) <= 512


def test_reason_drops_evidence_blob_rather_than_truncating_it() -> None:
    long_head = "长" * 500
    composed = _reason(long_head, {"session_id": "s" * 100})
    assert composed == long_head[:512]
    assert "evidence" not in composed


async def test_write_memory_rejects_unknown_kind() -> None:
    pc = FakePowerContext()
    with pytest.raises(Exception, match="unknown memory kind"):
        await write_memory(pc, scope_id="scp_1", kind="guess", text="模型猜测")
    assert pc.calls == []


async def test_write_memory_shapes_the_entry_and_passes_reason() -> None:
    pc = FakePowerContext()
    entry = await write_memory(
        pc,
        scope_id="scp_1",
        kind="decision",
        text="  改用房间 ID 硬约束  ",
        reason="用户确认",
        evidence={"experiment_id": "exp_9"},
    )
    assert entry["kind"] == "decision"
    assert entry["kind_label"] == "研究决策"
    assert entry["text"] == "改用房间 ID 硬约束"
    assert entry["citation"]["entry_id"] == "mem_ent_new"
    assert entry["saved_at"]
    kind_call = next(call for call in pc.calls if call[0] == "remember")
    assert kind_call[1]["text"] == "改用房间 ID 硬约束"
    assert "用户确认 | evidence:" in kind_call[1]["reason"]


async def test_list_memories_groups_every_kind_even_when_empty() -> None:
    pc = FakePowerContext(entries=[_entry("mem_ent_a", kind="failure"), _entry("mem_ent_b")])
    listing = await list_memories(pc, scope_id="scp_1")

    assert listing["total"] == 2
    assert set(listing["grouped"]) == set(MEMORY_KINDS)
    assert listing["grouped"]["failure"][0]["kind_label"] == "失败记录"
    assert listing["grouped"]["progress"] == []


def test_shape_entry_defaults_missing_collections() -> None:
    shaped = _shape_entry({"kind": "progress", "text": "完成 baseline"})
    assert shaped["source_refs"] == []
    assert shaped["artifact_refs"] == []
    assert shaped["kind_label"] == "进展"
    assert shaped["citation"] is None


async def test_retry_returns_none_for_non_conflict_errors() -> None:
    pc = FakePowerContext(entries=[_entry("mem_ent_target")])
    error = PowerContextError("HTTP 500", status_code=500, detail="boom")
    assert await _retry_on_stale_revision(pc, scope_id="scp_1", citation={}, error=error) is None
    assert pc.calls == []


async def test_retry_returns_none_for_409_without_revision_conflict() -> None:
    pc = FakePowerContext(entries=[_entry("mem_ent_target")])
    error = PowerContextError("HTTP 409", status_code=409, detail={"error": {"code": "other"}})
    assert await _retry_on_stale_revision(pc, scope_id="scp_1", citation={}, error=error) is None
    assert pc.calls == []


async def test_retry_relists_and_matches_by_entry_id() -> None:
    fresh = _entry("mem_ent_target", revision=9)
    pc = FakePowerContext(entries=[_entry("mem_ent_other"), fresh])
    stale = {**fresh["citation"], "memory_ref": {"revision": 4}}

    refreshed = await _retry_on_stale_revision(pc, scope_id="scp_1", citation=stale, error=_conflict())

    assert refreshed == fresh["citation"]


async def test_retry_gives_up_when_the_entry_is_gone() -> None:
    pc = FakePowerContext(entries=[_entry("mem_ent_other")])
    stale = {"entry_id": "mem_ent_target"}
    assert await _retry_on_stale_revision(pc, scope_id="scp_1", citation=stale, error=_conflict()) is None


async def test_retry_gives_up_when_powercontext_is_down() -> None:
    pc = FakePowerContext(entries=[_entry("mem_ent_target")], list_failures=1)
    assert await _retry_on_stale_revision(pc, scope_id="scp_1", citation={}, error=_conflict()) is None


async def test_retire_memory_retries_once_on_stale_citation() -> None:
    fresh = _entry("mem_ent_target", revision=9)
    pc = FakePowerContext(stale_times=1, entries=[fresh])
    stale = {**fresh["citation"], "memory_ref": {"revision": 4}}

    result = await retire_memory(pc, scope_id="scp_1", citation=stale, reason="清理示例数据")

    assert result["retired"] is True
    assert result["entry"]["state"] == "inactive"
    retire_calls = [call for call in pc.calls if call[0] == "retire_entry"]
    assert len(retire_calls) == 2
    assert retire_calls[0][1]["citation"] == stale
    assert retire_calls[1][1]["citation"] == fresh["citation"]


async def test_retire_memory_surfaces_error_when_retry_also_fails() -> None:
    pc = FakePowerContext(stale_times=2, entries=[_entry("mem_ent_target")])
    with pytest.raises(Exception, match="409"):
        await retire_memory(pc, scope_id="scp_1", citation={"entry_id": "mem_ent_target"})


async def test_revise_memory_retries_once_on_stale_citation() -> None:
    fresh = _entry("mem_ent_target", revision=9)
    pc = FakePowerContext(stale_times=1, entries=[fresh])
    stale = {**fresh["citation"], "memory_ref": {"revision": 4}}

    entry = await revise_memory(
        pc, scope_id="scp_1", citation=stale, kind="decision", text="改为多视角平均嵌入", reason="用户纠正"
    )

    assert entry["version"] == 2
    revise_calls = [call for call in pc.calls if call[0] == "revise_entry"]
    assert len(revise_calls) == 2
    assert revise_calls[1][1]["citation"] == fresh["citation"]


def test_source_citation_and_statement_shapes() -> None:
    citation = source_citation({"name": "mem", "source_id": "src_1", "position": 3})
    assert citation == {"kind": "source", "source_ref": {"name": "mem", "source_id": "src_1"}}
    assert statement("已完成 baseline", [citation]) == {
        "text": "已完成 baseline",
        "citations": [citation],
    }


def test_render_transcript_keeps_only_the_tail() -> None:
    messages = [{"role": "user", "content": f"问题 {index}"} for index in range(60)]
    transcript = _render_transcript(messages, limit=5)
    assert transcript.count("\n") == 4
    assert transcript.startswith("user: 问题 55")
    assert _render_transcript([]) == ""


def test_render_source_separates_evidence_sections() -> None:
    source = _render_source(
        project_name="EQA 研究",
        session_id="sess_1",
        summary="本次会话验证了 HSM v2",
        completed=["完成 baseline"],
        conclusions=["外观嵌入不可行"],
        open_questions=["计数类问题仍偏低"],
        next_steps=["实现 HSM v3"],
        transcript="user: 开始",
    )
    for fragment in (
        "# LabTrace 研究进度快照",
        "项目：EQA 研究",
        "会话：sess_1",
        "## 本次会话总结",
        "## 已完成事项\n- 完成 baseline",
        "## 关键结论\n- 外观嵌入不可行",
        "## 未解决问题\n- 计数类问题仍偏低",
        "## 后续步骤\n- 实现 HSM v3",
        "## 会话记录（截断）",
    ):
        assert fragment in source


def test_render_restore_answer_uses_the_committed_handoff() -> None:
    answer = _render_restore_answer(
        {
            "handoff": {
                "status": "committed",
                "content": {
                    "objective": "在长时序 EQA 中控制显存",
                    "state": [{"text": "完成 HSM v1"}],
                    "next_action": {"text": "实现 HSM v3"},
                    "omissions": [{"text": "计数类问题未解决"}],
                },
            }
        }
    )
    assert "已从 PowerContext 恢复" in answer
    assert "研究目标：在长时序 EQA 中控制显存" in answer
    assert "- 已确认状态：完成 HSM v1" in answer
    assert "下一步：实现 HSM v3" in answer
    assert "- 未解决/未覆盖：计数类问题未解决" in answer


def test_render_restore_answer_falls_back_to_grouped_memories() -> None:
    answer = _render_restore_answer(
        {
            "handoff_error": "no committed handoff",
            "grouped": {
                "progress": [{"text": "完成 baseline"}],
                "decision": [],
                "failure": [],
                "next_action": [],
            },
        }
    )
    assert "已从 PowerContext 恢复" in answer
    assert "- 进展：完成 baseline" in answer


def test_render_restore_answer_says_so_when_nothing_was_saved() -> None:
    answer = _render_restore_answer({"handoff": None, "grouped": {}})
    assert "没有找到该项目已保存的研究进度" in answer
    assert "保存本次研究进度" in answer
