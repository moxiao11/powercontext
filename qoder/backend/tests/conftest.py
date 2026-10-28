"""Shared fixtures.

Unit tests never touch seekdb or PowerContext. The live end-to-end suite in
`test_live_api.py` is skipped unless LABTRACE_LIVE=1 points at a running backend.
"""

from __future__ import annotations

import os
from typing import Any

import pytest

from app.config import Settings


@pytest.fixture
def settings() -> Settings:
    return Settings(_env_file=None, seekdb_path="/tmp/labtrace-pytest", embedding_dimension=16)


class FakeDB:
    """Records the parameterized statements a service would send to seekdb."""

    def __init__(self, rows: list[dict[str, Any]] | None = None) -> None:
        self.rows = rows or []
        self.statements: list[tuple[str, tuple[Any, ...]]] = []

    async def query(self, sql: str, params: Any = None) -> list[dict[str, Any]]:
        self.statements.append((sql, tuple(params or ())))
        return list(self.rows)

    async def execute(self, sql: str, params: Any = None) -> int:
        self.statements.append((sql, tuple(params or ())))
        return 1

    async def execute_batch(self, statements: Any) -> None:
        self.statements.extend((sql, tuple(params or ())) for sql, params in statements)


@pytest.fixture
def fake_db() -> FakeDB:
    return FakeDB()


def live_enabled() -> bool:
    return os.environ.get("LABTRACE_LIVE", "").strip().lower() in {"1", "true", "yes"}


def live_base_url() -> str:
    return os.environ.get("LABTRACE_API_URL", "http://127.0.0.1:8100").rstrip("/")
