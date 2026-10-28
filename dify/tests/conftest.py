"""共享测试夹具。"""

from __future__ import annotations

import sys
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.config import Settings, load_json  # noqa: E402
from backend.database import Database  # noqa: E402
from backend.game_engine import GameEngine  # noqa: E402
from backend.memory_service import PowerContextClient  # noqa: E402
from backend.models import TurnRequest  # noqa: E402
from backend.rumor_engine import RumorEngine  # noqa: E402


class FakePowerContext:
    """内存版 PowerContext：行为对齐真实接口（scope/remember/search/prepare）。

    用于单元测试；集成测试用 httpx.MockTransport 驱动真实的
    PowerContextClient 代码路径。
    """

    def __init__(self, db=None, failing: bool = False):
        self.db = db
        self.scopes: dict[str, dict] = {}
        self.memories: dict[str, list[dict]] = {}
        self.calls: list[dict] = []
        self.failing = failing

    def _log(self, player_id, operation, success, event_id=None, scope_id=None, detail=None):
        if self.db is None:
            return
        from backend.memory_service import mask_scope

        self.db.log_memory(
            player_id=player_id, operation=operation, success=success,
            event_id=event_id, scope_id_masked=mask_scope(scope_id),
            request_id="mock-req", detail=detail,
        )

    def health(self) -> bool:
        return not self.failing

    def create_scope(self, player_id: str, idempotency_key: str) -> str | None:
        self.calls.append({"op": "create_scope", "player_id": player_id})
        self._log(player_id, "create_scope", not self.failing)
        if self.failing:
            return None
        if idempotency_key in self.scopes:
            return self.scopes[idempotency_key]["scope_id"]
        scope_id = f"scope-{idempotency_key}-{len(self.scopes)}"
        self.scopes[idempotency_key] = {"scope_id": scope_id}
        return scope_id

    def remember(self, player_id, scope_id, text, reason, event_id=None):
        self.calls.append({"op": "remember", "player_id": player_id, "scope_id": scope_id, "text": text, "event_id": event_id})
        self._log(player_id, "remember", not self.failing, event_id=event_id, scope_id=scope_id)
        if self.failing:
            return {"success": False, "records": [], "request_id": None, "error": "PowerContext 不可达"}
        self.memories.setdefault(scope_id, []).append({"text": text, "event_id": event_id})
        return {"success": True, "records": [{"artifact": "art"}], "request_id": "req-1", "error": None}

    def search(self, player_id, scope_id, query, limit=5):
        self.calls.append({"op": "search", "player_id": player_id, "scope_id": scope_id, "query": query})
        self._log(player_id, "search", not self.failing, scope_id=scope_id)
        if self.failing:
            return {"success": False, "entries": [], "error": "PowerContext 不可达"}
        hits = [m["text"] for m in self.memories.get(scope_id, []) if any(w in m["text"] for w in query.split()[:3])]
        return {"success": True, "entries": hits, "error": None}

    def prepare(self, player_id, scope_id, query, max_bytes=3000):
        self.calls.append({"op": "prepare", "player_id": player_id, "scope_id": scope_id, "query": query})
        self._log(player_id, "prepare", not self.failing, scope_id=scope_id)
        if self.failing:
            return {"success": False, "status": "error", "content": None, "error": "PowerContext 不可达"}
        entries = [m["text"] for m in self.memories.get(scope_id, [])]
        if not entries:
            return {"success": True, "status": "empty", "content": None, "error": None}
        return {"success": True, "status": "ready", "content": "\n".join(entries)[:max_bytes], "error": None}


@pytest.fixture()
def settings(tmp_path):
    return Settings(
        database_url=f"sqlite:///{tmp_path}/test.db",
        db_path=tmp_path / "test.db",
        game_default_coins=100,
        game_max_turns=10,
        game_random_seed=42,
        game_turns_per_day=2,
        memory_importance_threshold=5,
    )


@pytest.fixture()
def db(settings):
    return Database(settings.db_path)


@pytest.fixture()
def fake_memory(db):
    return FakePowerContext(db=db)


def build_engine(settings, db, memory) -> GameEngine:
    return GameEngine(
        db=db,
        settings=settings,
        rules=load_json("rules.json"),
        npc_config=load_json("npc_config.json"),
        initial_state=load_json("initial_state.json"),
        rumor_engine=RumorEngine(db, load_json("npc_config.json")),
        memory=memory,
    )


@pytest.fixture()
def engine(settings, db, fake_memory):
    return build_engine(settings, db, fake_memory)


def turn(engine, player_id: str, message: str, intent: dict | None = None, request_id: str | None = None) -> dict:
    req = TurnRequest(player_id=player_id, message=message)
    if intent is not None:
        import json

        req = TurnRequest(player_id=player_id, message=message, intent_json=json.dumps(intent, ensure_ascii=False), request_id=request_id)
    return engine.handle_turn(req)


def mock_transport_factory(state: dict | None = None, failing: bool = False):
    """构造行为对齐真实 PowerContext 的 MockTransport。"""
    state = state if state is not None else {"scopes": {}, "memories": {}}

    def handler(request: httpx.Request) -> httpx.Response:
        if failing:
            raise httpx.ConnectError("connection refused")
        path = request.url.path
        payload = {}
        if request.content:
            payload = json.loads(request.content) if request.content else {}
        if path == "/health/live":
            return httpx.Response(200, json={"status": "ok"})
        if path == "/v1/scopes":
            key = payload["idempotency_key"]
            if key not in state["scopes"]:
                state["scopes"][key] = f"scope-real-{len(state['scopes'])}"
            return httpx.Response(201, json={"scope_id": state["scopes"][key]}, headers={"X-PowerContext-Request-ID": "r-1"})
        if path == "/v1/memory/remember":
            scope = payload["scope_id"]
            state["memories"].setdefault(scope, []).append(payload["text"])
            return httpx.Response(
                200,
                json={"records": [{"artifact": {"id": "art"}, "state_version": 1}]},
                headers={"X-PowerContext-Request-ID": "r-2"},
            )
        if path == "/v1/memory/search":
            scope = payload["scope_id"]
            query = payload["query"]
            # 模拟真实服务器的全文检索：分词后任一命中即返回（“玩家”也是可命中词）。
            words = [w for w in query.split() if w]
            hits = [t for t in state["memories"].get(scope, []) if any(w in t for w in words[:4])]
            # 响应结构与真实 PowerContext v0.1.0 一致：{"mode":"text","hits":[{"memory":{"text":...}}]}
            return httpx.Response(
                200,
                json={
                    "mode": "text",
                    "hits": [
                        {
                            "memory": {"artifact": {"artifact_id": "art-1", "revision": 1}, "kind": "decision", "text": h, "state": "active"},
                            "score": 0.1,
                            "matched_by": ["text"],
                        }
                        for h in hits[: payload.get("limit", 5)]
                    ],
                },
                headers={"X-PowerContext-Request-ID": "r-3"},
            )
        if path == "/v1/context/prepare":
            scope = payload["scope_id"]
            entries = state["memories"].get(scope, [])
            if not entries:
                return httpx.Response(200, json={"status": "empty", "content": None})
            content = "\n".join(f"- {t}" for t in entries)[: payload.get("max_bytes", 3000)]
            return httpx.Response(200, json={"status": "ready", "content": content})
        return httpx.Response(404, json={"error": {"code": "not_found", "message": path, "details": {}}})

    import json

    return httpx.MockTransport(handler), state


import json  # noqa: E402
