"""PowerContext HTTP client.

只依据官方文档核实过的字段实现（https://powercontext.oceanbase.io/zh/docs/develop/）：
  POST /v1/scopes            {"title", "summary", "idempotency_key"} -> {"scope_id"}
  POST /v1/memory/remember   {"scope_id", "kind", "text", "reason"?}  -> {"records": [...]}
  POST /v1/memory/search     {"scope_id", "query", "limit"}           -> 记忆条目列表
  POST /v1/context/prepare   {"scope_id", "query", "max_bytes"}       -> {"status", "content"}
鉴权：Authorization: Bearer <token>（本地 loopback 默认关闭鉴权）。
所有调用结果都会写入 memory_log 审计表；失败绝不假装成功。
"""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx

from backend.database import Database

logger = logging.getLogger("grudgetown.memory")


class PowerContextError(RuntimeError):
    def __init__(self, message: str, status_code: int | None = None, code: str | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.code = code


def mask_scope(scope_id: str | None) -> str | None:
    if not scope_id:
        return None
    return scope_id[:8] + "***" if len(scope_id) > 8 else "***"


class PowerContextClient:
    def __init__(
        self,
        base_url: str,
        token: str = "",
        timeout: float = 10.0,
        max_retries: int = 2,
        db: Database | None = None,
        transport: httpx.BaseTransport | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout
        self.max_retries = max_retries
        self.db = db
        self._transport = transport

    # -- low level ---------------------------------------------------------

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def _request(self, method: str, path: str, payload: dict[str, Any] | None, timeout: float | None):
        with httpx.Client(transport=self._transport) as client:
            return client.request(
                method,
                f"{self.base_url}{path}",
                json=payload,
                headers=self._headers(),
                timeout=timeout or self.timeout,
            )

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                response = self._request("POST", path, payload, None)
                request_id = response.headers.get("X-PowerContext-Request-ID")
                if response.status_code >= 400:
                    body = {}
                    try:
                        body = response.json()
                    except Exception:
                        body = {"raw": response.text[:200]}
                    err = body.get("error", {})
                    raise PowerContextError(
                        f"HTTP {response.status_code}: {err.get('code', 'unknown')}: {err.get('message', body)}",
                        status_code=response.status_code,
                        code=err.get("code"),
                    )
                result = response.json()
                if isinstance(result, dict) and request_id:
                    result["_request_id"] = request_id
                return result
            except PowerContextError:
                raise
            except (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout, httpx.RemoteProtocolError) as exc:
                last_error = exc
                if attempt < self.max_retries:
                    time.sleep(0.5 * (attempt + 1))
                    continue
                raise PowerContextError(f"PowerContext 不可达: {type(exc).__name__}") from exc
        raise PowerContextError(f"PowerContext 请求失败: {last_error}")

    def _log(
        self,
        player_id: str,
        operation: str,
        success: bool,
        event_id: str | None = None,
        scope_id: str | None = None,
        request_id: str | None = None,
        detail: str | None = None,
    ) -> None:
        if self.db is None:
            return
        try:
            self.db.log_memory(
                player_id=player_id,
                operation=operation,
                success=success,
                event_id=event_id,
                scope_id_masked=mask_scope(scope_id),
                request_id=request_id,
                detail=detail[:500] if detail else None,
            )
        except Exception:
            logger.exception("写入 memory_log 失败（不影响游戏状态）")

    # -- public API ----------------------------------------------------------

    def health(self) -> bool:
        try:
            response = self._request("GET", "/health/live", None, min(self.timeout, 5.0))
            return response.status_code == 200
        except httpx.HTTPError:
            return False

    def create_scope(self, player_id: str, idempotency_key: str) -> str | None:
        """创建（或按幂等键复用）玩家隔离的记忆 Scope。仅由可信后端调用。"""
        try:
            result = self._post(
                "/v1/scopes",
                {
                    "title": f"GrudgeTown {player_id}",
                    "summary": f"记仇小镇玩家 {player_id} 的长期游戏记忆",
                    "idempotency_key": idempotency_key,
                },
            )
            scope_id = result.get("scope_id")
            self._log(
                player_id, "create_scope", bool(scope_id), scope_id=scope_id,
                request_id=result.get("_request_id"),
                detail=f"idempotency_key={idempotency_key}",
            )
            return scope_id
        except PowerContextError as exc:
            self._log(player_id, "create_scope", False, detail=str(exc))
            return None

    def remember(self, player_id: str, scope_id: str, text: str, reason: str, event_id: str | None = None) -> dict[str, Any]:
        """写入一条长期记忆。返回 {"success", "records", "request_id", "error"}。"""
        try:
            result = self._post(
                "/v1/memory/remember",
                {"scope_id": scope_id, "kind": "decision", "text": text, "reason": reason},
            )
            records = result.get("records", [])
            self._log(
                player_id, "remember", True, event_id=event_id, scope_id=scope_id,
                request_id=result.get("_request_id"),
                detail=f"records={len(records)}",
            )
            return {"success": True, "records": records, "request_id": result.get("_request_id"), "error": None}
        except PowerContextError as exc:
            self._log(player_id, "remember", False, event_id=event_id, scope_id=scope_id, detail=str(exc))
            return {"success": False, "records": [], "request_id": None, "error": str(exc)}

    def search(self, player_id: str, scope_id: str, query: str, limit: int = 5) -> dict[str, Any]:
        """按语义检索活跃记忆。返回 {"success", "entries", "error"}。"""
        try:
            result = self._post(
                "/v1/memory/search",
                {"scope_id": scope_id, "query": query, "limit": limit},
            )
            entries = (
                result.get("hits")
                or result.get("entries")
                or result.get("records")
                or result.get("results")
                or []
            )
            texts: list[str] = []
            for entry in entries:
                if isinstance(entry, dict):
                    memory = entry.get("memory")
                    if isinstance(memory, dict):
                        text = memory.get("text") or memory.get("content") or memory.get("body")
                    else:
                        text = entry.get("text") or entry.get("content") or entry.get("body")
                    if text:
                        texts.append(str(text))
                elif isinstance(entry, str):
                    texts.append(entry)
            self._log(player_id, "search", True, scope_id=scope_id, request_id=result.get("_request_id"),
                      detail=f"query={query[:80]} hits={len(texts)}")
            return {"success": True, "entries": texts, "error": None}
        except PowerContextError as exc:
            self._log(player_id, "search", False, scope_id=scope_id, detail=str(exc))
            return {"success": False, "entries": [], "error": str(exc)}

    def prepare(self, player_id: str, scope_id: str, query: str, max_bytes: int = 3000) -> dict[str, Any]:
        """准备有界历史上下文。返回 {"success", "status", "content", "error"}。"""
        try:
            result = self._post(
                "/v1/context/prepare",
                {"scope_id": scope_id, "query": query, "max_bytes": max_bytes},
            )
            status = result.get("status", "ready")
            content = result.get("content")
            self._log(player_id, "prepare", True, scope_id=scope_id, request_id=result.get("_request_id"),
                      detail=f"status={status}")
            return {"success": True, "status": status, "content": content, "error": None}
        except PowerContextError as exc:
            self._log(player_id, "prepare", False, scope_id=scope_id, detail=str(exc))
            return {"success": False, "status": "error", "content": None, "error": str(exc)}
