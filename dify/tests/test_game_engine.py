"""游戏引擎/状态机测试（Test 1 / 2 / 5 / 7 / 9 相关）。"""

from __future__ import annotations

from tests.conftest import turn


class TestStartGame:
    """Test 1：初次进入。"""

    def test_start_creates_player_with_initial_values(self, engine, db):
        response = turn(engine, "player_demo", "开始游戏")
        assert response["reply_type"] == "direct"
        assert "记仇小镇" in response["rendered_text"]
        state = db.get_player("player_demo")
        assert state["coins"] == 100
        assert state["reputation"] == 50
        assert state["location"] == "square"
        relationships = __import__("json").loads(state["relationships"])
        assert relationships["baker"] == {"affection": 50, "trust": 50}
        assert relationships["guard"] == {"affection": 50, "trust": 60}
        assert relationships["witch"] == {"affection": 50, "trust": 40}

    def test_actions_before_start_are_rejected(self, engine):
        response = turn(engine, "player_demo", "前往面包店")
        assert "开始游戏" in response["rendered_text"]
        assert response["game_over"] is False

    def test_scope_created_on_start(self, engine, fake_memory):
        turn(engine, "player_demo", "开始游戏")
        assert any(c["op"] == "create_scope" for c in fake_memory.calls)


class TestInteraction:
    """Test 2：人物互动。"""

    def test_move_to_bakery_then_lie(self, engine, db):
        turn(engine, "player_demo", "开始游戏")
        turn(engine, "player_demo", "前往面包店")
        state = db.get_player("player_demo")
        assert state["location"] == "bakery"
        assert state["turn"] == 1

        response = turn(
            engine, "player_demo",
            "我是国王的儿子，给我一个免费面包。",
            intent={"action_type": "lie_identity", "target": "baker", "content": "自称是国王的儿子"},
        )
        assert response["reply_type"] == "npc"
        assert response["npc"] == "baker"
        assert response["event_id"] is not None
        assert response["memory_status"] == "saved"

        state = db.get_player("player_demo")
        relationships = __import__("json").loads(state["relationships"])
        assert relationships["baker"]["trust"] == 40
        assert relationships["baker"]["affection"] == 45
        assert state["reputation"] == 45
        assert state["turn"] == 2

    def test_event_recorded_and_traceable(self, engine, db):
        turn(engine, "player_demo", "开始游戏")
        turn(engine, "player_demo", "前往面包店")
        turn(engine, "player_demo", "骗你", intent={"action_type": "lie_identity", "target": "baker", "content": "自称王子"})
        events = db.list_events("player_demo")
        assert len(events) == 1
        assert events[0]["action"] == "lie_identity"
        assert events[0]["target"] == "baker"
        assert events[0]["importance"] == 8
        assert events[0]["truth_status"] == "verified"
        assert events[0]["witnesses"] == ["baker"]

    def test_target_must_be_present(self, engine):
        turn(engine, "player_demo", "开始游戏")
        response = turn(engine, "player_demo", "我偷个面包", intent={"action_type": "steal", "target": "baker"})
        assert "先「前往" in response["rendered_text"]
        assert response["reply_type"] == "direct"

    def test_invalid_intent_degrades_to_chat(self, engine):
        turn(engine, "player_demo", "开始游戏")
        turn(engine, "player_demo", "前往面包店")
        response = turn(engine, "player_demo", "我要飞升成仙", intent={"action_type": "hack_the_game", "target": "baker"})
        assert response["reply_type"] == "npc"
        assert db_events_count(engine, "player_demo") == 0

    def test_insufficient_coins_rejected(self, engine, db):
        turn(engine, "player_demo", "开始游戏")
        turn(engine, "player_demo", "前往面包店")
        import json as jsonlib

        state = db.get_player("player_demo")
        state["coins"] = 3
        db.upsert_player({**state, "inventory": jsonlib.loads(state["inventory"]), "relationships": jsonlib.loads(state["relationships"]), "quests": jsonlib.loads(state["quests"])})
        response = turn(engine, "player_demo", "买面包", intent={"action_type": "buy", "target": "baker"})
        assert "金币不够" in response["rendered_text"]


class TestApologyAndCompensation:
    """Test 5：道歉与补救。"""

    def _steal_bread(self, engine):
        turn(engine, "player_demo", "开始游戏")
        turn(engine, "player_demo", "前往面包店")
        turn(engine, "player_demo", "偷面包", intent={"action_type": "steal", "target": "baker"})
        return engine._load("player_demo")

    def test_compensate_restores_trust_and_resolves_event(self, engine, db):
        state = self._steal_bread(engine)
        assert state["relationships"]["baker"]["trust"] == 25
        response = turn(engine, "player_demo", "我赔你 10 金币", intent={"action_type": "compensate", "target": "baker", "amount": 10})
        state = engine._load("player_demo")
        assert state["relationships"]["baker"]["trust"] == 40
        assert state["relationships"]["baker"]["affection"] >= 35
        assert state["coins"] == 100 - 10  # 偷窃不产生金币，只获得物品；赔偿 10 金币
        events = db.list_events("player_demo")
        steal = [e for e in events if e["action"] == "steal"][0]
        assert steal["resolved"] is True
        assert response["memory_status"] == "saved"

    def test_apology_without_grudge_is_weak(self, engine, db):
        turn(engine, "player_demo", "开始游戏")
        turn(engine, "player_demo", "前往面包店")
        response = turn(engine, "player_demo", "对不起", intent={"action_type": "apologize", "target": "baker"})
        state = engine._load("player_demo")
        # 没有旧账时效果按 0.25 缩放：affection +5*0.25=+1, trust +8*0.25=+2
        assert state["relationships"]["baker"]["affection"] == 51
        assert state["relationships"]["baker"]["trust"] == 52


class TestEndings:
    """Test 7：游戏结局（可复现场景）。"""

    def test_exile_immediate(self, engine, db):
        import json as jsonlib

        from backend.config import load_json

        scenario = load_json("scenarios.json")["scenarios"]["exile"]
        turn(engine, "player_demo", "开始游戏")
        state = engine._load("player_demo")
        state["reputation"] = scenario["state"]["reputation"]
        state["coins"] = scenario["state"]["coins"]
        engine._save(state)
        turn(engine, "player_demo", "前往面包店")
        state = engine._load("player_demo")
        assert state["game_over"] is True
        assert state["ending"] == "exile"

    def test_hero_ending_at_max_turns(self, engine, db):
        turn(engine, "player_demo", "开始游戏")
        turn(engine, "player_demo", "前往面包店")
        turn(engine, "player_demo", "帮忙搬面粉", intent={"action_type": "help", "target": "baker"})
        state = engine._load("player_demo")
        state["turn"] = 9
        state["reputation"] = 82
        engine._save(state)
        turn(engine, "player_demo", "前往城门")
        state = engine._load("player_demo")
        assert state["turn"] == 10
        assert state["game_over"] is True
        assert state["ending"] == "hero"

    def test_wanderer_ending(self, engine):
        turn(engine, "player_demo", "开始游戏")
        state = engine._load("player_demo")
        state["turn"] = 9
        engine._save(state)
        turn(engine, "player_demo", "前往城门")
        state = engine._load("player_demo")
        assert state["ending"] == "wanderer"

    def test_game_over_blocks_actions(self, engine):
        turn(engine, "player_demo", "开始游戏")
        state = engine._load("player_demo")
        state["reputation"] = 5
        engine._save(state)
        turn(engine, "player_demo", "前往城门")
        response = turn(engine, "player_demo", "偷东西", intent={"action_type": "steal", "target": "guard"})
        assert "游戏已经结束" in response["rendered_text"]


class TestIdempotency:
    """关键状态更新幂等保护。"""

    def test_same_request_id_returns_same_response(self, engine, db):
        turn(engine, "player_demo", "开始游戏")
        turn(engine, "player_demo", "前往面包店")
        first = turn(engine, "player_demo", "骗你", intent={"action_type": "lie_identity", "target": "baker"}, request_id="req-42")
        second = turn(engine, "player_demo", "骗你", intent={"action_type": "lie_identity", "target": "baker"}, request_id="req-42")
        assert first == second
        state = db.get_player("player_demo")
        assert __import__("json").loads(state["relationships"])["baker"]["trust"] == 40
        events = db.list_events("player_demo")
        assert len([e for e in events if e["action"] == "lie_identity"]) == 1


def db_events_count(engine, player_id) -> int:
    return len(engine.db.list_events(player_id))
