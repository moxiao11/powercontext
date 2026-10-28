#!/usr/bin/env python3
"""Initialise a *remote* OceanBase seekdb instance with the LabTrace schema.

Embedded mode (SEEKDB_MODE=embedded) does not need this script: the backend creates the
tables, the vector index and both FULLTEXT indexes on startup. Use it when you point
LabTrace at a standalone seekdb/OceanBase server and want to create the schema yourself
(for example to review the DDL first, or to provision a shared instance).

    python scripts/init-db.py --dry-run          # print the statements, change nothing
    python scripts/init-db.py                    # apply db/schema.sql
    python scripts/init-db.py --dimension 1024 --parser ngram

Connection defaults come from SEEKDB_HOST / SEEKDB_PORT / SEEKDB_USER / SEEKDB_PASSWORD /
SEEKDB_DATABASE in the environment or in qoder/.env.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

QODER_DIR = Path(__file__).resolve().parent.parent
SCHEMA_FILE = QODER_DIR / "db" / "schema.sql"
ALLOWED_PARSERS = {"ik", "ngram", "space", "beng"}
# MySQL/OceanBase error codes that mean "already provisioned" rather than "failed".
ALREADY_EXISTS_ERRORS = {1007, 1050, 1061}


def load_env_file() -> None:
    env_file = QODER_DIR / ".env"
    if not env_file.is_file():
        return
    for raw in env_file.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


def split_statements(sql: str) -> list[str]:
    """Split schema.sql into statements, dropping `--` comments and blank lines."""
    lines = [line for line in sql.splitlines() if not line.strip().startswith("--")]
    statements = []
    for part in "\n".join(lines).split(";"):
        statement = part.strip()
        if statement:
            statements.append(statement)
    return statements


def apply_options(
    statements: list[str], dimension: int, parser: str, database: str
) -> list[str]:
    """Bind the schema to the configured embedding dimension, parser and database name."""
    result = []
    for statement in statements:
        if re.match(r"(?i)^USE\s", statement):
            continue
        statement = statement.replace(
            "CREATE DATABASE IF NOT EXISTS labtrace",
            f"CREATE DATABASE IF NOT EXISTS {database}",
        )
        statement = re.sub(r"VECTOR\(\d+\)", f"VECTOR({dimension})", statement)
        statement = re.sub(r"(?i)WITH PARSER \w+", f"WITH PARSER {parser}", statement)
        statement = re.sub(
            r"'fulltext_parser', '\w+'",
            f"'fulltext_parser', '{parser.upper()}'",
            statement,
        )
        result.append(statement)
    return result


def index_exists(cursor, database: str, table: str, index_name: str) -> bool:
    """Vector and FULLTEXT indexes have no IF NOT EXISTS, so they are checked before creation.

    Re-creating a vector index on a column that already has one is rejected by seekdb with
    error 1235 rather than a duplicate-name error, so the check has to happen up front.
    """
    cursor.execute(
        "SELECT COUNT(*) FROM information_schema.statistics "
        "WHERE table_schema = %s AND table_name = %s AND index_name = %s",
        (database, table, index_name),
    )
    return bool(cursor.fetchone()[0])


def main() -> int:
    load_env_file()
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--host", default=os.environ.get("SEEKDB_HOST", "127.0.0.1"))
    parser.add_argument(
        "--port", type=int, default=int(os.environ.get("SEEKDB_PORT", "2881"))
    )
    parser.add_argument("--user", default=os.environ.get("SEEKDB_USER", "root@test"))
    parser.add_argument("--password", default=os.environ.get("SEEKDB_PASSWORD", ""))
    parser.add_argument(
        "--database", default=os.environ.get("SEEKDB_DATABASE", "labtrace")
    )
    parser.add_argument(
        "--dimension",
        type=int,
        default=int(os.environ.get("EMBEDDING_DIMENSION", "384")),
    )
    parser.add_argument(
        "--parser",
        default=os.environ.get("SEEKDB_FULLTEXT_PARSER", "ik"),
        choices=sorted(ALLOWED_PARSERS),
        help="FULLTEXT parser; `space` and `beng` cannot tokenize Chinese",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="print the statements without connecting"
    )
    args = parser.parse_args()

    if not SCHEMA_FILE.is_file():
        print(f"schema file not found: {SCHEMA_FILE}", file=sys.stderr)
        return 1

    statements = apply_options(
        split_statements(SCHEMA_FILE.read_text(encoding="utf-8")),
        args.dimension,
        args.parser,
        args.database,
    )

    if args.dry_run:
        for statement in statements:
            print(statement + ";\n")
        print(
            f"-- {len(statements)} statements, dimension={args.dimension}, parser={args.parser}"
        )
        return 0

    try:
        import pymysql
    except ImportError:
        print(
            "pymysql is not installed; run this inside the backend virtualenv",
            file=sys.stderr,
        )
        return 1

    print(f"connecting to seekdb at {args.host}:{args.port} as {args.user}")
    connection = pymysql.connect(
        host=args.host,
        port=args.port,
        user=args.user,
        password=args.password,
        charset="utf8mb4",
        autocommit=True,
    )
    try:
        with connection.cursor() as cursor:
            for statement in statements:
                head = " ".join(statement.split())[:90]
                index = re.match(
                    r"(?i)^CREATE (?:VECTOR |FULLTEXT )?INDEX (\S+) ON (\w+)", statement
                )
                if index and index_exists(
                    cursor, args.database, index.group(2), index.group(1)
                ):
                    print(f"exists: {head}")
                    continue
                try:
                    cursor.execute(statement)
                except pymysql.MySQLError as exc:
                    # 1007 database exists, 1050 table exists, 1061 index name exists: the schema
                    # is idempotent so re-running against an initialised instance is a no-op.
                    if exc.args and exc.args[0] in ALREADY_EXISTS_ERRORS:
                        print(f"exists: {head}")
                        continue
                    print(f"FAILED: {head}\n  {exc}", file=sys.stderr)
                    return 1
                print(f"ok: {head}")
                # The schema opens with CREATE DATABASE and USE; USE is dropped above, so the
                # connection has to select the database itself before the tables are created.
                if re.match(r"(?i)^CREATE DATABASE", statement):
                    connection.select_db(args.database)
                    print(f"selected database {args.database}")
            cursor.execute("SELECT VERSION()")
            version = cursor.fetchone()[0]
            connection.select_db(args.database)
            cursor.execute("SHOW TABLES")
            tables = sorted(str(row[0]) for row in cursor.fetchall())
    finally:
        connection.close()

    print(f"\nseekdb version: {version}")
    print(f"database {args.database} tables: {', '.join(tables) or '(none)'}")
    print(f"vector dimension {args.dimension}, FULLTEXT parser {args.parser}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
