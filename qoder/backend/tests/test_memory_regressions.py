"""Current memory wins over snapshots; partial writes and conflicts stay visible."""

import pytest

from app.services.memory import MemoryError, _render_restore_answer, revise_memory, save_progress
from tests.test_memory_service import FakePowerContext, _entry


async def test_concurrent_correction_is_never_overwritten_by_retry() -> None:
    pc = FakePowerContext(stale_times=1, entries=[_entry("entry")])
    with pytest.raises(MemoryError, match="409"):
        await revise_memory(
            pc,
            scope_id="scope",
            citation={"entry_id": "entry", "entry_version_id": "older-version"},
            kind="decision",
            text="陈旧客户端修改",
        )
    assert len([call for call in pc.calls if call[0] == "revise_entry"]) == 1


def test_restore_uses_corrected_active_memory_instead_of_old_snapshot() -> None:
    answer = _render_restore_answer(
        {
            "handoff": {"content": {"next_action": {"text": "旧计划"}}},
            "grouped": {"next_action": [_entry("entry", kind="next_action", text="修订计划", version=2)]},
        }
    )
    assert "修订计划" in answer
    assert "旧计划" not in answer


def test_retired_memory_is_not_revived_by_handoff() -> None:
    answer = _render_restore_answer(
        {
            "handoff": {"content": {"next_action": {"text": "已撤销的计划"}}},
            "grouped": {},
        }
    )
    assert "当前没有有效记忆" in answer
    assert "已撤销的计划" not in answer


class PartialPowerContext(FakePowerContext):
    def __init__(self):
        super().__init__()
        self.source_content = ""

    async def capture_source(self, **kwargs):
        self.source_content = kwargs["content"]
        return {"source": {"name": "scope", "source_id": "source"}}

    async def remember(self, **kwargs):
        from app.services.powercontext import PowerContextError

        if kwargs["kind"] == "failure":
            raise PowerContextError("write unavailable", status_code=503)
        return await super().remember(**kwargs)

    async def finalize_handoff(self, **kwargs):
        return kwargs["draft"]

    async def commit_handoff(self, **kwargs):
        return {"reference": {"family": "handoff", "revision": 1}}


async def test_partial_progress_save_preserves_reason_in_source_and_reports_failure() -> None:
    pc = PartialPowerContext()
    result = await save_progress(
        pc,
        scope_id="scope",
        project_name="示例",
        session_id="session",
        summary="验证记忆",
        messages=[],
        decisions=[{"text": "使用房间约束", "reason": "避免跨房间误合并"}],
        failures=[{"text": "放弃旧方案", "reason": "缺少视角不变性"}],
    )
    assert result["status"] == "partial"
    assert result["failed_writes"][0]["kind"] == "failure"
    assert result["handoff"]["status"] == "committed"
    assert "缺少视角不变性" in pc.source_content
    assert "避免跨房间误合并" in result["memories"][0]["text"]
    assert "[session:session]" in result["memories"][0]["text"]
