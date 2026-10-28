"""SQLite persistence for deterministic game state.

PowerContext 负责跨会话语义记忆；本模块只保存精确游戏状态（金币/好感度/事件/传闻），
绝不用于替代 PowerContext 的记忆能力。
"""

from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

_SCHEMA = """
CREATE TABLE IF NOT EXISTS players (
    player_id TEXT PRIMARY KEY,
    day INTEGER NOT NULL,
    turn INTEGER NOT NULL,
    coins INTEGER NOT NULL,
    reputation INTEGER NOT NULL,
    location TEXT NOT NULL,
    inventory TEXT NOT NULL DEFAULT '[]',
    relationships TEXT NOT NULL DEFAULT '{}',
    quests TEXT NOT NULL DEFAULT '{}',
    scope_id TEXT,
    scope_generation INTEGER NOT NULL DEFAULT 0,
    game_over INTEGER NOT NULL DEFAULT 0,
    ending TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS events (
    event_id TEXT PRIMARY KEY,
    player_id TEXT NOT NULL,
    day INTEGER NOT NULL,
    turn INTEGER NOT NULL,
    actor TEXT NOT NULL,
    target TEXT,
    action TEXT NOT NULL,
    description TEXT NOT NULL,
    witnesses TEXT NOT NULL DEFAULT '[]',
    truth_status TEXT NOT NULL DEFAULT 'verified',
    importance INTEGER NOT NULL,
    resolved INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_events_player ON events(player_id, day, turn);
CREATE TABLE IF NOT EXISTS rumors (
    rumor_id TEXT PRIMARY KEY,
    player_id TEXT NOT NULL,
    root_event_id TEXT NOT NULL,
    source_event_id TEXT NOT NULL,
    origin TEXT NOT NULL,
    holder TEXT NOT NULL,
    content TEXT NOT NULL,
    truth_status TEXT NOT NULL DEFAULT 'unverified',
    confidence REAL NOT NULL,
    spread_count INTEGER NOT NULL DEFAULT 1,
    day INTEGER NOT NULL,
    turn INTEGER NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(root_event_id, holder)
);
CREATE INDEX IF NOT EXISTS idx_rumors_player ON rumors(player_id, holder);
CREATE TABLE IF NOT EXISTS memory_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id TEXT NOT NULL,
    event_id TEXT,
    operation TEXT NOT NULL,
    scope_id_masked TEXT,
    success INTEGER NOT NULL,
    request_id TEXT,
    detail TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS processed_requests (
    request_key TEXT PRIMARY KEY,
    player_id TEXT NOT NULL,
    response TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


class Database:
    """Thread-safe wrapper around a SQLite file (connection per operation)."""

    def __init__(self, db_path: Path | str):
        self.db_path = Path(db_path)
        self._lock = threading.Lock()
        self._init_schema()

    @property
    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=15)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    @contextmanager
    def tx(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            conn = self._conn
            try:
                yield conn
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()

    @contextmanager
    def query(self) -> Iterator[sqlite3.Connection]:
        conn = self._conn
        try:
            yield conn
        finally:
            conn.close()

    def _init_schema(self) -> None:
        with self.tx() as conn:
            conn.executescript(_SCHEMA)

    # ---- players -------------------------------------------------------

    def get_player(self, player_id: str) -> dict[str, Any] | None:
        with self.query() as conn:
            row = conn.execute("SELECT * FROM players WHERE player_id = ?", (player_id,)).fetchone()
        return dict(row) if row else None

    def upsert_player(self, state: dict[str, Any]) -> None:
        with self.tx() as conn:
            conn.execute(
                """
                INSERT INTO players
                    (player_id, day, turn, coins, reputation, location, inventory,
                     relationships, quests, scope_id, scope_generation, game_over, ending, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
                ON CONFLICT(player_id) DO UPDATE SET
                    day=excluded.day, turn=excluded.turn, coins=excluded.coins,
                    reputation=excluded.reputation, location=excluded.location,
                    inventory=excluded.inventory, relationships=excluded.relationships,
                    quests=excluded.quests, scope_id=excluded.scope_id,
                    scope_generation=excluded.scope_generation,
                    game_over=excluded.game_over, ending=excluded.ending,
                    updated_at=datetime('now')
                """,
                (
                    state["player_id"], state["day"], state["turn"], state["coins"],
                    state["reputation"], state["location"], json.dumps(state["inventory"], ensure_ascii=False),
                    json.dumps(state["relationships"], ensure_ascii=False),
                    json.dumps(state["quests"], ensure_ascii=False),
                    state.get("scope_id"), state.get("scope_generation", 0),
                    int(state.get("game_over", False)), state.get("ending"),
                ),
            )

    def delete_player_state(self, player_id: str) -> None:
        """Reset：清空游戏状态与事件/传闻，保留 memory_log 审计记录。"""
        with self.tx() as conn:
            conn.execute("DELETE FROM events WHERE player_id = ?", (player_id,))
            conn.execute("DELETE FROM rumors WHERE player_id = ?", (player_id,))
            conn.execute("DELETE FROM processed_requests WHERE player_id = ?", (player_id,))
            conn.execute("DELETE FROM players WHERE player_id = ?", (player_id,))

    # ---- events --------------------------------------------------------

    def insert_event(self, event: dict[str, Any]) -> None:
        with self.tx() as conn:
            conn.execute(
                """
                INSERT INTO events
                    (event_id, player_id, day, turn, actor, target, action, description,
                     witnesses, truth_status, importance, resolved)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event["event_id"], event["player_id"], event["day"], event["turn"],
                    event["actor"], event.get("target"), event["action"], event["description"],
                    json.dumps(event.get("witnesses", []), ensure_ascii=False),
                    event.get("truth_status", "verified"), event["importance"],
                    int(bool(event.get("resolved", False))),
                ),
            )

    def list_events(self, player_id: str, limit: int = 100) -> list[dict[str, Any]]:
        with self.query() as conn:
            rows = conn.execute(
                "SELECT * FROM events WHERE player_id = ? ORDER BY turn DESC, event_id DESC LIMIT ?",
                (player_id, limit),
            ).fetchall()
        out = []
        for row in rows:
            item = dict(row)
            item["witnesses"] = json.loads(item["witnesses"])
            item["resolved"] = bool(item["resolved"])
            out.append(item)
        return out

    def find_unresolved_bad_event(self, player_id: str, target: str, bad_actions: list[str]) -> dict[str, Any] | None:
        with self.query() as conn:
            rows = conn.execute(
                """
                SELECT * FROM events
                WHERE player_id = ? AND target = ? AND action IN (%s) AND resolved = 0
                ORDER BY importance DESC, turn DESC LIMIT 1
                """ % ",".join("?" * len(bad_actions)),
                (player_id, target, *bad_actions),
            ).fetchall()
        if not rows:
            return None
        item = dict(rows[0])
        item["witnesses"] = json.loads(item["witnesses"])
        item["resolved"] = bool(item["resolved"])
        return item

    def mark_event_resolved(self, event_id: str) -> None:
        with self.tx() as conn:
            conn.execute("UPDATE events SET resolved = 1 WHERE event_id = ?", (event_id,))

    # ---- rumors --------------------------------------------------------

    def insert_rumor(self, rumor: dict[str, Any]) -> bool:
        """INSERT OR IGNORE：同一 (root_event_id, holder) 只保留一条，防止无限循环传播。"""
        with self.tx() as conn:
            cur = conn.execute(
                """
                INSERT OR IGNORE INTO rumors
                    (rumor_id, player_id, root_event_id, source_event_id, origin, holder,
                     content, truth_status, confidence, spread_count, day, turn)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    rumor["rumor_id"], rumor["player_id"], rumor["root_event_id"],
                    rumor["source_event_id"], rumor["origin"], rumor["holder"],
                    rumor["content"], rumor["truth_status"], rumor["confidence"],
                    rumor["spread_count"], rumor["day"], rumor["turn"],
                ),
            )
            return cur.rowcount > 0

    def upsert_rumor(self, rumor: dict[str, Any]) -> bool:
        """澄清性传闻：同 (root_event_id, holder) 已存在时覆盖旧版本。

        只有 truth_status=verified 的澄清允许覆盖，普通传播仍走 insert_rumor 的去重。
        """
        with self.tx() as conn:
            cur = conn.execute(
                """
                INSERT INTO rumors
                    (rumor_id, player_id, root_event_id, source_event_id, origin, holder,
                     content, truth_status, confidence, spread_count, day, turn)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(root_event_id, holder) DO UPDATE SET
                    rumor_id=excluded.rumor_id, content=excluded.content,
                    truth_status=excluded.truth_status, confidence=excluded.confidence,
                    spread_count=excluded.spread_count, day=excluded.day, turn=excluded.turn
                """,
                (
                    rumor["rumor_id"], rumor["player_id"], rumor["root_event_id"],
                    rumor["source_event_id"], rumor["origin"], rumor["holder"],
                    rumor["content"], rumor["truth_status"], rumor["confidence"],
                    rumor["spread_count"], rumor["day"], rumor["turn"],
                ),
            )
            return cur.rowcount > 0

    def list_rumors(self, player_id: str, holder: str | None = None) -> list[dict[str, Any]]:
        with self.query() as conn:
            if holder is None:
                rows = conn.execute(
                    "SELECT * FROM rumors WHERE player_id = ? ORDER BY turn DESC, rumor_id DESC",
                    (player_id,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM rumors WHERE player_id = ? AND holder = ? ORDER BY turn DESC, rumor_id DESC",
                    (player_id, holder),
                ).fetchall()
        return [dict(row) for row in rows]

    def get_event(self, event_id: str) -> dict[str, Any] | None:
        with self.query() as conn:
            row = conn.execute("SELECT * FROM events WHERE event_id = ?", (event_id,)).fetchone()
        if not row:
            return None
        item = dict(row)
        item["witnesses"] = json.loads(item["witnesses"])
        item["resolved"] = bool(item["resolved"])
        return item

    # ---- memory audit log ----------------------------------------------

    def log_memory(
        self,
        player_id: str,
        operation: str,
        success: bool,
        event_id: str | None = None,
        scope_id_masked: str | None = None,
        request_id: str | None = None,
        detail: str | None = None,
    ) -> None:
        with self.tx() as conn:
            conn.execute(
                """
                INSERT INTO memory_log
                    (player_id, event_id, operation, scope_id_masked, success, request_id, detail)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (player_id, event_id, operation, scope_id_masked, int(success), request_id, detail),
            )

    def list_memory_log(self, player_id: str, limit: int = 50) -> list[dict[str, Any]]:
        with self.query() as conn:
            rows = conn.execute(
                "SELECT * FROM memory_log WHERE player_id = ? ORDER BY id DESC LIMIT ?",
                (player_id, limit),
            ).fetchall()
        out = []
        for row in rows:
            item = dict(row)
            item["success"] = bool(item["success"])
            out.append(item)
        return out

    # ---- request idempotency -------------------------------------------

    def get_processed(self, request_key: str) -> dict[str, Any] | None:
        with self.query() as conn:
            row = conn.execute(
                "SELECT response FROM processed_requests WHERE request_key = ?", (request_key,)
            ).fetchone()
        if not row:
            return None
        return json.loads(row["response"])

    def put_processed(self, request_key: str, player_id: str, response: dict[str, Any]) -> None:
        with self.tx() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO processed_requests (request_key, player_id, response) VALUES (?, ?, ?)",
                (request_key, player_id, json.dumps(response, ensure_ascii=False)),
            )
