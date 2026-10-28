"""PowerContext 客户端测试：真实代码路径 + MockTransport。

不用 SQLite 冒充 PowerContext——这里驱动的是真实的 PowerContextClient
（httpx + 官方契约字段），只是把网络层替换为 MockTransport。
"""

from __future__ import annotations

import httpx
import pytest

from backend.memory_service import PowerContextClient, mask_scope
from tests.conftest import mock_transport_factory


def make_client(db, **kw):
    transport, state = mock_transport_factory(**kw)
    client = PowerContextClient(
        base_url="http://127.0.0.1:8000",
        token="secret-token",
        timeout=5,
        max_retries=1,
        db=db,
        transport=transport,
    )
    return client, state


class TestScope:
    def test_create_scope_returns_id_and_idempotent(self, db):
        client, _ = make_client(db)
        first = client.create_scope("p1", "grudgetown-p1-gen0")
        second = client.create_scope("p1", "grudgetown-p1-gen0")
        assert first is not None
        assert first == second

    def test_scope_is_masked_in_log(self, db):
        client, _ = make_client(db)
        client.create_scope("p1", "grudgetown-p1-gen0")
        rows = db.list_memory_log("p1")
        assert rows[0]["operation"] == "create_scope"
        assert rows[0]["success"] is True
        assert rows[0]["scope_id_masked"] == mask_scope("scope-real-0")
        assert "scope-real-0" not in (rows[0]["scope_id_masked"] or "")

    def test_authorization_header_sent(self, db):
        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["auth"] = request.headers.get("Authorization")
            return httpx.Response(201, json={"scope_id": "s1"})

        client = PowerContextClient("http://x", token="tok", transport=httpx.MockTransport(handler), db=db)
        client.create_scope("p1", "k")
        assert captured["auth"] == "Bearer tok"


class TestRemember:
    def test_remember_returns_records_and_logs(self, db):
        client, state = make_client(db)
        result = client.remember("p1", "scope-real-0", "第1天玩家自称王子", "事件", event_id="evt_001")
        assert result["success"] is True
        assert result["records"]
        assert "第1天玩家自称王子" in state["memories"]["scope-real-0"]
        rows = db.list_memory_log("p1")
        assert rows[0]["operation"] == "remember"
        assert rows[0]["event_id"] == "evt_001"
        assert rows[0]["success"] is True

    def test_remember_failure_is_logged_not_faked(self, db):
        client, _ = make_client(db, failing=True)
        result = client.remember("p1", "scope-real-0", "text", "reason")
        assert result["success"] is False
        rows = db.list_memory_log("p1")
        assert rows[0]["success"] is False
        assert "不可达" in rows[0]["detail"]


class TestSearchAndPrepare:
    def test_search_returns_entries(self, db):
        client, _ = make_client(db)
        client.remember("p1", "scope-real-0", "玩家对老张自称王子", "事件")
        result = client.search("p1", "scope-real-0", "老张 王子")
        assert result["success"] is True
        assert any("王子" in e for e in result["entries"])

    def test_prepare_returns_bounded_content(self, db):
        client, _ = make_client(db)
        client.remember("p1", "scope-real-0", "记忆A", "事件")
        result = client.prepare("p1", "scope-real-0", "记忆")
        assert result["success"] is True
        assert result["status"] == "ready"
        assert "记忆A" in result["content"]

    def test_prepare_empty_scope_returns_empty_status(self, db):
        client, _ = make_client(db)
        result = client.prepare("p1", "scope-real-0", "不存在的东西")
        assert result["status"] == "empty"
        assert result["content"] is None


class TestErrorContract:
    def test_error_envelope_is_parsed(self, db):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(422, json={"error": {"code": "invalid_request", "message": "bad", "details": {}}})

        client = PowerContextClient("http://x", transport=httpx.MockTransport(handler), db=db, max_retries=0)
        result = client.remember("p1", "s", "text", "reason")
        assert result["success"] is False
        assert "invalid_request" in result["error"]

    def test_health_reports_unreachable(self, db):
        client, _ = make_client(db, failing=True)
        assert client.health() is False

    def test_no_secrets_in_logs(self, db):
        client, _ = make_client(db)
        client.remember("p1", "scope-real-0", "text", "reason")
        for row in db.list_memory_log("p1"):
            blob = str(row)
            assert "secret-token" not in blob


@pytest.mark.parametrize("raw,masked", [(None, None), ("abc", "***"), ("abcdefgh1234", "abcdefgh***")])
def test_mask_scope(raw, masked):
    assert mask_scope(raw) == masked
