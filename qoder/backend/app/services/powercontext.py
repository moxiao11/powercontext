"""PowerContext HTTP client: scopes, sources, memory, prepared context and handoff.

Endpoints follow openapi/powercontext.yaml of PowerContext v1.2.0. Memory entries
are addressed by an exact citation (memory_ref + entry_id + entry_version_id) that
every mutation response returns; revisions and retirements must pass it back.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.config import Settings

logger = logging.getLogger(__name__)


class PowerContextError(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None, detail: Any = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.detail = detail


class PowerContextClient:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client = httpx.AsyncClient(
            base_url=settings.powercontext_url,
            timeout=30.0,
            headers={"Authorization": f"Bearer {settings.powercontext_token}"}
            if settings.powercontext_token
            else {},
        )

    @property
    def base_url(self) -> str:
        return self._settings.powercontext_url

    async def close(self) -> None:
        await self._client.aclose()

    async def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            response = await self._client.post(path, json=payload)
        except httpx.HTTPError as exc:
            raise PowerContextError(
                f"cannot reach PowerContext at {self._settings.powercontext_url}: {exc}"
            ) from exc
        if response.status_code >= 400:
            raise PowerContextError(
                f"PowerContext {path} returned HTTP {response.status_code}",
                status_code=response.status_code,
                detail=response.text[:800],
            )
        return response.json()

    async def _get(self, path: str) -> dict[str, Any]:
        try:
            response = await self._client.get(path)
        except httpx.HTTPError as exc:
            raise PowerContextError(
                f"cannot reach PowerContext at {self._settings.powercontext_url}: {exc}"
            ) from exc
        if response.status_code >= 400:
            raise PowerContextError(
                f"PowerContext {path} returned HTTP {response.status_code}",
                status_code=response.status_code,
                detail=response.text[:400],
            )
        return response.json()

    # --- health -----------------------------------------------------------
    async def status(self) -> dict[str, Any]:
        info: dict[str, Any] = {"url": self.base_url, "reachable": False, "ready": False}
        try:
            live = await self._client.get("/health/live")
            info["reachable"] = live.status_code < 400
            ready = await self._client.get("/health/ready")
            info["ready"] = ready.status_code == 200
            info["ready_status"] = ready.status_code
            if ready.status_code < 400:
                info["checks"] = ready.json()
        except httpx.HTTPError as exc:
            info["error"] = str(exc)
        try:
            info["capabilities"] = await self._get("/v1/capabilities")
        except PowerContextError as exc:
            info["capabilities_error"] = str(exc)
        return info

    # --- scopes -----------------------------------------------------------
    async def create_scope(self, *, title: str, summary: str, idempotency_key: str) -> dict[str, Any]:
        return await self._post(
            "/v1/scopes",
            {"title": title, "summary": summary, "idempotency_key": idempotency_key},
        )

    async def get_scope(self, scope_id: str) -> dict[str, Any]:
        return await self._get(f"/v1/scopes/{scope_id}")

    # --- sources ----------------------------------------------------------
    async def capture_source(
        self, *, scope_id: str, source_id: str, content: str, metadata: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"scope_id": scope_id, "source_id": source_id, "content": content}
        if metadata:
            payload["metadata"] = metadata
        return await self._post("/v1/sources/content", payload)

    # --- memory -----------------------------------------------------------
    async def remember(
        self, *, scope_id: str, kind: str, text: str, reason: str | None = None
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"scope_id": scope_id, "kind": kind, "text": text}
        if reason:
            payload["reason"] = reason
        return await self._post("/v1/memory/remember", payload)

    async def search_memory(self, *, scope_id: str, query: str, limit: int = 10) -> dict[str, Any]:
        return await self._post(
            "/v1/memory/search", {"scope_id": scope_id, "query": query, "limit": max(1, min(limit, 50))}
        )

    async def list_entries(self, *, scope_id: str, include_inactive: bool = False) -> dict[str, Any]:
        return await self._post(
            "/v1/memory/entries/list",
            {"scope_id": scope_id, "include_inactive": include_inactive},
        )

    async def get_entry(self, *, scope_id: str, citation: dict[str, Any]) -> dict[str, Any]:
        return await self._post("/v1/memory/entries/get", {"scope_id": scope_id, "citation": citation})

    async def revise_entry(
        self,
        *,
        scope_id: str,
        citation: dict[str, Any],
        kind: str,
        text: str,
        reason: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"scope_id": scope_id, "citation": citation, "kind": kind, "text": text}
        if reason:
            payload["reason"] = reason
        return await self._post("/v1/memory/entries/revise", payload)

    async def retire_entry(
        self, *, scope_id: str, citation: dict[str, Any], reason: str | None = None
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"scope_id": scope_id, "citation": citation}
        if reason:
            payload["reason"] = reason
        return await self._post("/v1/memory/entries/retire", payload)

    # --- prepared context -------------------------------------------------
    async def prepare_context(self, *, scope_id: str, query: str, max_bytes: int = 8000) -> dict[str, Any]:
        return await self._post(
            "/v1/context/prepare",
            {"scope_id": scope_id, "query": query, "max_bytes": max(512, min(max_bytes, 32768))},
        )

    # --- handoff ----------------------------------------------------------
    async def finalize_handoff(self, *, scope_id: str, draft: dict[str, Any]) -> dict[str, Any]:
        return await self._post("/v1/handoff/finalize", {"scope_id": scope_id, "draft": draft})

    async def commit_handoff(self, *, scope_id: str, prepared: dict[str, Any]) -> dict[str, Any]:
        return await self._post("/v1/handoff/commit", {"scope_id": scope_id, "handoff": prepared})

    async def continue_handoff(self, *, scope_id: str, selection: str = "latest") -> dict[str, Any]:
        return await self._post("/v1/handoff/continue", {"scope_id": scope_id, "selection": selection})

    async def handoff_report(self, *, selection: dict[str, Any], fmt: str = "json") -> dict[str, Any]:
        return await self._post("/v1/handoff-reports/get", {"selection": selection, "format": fmt})


def source_citation(source_ref: dict[str, Any]) -> dict[str, Any]:
    """Build a HandoffCitation of kind 'source' from a captured SourceReference."""
    return {
        "kind": "source",
        "source_ref": {"name": source_ref["name"], "source_id": source_ref["source_id"]},
    }


def statement(text: str, citations: list[dict[str, Any]]) -> dict[str, Any]:
    return {"text": text, "citations": citations}


_client: PowerContextClient | None = None


def get_powercontext() -> PowerContextClient:
    if _client is None:
        raise PowerContextError("PowerContext client is not initialised")
    return _client


async def init_powercontext(settings: Settings) -> PowerContextClient:
    global _client
    _client = PowerContextClient(settings)
    return _client


async def close_powercontext() -> None:
    global _client
    if _client is not None:
        await _client.close()
        _client = None
