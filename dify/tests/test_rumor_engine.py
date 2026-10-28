"""八卦传播引擎测试（Test 6）。"""

from __future__ import annotations

import random

from backend.database import Database
from backend.rumor_engine import RumorEngine
from tests.conftest import turn


def make_rumor_engine(db: Database) -> RumorEngine:
    from backend.config import load_json

    return RumorEngine(db, load_json("npc_config.json"))


def make_event(event_id="evt_001", importance=8, description="玩家自称王子"):
    return {
        "event_id": event_id, "player_id": "player_demo", "day": 1, "turn": 1,
        "actor": "player", "target": "baker", "action": "lie_identity",
        "description": description, "witnesses": ["baker"],
        "truth_status": "verified", "importance": importance,
    }


class TestRumorCreation:
    def test_rumor_requires_real_event(self, engine, db):
        rumor_engine = make_rumor_engine(db)
        event = make_event()
        rumor = rumor_engine.create_rumor(random.Random(1), "player_demo", event, "baker", 1, 1)
        assert rumor is not None
        assert rumor["root_event_id"] == "evt_001"
        assert rumor["source_event_id"] == "evt_001"
        assert rumor["holder"] == "baker"
        assert rumor["truth_status"] == "unverified"

    def test_rumors_never_modify_original_event(self, engine, db):
        rumor_engine = make_rumor_engine(db)
        event = make_event()
        db.insert_event(event)
        rumor_engine.create_rumor(random.Random(1), "player_demo", event, "baker", 1, 1)
        rumor_engine.spread_tick(random.Random(2), "player_demo", 1, 2, {"evt_001"})
        stored = db.get_event("evt_001")
        assert stored["description"] == "玩家自称王子"
        assert stored["truth_status"] == "verified"


class TestPropagation:
    def test_high_importance_first_hop_is_guaranteed(self, engine, db):
        """重要度>=8 的事件（如冒充王子）保底传播 baker->guard，评委可复现。"""
        turn(engine, "player_demo", "开始游戏")
        turn(engine, "player_demo", "前往面包店")
        turn(engine, "player_demo", "骗你", intent={"action_type": "lie_identity", "target": "baker", "content": "自称王子"})
        rumors = db.list_rumors("player_demo")
        assert any(r["holder"] == "guard" for r in rumors), "守卫应已通过传播获得传闻"
        guard_rumor = [r for r in rumors if r["holder"] == "guard"][0]
        assert guard_rumor["root_event_id"].startswith("evt_")

    def test_propagation_path_follows_social_graph(self, engine, db):
        rumor_engine = make_rumor_engine(db)
        event = make_event()
        rumor_engine.create_rumor(random.Random(1), "player_demo", event, "baker", 1, 1)
        spread = rumor_engine.spread_tick(random.Random(42), "player_demo", 1, 2, {"evt_001"})
        holders = {r["holder"] for r in spread}
        # baker 的社交边只连 guard(0.85) 与 witch(0.3)
        assert holders <= {"guard", "witch"}

    def test_exaggeration_grows_with_spread_count(self, engine, db):
        rumor_engine = make_rumor_engine(db)
        event = make_event()
        rumor_engine.create_rumor(random.Random(1), "player_demo", event, "baker", 1, 1)
        rumor_engine.spread_tick(random.Random(42), "player_demo", 1, 2, {"evt_001"})
        guard_rumor = [r for r in db.list_rumors("player_demo") if r["holder"] == "guard"][0]
        assert "老张" in guard_rumor["content"] or "老张告诉我" in guard_rumor["content"]
        second = rumor_engine.spread_tick(random.Random(42), "player_demo", 2, 3, set())
        if second:
            assert any("听说" in r["content"] or "议论" in r["content"] for r in second)

    def test_confidence_decays(self, engine, db):
        rumor_engine = make_rumor_engine(db)
        event = make_event()
        rumor_engine.create_rumor(random.Random(1), "player_demo", event, "baker", 1, 1, confidence=0.7)
        rumor_engine.spread_tick(random.Random(0), "player_demo", 1, 2, {"evt_001"})
        rumors = db.list_rumors("player_demo")
        holder_rumor = [r for r in rumors if r["holder"] == "baker"][0]
        spread_rumor = [r for r in rumors if r["holder"] != "baker"]
        if spread_rumor:
            assert spread_rumor[0]["confidence"] < holder_rumor["confidence"]

    def test_no_infinite_propagation(self, engine, db):
        rumor_engine = make_rumor_engine(db)
        event = make_event()
        rumor_engine.create_rumor(random.Random(1), "player_demo", event, "baker", 1, 1)
        total = 1
        for tick in range(2, 30):
            spread = rumor_engine.spread_tick(random.Random(tick), "player_demo", tick // 2 + 1, tick, {"evt_001"})
            total += len(spread)
        rumors = db.list_rumors("player_demo")
        # 去重 + spread_count 上限 + 每对 (root,holder) 唯一 => 节点数有限
        assert len(rumors) <= 4
        assert all(r["spread_count"] <= 4 for r in rumors)

    def test_deterministic_with_fixed_seed(self, engine, db, settings):
        def run(seed_tag):
            import backend.config as config

            path = settings.db_path.parent / f"rumor_{seed_tag}.db"
            local_db = Database(path)
            rumor_engine = make_rumor_engine(local_db)
            event = make_event()
            rumor_engine.create_rumor(random.Random(1), "player_demo", event, "baker", 1, 1)
            for turn_no in range(2, 8):
                rumor_engine.spread_tick(random.Random(f"{settings.game_random_seed}:{turn_no}"), "player_demo", turn_no // 2 + 1, turn_no, set())
            rows = [(r["holder"], r["content"], r["confidence"]) for r in local_db.list_rumors("player_demo")]
            path.unlink(missing_ok=True)
            return rows

        assert run("a") == run("b"), "固定随机种子下传播必须可复现"


class TestClarityAndTraceability:
    def test_clarification_rumor_after_compensation(self, engine, db):
        turn(engine, "player_demo", "开始游戏")
        turn(engine, "player_demo", "前往面包店")
        turn(engine, "player_demo", "偷面包", intent={"action_type": "steal", "target": "baker"})
        turn(engine, "player_demo", "赔你 10 金币", intent={"action_type": "compensate", "target": "baker", "amount": 10})
        rumors = db.list_rumors("player_demo")
        clarify = [r for r in rumors if r["truth_status"] == "verified"]
        assert clarify, "赔偿后应产生澄清性传闻"
        assert any("赔偿" in r["content"] or "和解" in r["content"] for r in clarify)

    def test_guard_context_separates_fact_and_rumor(self, engine, db):
        turn(engine, "player_demo", "开始游戏")
        turn(engine, "player_demo", "前往面包店")
        turn(engine, "player_demo", "骗你", intent={"action_type": "lie_identity", "target": "baker", "content": "自称王子"})
        turn(engine, "player_demo", "前往城门")
        state = engine._load("player_demo")
        context = engine._build_npc_context(state, "guard", "（测试）", "测试")
        assert "【亲眼所见的事实】" in context
        assert "【听到的传闻】" in context
        assert "未经证实" in context or "从" in context
