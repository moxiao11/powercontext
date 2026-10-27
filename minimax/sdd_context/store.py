from __future__ import annotations

import json
import os
import re
from pathlib import Path

import pymysql
from pymysql.cursors import DictCursor

from .common import append_event, canonical, digest


class EngineeringStore:
    """Real MySQL-wire queries; deliberately has no local-file fallback."""

    def __init__(self, audit: Path | None = None):
        self.audit = audit
        self.database = os.getenv("SDD_DB_NAME", "sdd_context")
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,63}", self.database):
            raise ValueError("Invalid SDD_DB_NAME")
        self.config = dict(host=os.getenv("SDD_DB_HOST", "127.0.0.1"),
                           port=int(os.getenv("SDD_DB_PORT", "12890")),
                           user=os.getenv("SDD_DB_USER", "root"),
                           password=os.getenv("SDD_DB_PASSWORD", ""),
                           charset="utf8mb4", cursorclass=DictCursor,
                           connect_timeout=10, read_timeout=30, write_timeout=30)

    def connect(self):
        return pymysql.connect(**self.config, database=self.database)

    def initialize(self):
        with pymysql.connect(**self.config, autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute(f"CREATE DATABASE IF NOT EXISTS `{self.database}` CHARACTER SET utf8mb4")
        with self.connect() as conn:
            with conn.cursor() as cur:
                cur.execute("""CREATE TABLE IF NOT EXISTS sdd_projects (
                    project_id VARCHAR(128) PRIMARY KEY, snapshot_sha256 CHAR(64) NOT NULL)""")
                cur.execute("""CREATE TABLE IF NOT EXISTS sdd_documents (
                    project_id VARCHAR(128) NOT NULL, doc_id VARCHAR(255) NOT NULL,
                    revision INT NOT NULL, kind VARCHAR(16) NOT NULL,
                    source_path VARCHAR(512) NOT NULL, symbol TEXT NOT NULL,
                    content LONGTEXT NOT NULL, payload LONGTEXT NOT NULL,
                    tags_json TEXT NOT NULL, sha256 CHAR(64) NOT NULL,
                    active TINYINT NOT NULL,
                    PRIMARY KEY (project_id, doc_id, revision))""")
            conn.commit()

    def import_documents(self, project_id: str, documents: list[dict]) -> dict:
        snapshot = digest(documents)
        changed = []
        with self.connect() as conn:
            with conn.cursor() as cur:
                cur.execute("INSERT IGNORE INTO sdd_projects VALUES (%s, %s)", (project_id, ""))
                cur.execute("SELECT snapshot_sha256 FROM sdd_projects WHERE project_id=%s FOR UPDATE", (project_id,))
                previous = cur.fetchone()["snapshot_sha256"]
                cur.execute("SELECT doc_id, revision, sha256 FROM sdd_documents WHERE project_id=%s ORDER BY revision", (project_id,))
                heads = {row["doc_id"]: row for row in cur.fetchall()}
                cur.execute("UPDATE sdd_documents SET active=0 WHERE project_id=%s", (project_id,))
                for doc in documents:
                    head = heads.get(doc["doc_id"])
                    if head and head["sha256"] == doc["sha256"]:
                        revision = head["revision"]
                        cur.execute("UPDATE sdd_documents SET active=%s WHERE project_id=%s AND doc_id=%s AND revision=%s",
                                    (int(doc["active"]), project_id, doc["doc_id"], revision))
                    else:
                        revision = head["revision"] + 1 if head else 1
                        cur.execute("INSERT INTO sdd_documents VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                                    (project_id, doc["doc_id"], revision, doc["kind"], doc["source_path"],
                                     doc["symbol"], doc["content"], canonical(doc), canonical(doc["tags"]),
                                     doc["sha256"], int(doc["active"])))
                        changed.append({"doc_id": doc["doc_id"], "revision": revision})
                cur.execute("UPDATE sdd_projects SET snapshot_sha256=%s WHERE project_id=%s", (snapshot, project_id))
            conn.commit()
        result = {"project_id": project_id, "snapshot_sha256": snapshot, "changed": changed,
                  "document_count": len(documents), "unchanged": previous == snapshot}
        append_event(self.audit, {"operation": "import", **result})
        return result

    @staticmethod
    def decode(row):
        return {**json.loads(row["payload"]), "revision": row["revision"]}

    def _select(self, sql: str, params: list | tuple) -> list[dict]:
        with self.connect() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                rows = cur.fetchall()
        append_event(self.audit, {"operation": "select", "sql": sql, "parameters": params,
                                  "results": [{"doc_id": r["doc_id"], "revision": r["revision"], "sha256": r["sha256"]} for r in rows]})
        return [self.decode(row) for row in rows]

    def search(self, project_id: str, query: str) -> list[dict]:
        tokens = list(dict.fromkeys(re.findall(r"[a-zA-Z][a-zA-Z0-9_]*|[\u4e00-\u9fff]{2,}", query.lower())))[:16]
        if not tokens:
            return []
        conditions, params = [], [project_id]
        for token in tokens:
            # Literal wildcards are escaped so task text cannot broaden a LIKE query.
            literal = token.replace("\\", "\\\\").replace("_", "\\_").replace("%", "\\%")
            conditions.append("(LOWER(tags_json) LIKE %s OR LOWER(content) LIKE %s OR LOWER(symbol) LIKE %s)")
            params.extend(["%" + literal + "%"] * 3)
        sql = "SELECT * FROM sdd_documents WHERE project_id=%s AND active=1 AND (" + " OR ".join(conditions) + ") ORDER BY doc_id"
        return self._select(sql, params)

    def by_ids(self, project_id: str, ids: list[str]) -> list[dict]:
        if not ids:
            return []
        sql = "SELECT * FROM sdd_documents WHERE project_id=%s AND active=1 AND doc_id IN (" + ",".join(["%s"] * len(ids)) + ") ORDER BY doc_id"
        return self._select(sql, [project_id, *ids])

    def history(self, project_id: str) -> list[dict]:
        return self._select("SELECT * FROM sdd_documents WHERE project_id=%s ORDER BY doc_id,revision", [project_id])
