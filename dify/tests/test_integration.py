"""集成测试：跨会话记忆（Test 3）、可重复运行（Test 9）与 API 全链路。

跨会话记忆通过 httpx.MockTransport 驱动真实的 PowerContextClient 代码路径
（官方契约字段），保证「守卫引用的记忆必须来自真实写入」这一验收点。
"""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

from backend.database import Database
from backend.memory_service import PowerContextClient
from tests.conftest import build_engine, mock_transport_factory, turn


class TestCrossSessionMemory:
    """Test 3：两个「会话」间恢复记忆。

    用两套独立 engine 实例模拟两个进程/会话，共享同一个 SQLite 与
    同一个（Mock 的）PowerContext Server 状态。
    """

    def _setup(self, settings, db):
        transport, state = mock_transport_factory()
        memory = PowerContextClient(
            base_url="http://127.0.0.1:8000", timeout=5, max_retries=1, db=db, transport=transport,
        )
        return build_engine(settings, db, memory), memory, state

    def test_guard_remembers_baker_lie_across_sessions(self, settings, db):
        engine_session1, memory, server_state = self._setup(settings, db)

        # ===== 会话 1：面包店行骗 =====
        turn(engine_session1, "player_demo", "开始游戏")
        turn(engine_session1, "player_demo", "前往面包店")
        turn(
            engine_session1, "player_demo",
            "其实我是国王的儿子，给我一个免费面包。",
            intent={"action_type": "lie_identity", "target": "baker", "content": "自称是国王的儿子"},
        )
        assert any("自称" in t or "国王" in t for texts in [server_state["memories"].values()] for t in list(texts)[0])

        # ===== 新会话（新 engine 实例 = 不依赖 Dify conversation_id）=====
        engine_session2, _, _ = self._setup(settings, db)
        response = turn(engine_session2, "player_demo", "前往城门")
        assert response["reply_type"] == "npc"
        assert response["npc"] == "guard"
        context = response["context_text"]
        # 守卫的上下文必须包含从 PowerContext 召回的内容或传播的传闻
        assert "国王的儿子" in context or "王子" in context
        assert "【听到的传闻】" in context
        # 且传闻可追溯到真实保存过的事件
        rumors = db.list_rumors("player_demo", holder="guard")
        assert rumors
        root_event = db.get_event(rumors[0]["root_event_id"])
        assert root_event is not None
        assert root_event["action"] == "lie_identity"

    def test_memory_recall_traceable_to_write_log(self, settings, db):
        engine, memory, _ = self._setup(settings, db)
        turn(engine, "player_demo", "开始游戏")
        turn(engine, "player_demo", "前往面包店")
        turn(engine, "player_demo", "骗你", intent={"action_type": "lie_identity", "target": "baker", "content": "自称王子"})
        log = db.list_memory_log("player_demo")
        writes = [r for r in log if r["operation"] == "remember" and r["success"]]
        assert writes, "必须存在成功的 PowerContext 写入记录"
        recalls = [r for r in log if r["operation"] in ("prepare", "search")]
        assert recalls


class TestRepeatability:
    """Test 9：重置 + 固定随机种子 -> 可重复验证。"""

    def _run_script(self, settings, player_id):
        db = Database(settings.db_path.parent / f"{player_id}.db")
        transport, _ = mock_transport_factory()
        from backend.memory_service import PowerContextClient

        memory = PowerContextClient("http://x", transport=transport, db=db, max_retries=0)
        engine = build_engine(settings, db, memory)
        turn(engine, player_id, "开始游戏")
        turn(engine, player_id, "前往面包店")
        turn(engine, player_id, "骗你", intent={"action_type": "lie_identity", "target": "baker", "content": "自称王子"})
        turn(engine, player_id, "前往城门")
        state = engine._load(player_id)
        rumors = sorted((r["holder"], r["content"], r["confidence"]) for r in db.list_rumors(player_id))
        db.db_path.unlink(missing_ok=True)
        return state["relationships"], rumors

    def test_reset_and_rerun_produces_identical_results(self, settings):
        rel_a, rumors_a = self._run_script(settings, "run_a")
        rel_b, rumors_b = self._run_script(settings, "run_b")
        assert rel_a == rel_b
        assert rumors_a == rumors_b


class TestApiIntegration:
    """FastAPI 全链路（Dify HTTP Request 节点实际调用的端点）。"""

    def _client(self, settings, db):
        transport, _ = mock_transport_factory()
        import backend.main as main_mod

        app = main_mod.create_app(settings)
        # 把 app 内部的 memory client 换成带 MockTransport 的（保留真实代码路径）
        from backend.memory_service import PowerContextClient

        app.state.engine.memory = PowerContextClient(
            "http://x", transport=transport, db=app.state.engine.db, max_retries=0,
        )
        app.state.engine.memory.db = app.state.engine.db
        return TestClient(app)

    def test_full_flow_via_http_api(self, settings, db):
        client = self._client(settings, db)
        assert client.get("/health").json()["status"] == "ok"

        # turn: start
        r = client.post("/api/game/turn", json={"player_id": "player_demo", "message": "开始游戏"})
        assert r.status_code == 200
        assert "记仇小镇" in r.json()["rendered_text"]

        # turn: move with intent_json from Dify code node
        r = client.post("/api/game/turn", json={
            "player_id": "player_demo", "message": "前往面包店",
            "intent_json": json.dumps({"action_type": "move", "target": "bakery"}),
        })
        assert r.json()["reply_type"] == "npc"

        # turn: natural language lie with LLM intent JSON
        r = client.post("/api/game/turn", json={
            "player_id": "player_demo", "message": "我是国王的儿子，给我一个免费面包",
            "intent_json": json.dumps({"action_type": "lie_identity", "target": "baker", "amount": None, "content": "自称是国王的儿子"}),
        })
        body = r.json()
        assert body["npc"] == "baker"
        assert body["memory_status"] == "saved"
        assert "声望" in body["changes_block"]

        # recall endpoint（模拟第二次会话的守卫场景）
        r = client.post("/api/memory/recall", json={"player_id": "player_demo", "npc_id": "guard", "query": "王子 国王的儿子"})
        recall = r.json()
        assert recall["powercontext_reachable"] is True
        assert recall["memories"], "守卫应能召回此前写入的长期记忆"

        # news endpoint
        r = client.post("/api/game/news", json={"player_id": "player_demo"})
        assert r.json()["news"]

        # reset endpoint
        r = client.post("/api/game/reset", json={"player_id": "player_demo"})
        assert r.json()["success"] is True
        r = client.post("/api/game/state", json={"player_id": "player_demo"})
        assert r.json()["state"]["turn"] == 0
        assert r.json()["state"]["coins"] == 100

    def test_validation_error_returns_unified_envelope(self, settings, db):
        client = self._client(settings, db)
        r = client.post("/api/game/turn", json={"player_id": "", "message": "x"})
        assert r.status_code == 422
        assert r.json()["error"]["code"] == "invalid_request"

    def test_memory_log_endpoint_masks_scope(self, settings, db):
        client = self._client(settings, db)
        client.post("/api/game/turn", json={"player_id": "p1", "message": "开始游戏"})
        client.post("/api/game/turn", json={"player_id": "p1", "message": "前往面包店"})
        client.post("/api/game/turn", json={
            "player_id": "p1", "message": "骗你",
            "intent_json": json.dumps({"action_type": "lie_identity", "target": "baker", "content": "x"}),
        })
        r = client.get("/api/memory/log", params={"player_id": "p1"})
        rows = r.json()["log"]
        assert rows
        assert all(row["scope_id_masked"] is None or "***" in (row["scope_id_masked"] or "***") for row in rows)
