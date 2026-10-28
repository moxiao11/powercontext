"""玩家隔离与异常处理测试（Test 4 / Test 8）。"""

from __future__ import annotations

from tests.conftest import build_engine, mock_transport_factory, turn


class TestPlayerIsolation:
    """Test 4：玩家 A、B 互不可见。"""

    def test_states_do_not_mix(self, engine, db):
        turn(engine, "player_a", "开始游戏")
        turn(engine, "player_b", "开始游戏")
        turn(engine, "player_a", "前往面包店")
        turn(engine, "player_a", "骗你", intent={"action_type": "lie_identity", "target": "baker", "content": "自称王子"})
        a = engine._load("player_a")
        b = engine._load("player_b")
        assert a["relationships"]["baker"]["trust"] == 40
        assert b["relationships"]["baker"]["trust"] == 50
        assert b["turn"] == 0
        assert [e for e in db.list_events("player_b")] == []
        assert [r for r in db.list_rumors("player_b")] == []

    def test_player_b_cannot_hear_player_a_secrets(self, engine, db):
        turn(engine, "player_a", "开始游戏")
        turn(engine, "player_a", "前往面包店")
        turn(engine, "player_a", "骗你", intent={"action_type": "lie_identity", "target": "baker", "content": "我是国王的儿子"})
        turn(engine, "player_b", "开始游戏")
        turn(engine, "player_b", "前往城门")
        state_b = engine._load("player_b")
        context = engine._build_npc_context(state_b, "guard", "（测试）", "你是谁？")
        assert "国王的儿子" not in context
        assert "王子" not in context

    def test_scopes_are_per_player(self, engine, fake_memory):
        turn(engine, "player_a", "开始游戏")
        turn(engine, "player_b", "开始游戏")
        scope_a = engine._load("player_a")["scope_id"]
        scope_b = engine._load("player_b")["scope_id"]
        assert scope_a and scope_b
        assert scope_a != scope_b

    def test_recall_is_scoped(self, engine, fake_memory):
        turn(engine, "player_a", "开始游戏")
        turn(engine, "player_a", "前往面包店")
        turn(engine, "player_a", "骗你", intent={"action_type": "lie_identity", "target": "baker", "content": "自称王子"})
        turn(engine, "player_b", "开始游戏")
        recall_b = engine.recall("player_b", "guard", "王子")
        assert recall_b["memories"] == []
        recall_a = engine.recall("player_a", "guard", "王子")
        assert any("王子" in m for m in recall_a["memories"])


class TestPowerContextUnavailable:
    """Test 8：PowerContext 不可用时的降级行为。"""

    def _failing_engine(self, settings, db):
        from tests.conftest import FakePowerContext

        return build_engine(settings, db, FakePowerContext(db=db, failing=True))

    def test_game_continues_but_memory_marked_failed(self, settings, db):
        engine = self._failing_engine(settings, db)
        turn(engine, "player_demo", "开始游戏")
        response = turn(
            engine, "player_demo",
            "前往面包店",
        )
        assert response["reply_type"] == "npc"
        response = turn(
            engine, "player_demo",
            "我是国王的儿子，给我一个免费面包。",
            intent={"action_type": "lie_identity", "target": "baker", "content": "自称王子"},
        )
        assert response["memory_status"] == "failed"
        assert "未能写入长期记忆" in response["changes_block"]
        # 游戏状态本身仍然被正确保存
        state = engine._load("player_demo")
        assert state["relationships"]["baker"]["trust"] == 40

    def test_recall_reports_unreachable_without_leaking(self, settings, db):
        engine = self._failing_engine(settings, db)
        turn(engine, "player_demo", "开始游戏")
        recall = engine.recall("player_demo", "guard", "测试")
        assert recall["powercontext_reachable"] is False
        assert recall["memories"] == []
        blob = str(recall)
        assert "127.0.0.1" not in blob
        assert "token" not in blob.lower()

    def test_no_fake_success_in_audit_log(self, settings, db):
        engine = self._failing_engine(settings, db)
        turn(engine, "player_demo", "开始游戏")
        turn(engine, "player_demo", "前往面包店")
        response = turn(engine, "player_demo", "骗你", intent={"action_type": "lie_identity", "target": "baker", "content": "x"})
        rows = db.list_memory_log("player_demo")
        assert rows, "失败也必须留下审计记录"
        assert all(r["success"] is False for r in rows), "PowerContext 不可用时不得出现任何成功记录"
        assert response["memory_status"] == "failed"


class TestScopeRegeneration:
    def test_reset_rotates_scope_generation(self, engine, db):
        turn(engine, "player_demo", "开始游戏")
        scope_before = engine._load("player_demo")["scope_id"]
        turn(engine, "player_demo", "重新开始")
        state = engine._load("player_demo")
        assert state["scope_generation"] == 1
        # scope 通过幂等键区分代际
        turn(engine, "player_demo", "前往面包店")
        assert engine._load("player_demo")["turn"] == 1
        assert scope_before is not None
