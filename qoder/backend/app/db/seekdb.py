"""seekdb access layer.

Two modes, selected by SEEKDB_MODE:
  embedded - pylibseekdb starts an in-process OceanBase seekdb runtime exposed
             over a Unix socket (Linux/macOS only).
  remote   - connect to a standalone OceanBase/seekdb server over TCP.

All statements use parameterized SQL; callers must never interpolate untrusted
input into query text.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime
from typing import Any

import pymysql
from pymysql.cursors import DictCursor

from app.config import Settings

logger = logging.getLogger(__name__)


class SeekDBError(RuntimeError):
    pass


class SeekDB:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._instance: Any = None
        self._connect_kwargs: dict[str, Any] = {}
        self._version: str = ""

    async def start(self) -> None:
        if self._settings.seekdb_mode == "embedded":
            self._connect_kwargs = await self._open_embedded()
        else:
            self._connect_kwargs = {
                "host": self._settings.seekdb_host,
                "port": self._settings.seekdb_port,
                "user": self._settings.seekdb_user,
                "password": self._settings.seekdb_password,
                "database": self._settings.seekdb_database,
                "charset": "utf8mb4",
            }
        rows = await self.query("SELECT VERSION() AS v")
        self._version = str(rows[0]["v"]) if rows else "unknown"
        logger.info("seekdb connected: mode=%s version=%s", self._settings.seekdb_mode, self._version)

    async def _open_embedded(self) -> dict[str, Any]:
        try:
            import pylibseekdb
        except ImportError as exc:  # pragma: no cover - platform dependent
            raise SeekDBError(
                "pylibseekdb is not installed. Embedded seekdb requires Linux/macOS; "
                "install with `pip install pylibseekdb` or use SEEKDB_MODE=remote."
            ) from exc
        path = self._settings.resolved_seekdb_path()
        path.mkdir(parents=True, exist_ok=True)
        self._instance = await pylibseekdb.aopen(str(path))
        options = self._instance.connection_options()
        kwargs: dict[str, Any] = {"charset": "utf8mb4", "database": self._settings.seekdb_database}
        if "unix_socket" in options:
            kwargs["unix_socket"] = options["unix_socket"]
        else:
            kwargs["host"] = options.get("host", "127.0.0.1")
            kwargs["port"] = int(options.get("port", 2881))
        kwargs["user"] = options.get("user", "root")
        return kwargs

    async def stop(self) -> None:
        if self._instance is not None:
            try:
                self._instance.close()
            except Exception:  # pragma: no cover - best effort shutdown
                logger.exception("failed to close embedded seekdb instance")
            self._instance = None

    @property
    def version(self) -> str:
        return self._version

    @property
    def mode(self) -> str:
        return self._settings.seekdb_mode

    def _connect(self) -> pymysql.connections.Connection:
        try:
            return pymysql.connect(cursorclass=DictCursor, autocommit=True, **self._connect_kwargs)
        except pymysql.MySQLError as exc:
            raise SeekDBError(f"cannot connect to seekdb: {exc}") from exc

    async def query(self, sql: str, params: Sequence[Any] | None = None) -> list[dict[str, Any]]:
        def _run() -> list[dict[str, Any]]:
            conn = self._connect()
            try:
                with conn.cursor() as cursor:
                    cursor.execute(sql, params or ())
                    return list(cursor.fetchall())
            finally:
                conn.close()

        try:
            return await asyncio.to_thread(_run)
        except pymysql.MySQLError as exc:
            raise SeekDBError(f"query failed: {exc}\nSQL: {sql}") from exc

    async def execute(self, sql: str, params: Sequence[Any] | None = None) -> int:
        def _run() -> int:
            conn = self._connect()
            try:
                with conn.cursor() as cursor:
                    return cursor.execute(sql, params or ())
            finally:
                conn.close()

        try:
            return await asyncio.to_thread(_run)
        except pymysql.MySQLError as exc:
            raise SeekDBError(f"execute failed: {exc}\nSQL: {sql}") from exc

    async def execute_batch(self, statements: Iterable[tuple[str, Sequence[Any]]]) -> None:
        """Run several statements inside one transaction."""

        items = list(statements)

        def _run() -> None:
            conn = self._connect()
            try:
                conn.begin()
                with conn.cursor() as cursor:
                    for sql, params in items:
                        cursor.execute(sql, params)
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()

        try:
            await asyncio.to_thread(_run)
        except pymysql.MySQLError as exc:
            raise SeekDBError(f"batch failed: {exc}") from exc

    async def init_schema(self) -> None:
        dim = self._settings.embedding_dimension
        ddl = [
            """CREATE TABLE IF NOT EXISTS lt_projects (
                project_id VARCHAR(64) NOT NULL PRIMARY KEY,
                name VARCHAR(255) NOT NULL,
                description TEXT,
                pc_scope_id VARCHAR(191),
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL
            )""",
            """CREATE TABLE IF NOT EXISTS lt_documents (
                doc_id VARCHAR(64) NOT NULL PRIMARY KEY,
                project_id VARCHAR(64) NOT NULL,
                title VARCHAR(512) NOT NULL,
                topic VARCHAR(255),
                file_name VARCHAR(512),
                file_type VARCHAR(16) NOT NULL,
                page_count INT NOT NULL DEFAULT 0,
                char_count INT NOT NULL DEFAULT 0,
                chunk_count INT NOT NULL DEFAULT 0,
                status VARCHAR(32) NOT NULL DEFAULT 'ready',
                created_at DATETIME NOT NULL,
                INDEX idx_lt_documents_project (project_id),
                INDEX idx_lt_documents_created (created_at)
            )""",
            f"""CREATE TABLE IF NOT EXISTS lt_document_chunks (
                chunk_id VARCHAR(64) NOT NULL PRIMARY KEY,
                doc_id VARCHAR(64) NOT NULL,
                project_id VARCHAR(64) NOT NULL,
                chunk_index INT NOT NULL,
                page_no INT,
                content LONGTEXT NOT NULL,
                searchable_text LONGTEXT NOT NULL,
                embedding VECTOR({dim}) NOT NULL,
                created_at DATETIME NOT NULL,
                INDEX idx_lt_chunks_doc (doc_id),
                INDEX idx_lt_chunks_project (project_id)
            )""",
            """CREATE TABLE IF NOT EXISTS lt_experiments (
                experiment_id VARCHAR(64) NOT NULL PRIMARY KEY,
                project_id VARCHAR(64) NOT NULL,
                name VARCHAR(255) NOT NULL,
                objective TEXT,
                hypothesis TEXT,
                method TEXT,
                model_config TEXT,
                dataset VARCHAR(255),
                result_summary TEXT,
                metrics TEXT,
                issues TEXT,
                failure_reason TEXT,
                next_steps TEXT,
                status VARCHAR(32) NOT NULL DEFAULT 'planned',
                log_markdown LONGTEXT,
                searchable_text LONGTEXT NOT NULL,
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL,
                INDEX idx_lt_experiments_project (project_id),
                INDEX idx_lt_experiments_created (created_at),
                INDEX idx_lt_experiments_dataset (dataset)
            )""",
            """CREATE TABLE IF NOT EXISTS lt_meta (
                meta_key VARCHAR(64) NOT NULL PRIMARY KEY,
                meta_value VARCHAR(255) NOT NULL,
                updated_at DATETIME NOT NULL
            )""",
        ]
        for statement in ddl:
            await self.execute(statement)

        await self._ensure_vector_index()
        await self._ensure_fulltext_indexes()

    async def _ensure_vector_index(self) -> None:
        name = "lt_chunks_vector_idx"
        if await self._index_exists("lt_document_chunks", name):
            return
        try:
            await self.execute(
                f"CREATE VECTOR INDEX {name} ON lt_document_chunks(embedding) WITH (distance=l2, type=hnsw)"
            )
        except SeekDBError as exc:
            logger.warning("index %s not created: %s", name, exc)

    async def _ensure_fulltext_indexes(self) -> None:
        """Create the fulltext indexes with the configured parser, rebuilding on change.

        The parser is fixed at index-creation time and is not reported by
        information_schema, so LabTrace records the active choice in lt_meta and drops and
        recreates both indexes when the configuration differs.
        """
        parser = self._settings.seekdb_fulltext_parser.upper()
        targets = [
            ("lt_chunks_ft_idx", "lt_document_chunks", "searchable_text"),
            ("lt_experiments_ft_idx", "lt_experiments", "searchable_text"),
        ]

        rows = await self.query("SELECT meta_value FROM lt_meta WHERE meta_key = %s", ("fulltext_parser",))
        recorded = str(rows[0]["meta_value"]).upper() if rows else None

        if recorded == parser:
            present = True
            for name, table, _ in targets:
                if not await self._index_exists(table, name):
                    present = False
                    break
            if present:
                return

        # `recorded is None` also covers databases created before the parser was tracked, whose
        # existing indexes were built with the old default and cannot be introspected.
        if recorded != parser:
            logger.info(
                "rebuilding fulltext indexes with parser %s (previously recorded: %s)",
                parser,
                recorded or "unknown",
            )
            for name, table, _ in targets:
                try:
                    await self.execute(f"DROP INDEX {name} ON {table}")
                except SeekDBError:
                    pass

        for name, table, column in targets:
            if await self._index_exists(table, name):
                continue
            try:
                await self.execute(f"CREATE FULLTEXT INDEX {name} ON {table}({column}) WITH PARSER {parser}")
            except SeekDBError as exc:
                logger.warning("index %s not created with parser %s: %s", name, parser, exc)
                return

        now = datetime.now(UTC).replace(tzinfo=None)
        await self.execute(
            "INSERT INTO lt_meta (meta_key, meta_value, updated_at) VALUES (%s,%s,%s) "
            "ON DUPLICATE KEY UPDATE meta_value = VALUES(meta_value), updated_at = VALUES(updated_at)",
            ("fulltext_parser", parser, now),
        )

    async def _index_exists(self, table: str, index_name: str) -> bool:
        rows = await self.query(
            "SELECT COUNT(*) AS n FROM information_schema.statistics "
            "WHERE table_name = %s AND index_name = %s",
            (table, index_name),
        )
        return bool(rows and rows[0]["n"])


_db: SeekDB | None = None


def get_db() -> SeekDB:
    if _db is None:
        raise SeekDBError("seekdb is not initialised")
    return _db


async def init_db(settings: Settings) -> SeekDB:
    global _db
    db = SeekDB(settings)
    await db.start()
    await db.init_schema()
    _db = db
    return db


async def close_db() -> None:
    global _db
    if _db is not None:
        await _db.stop()
        _db = None
