"""Minimal A-E reproduction using only TEST_DATABASE_URL; no credentials printed.

Startup search_path rejection is an expected diagnostic result on the confirmed
Neon pooled endpoint. These probes deliberately retain that rejected option;
the application adapter instead sets search_path after connecting.
"""
import os
import sys
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict
from app.db_backend import row_factory
from app.db_diagnostics import safe_error


def main():
    url = os.getenv("TEST_DATABASE_URL", "").strip()
    if not url:
        print("TEST_DATABASE_URL is not set; no connections attempted")
        return 2
    if url == os.getenv("DATABASE_URL", "").strip():
        print("Refusing: dedicated TEST_DATABASE_URL must differ from DATABASE_URL")
        return 2
    try:
        parameters = conninfo_to_dict(url)
    except psycopg.Error as error:
        print(safe_error(error, "parse"))
        return 1
    print("Pooled endpoint marker present:", "-pooler" in parameters.get("host", ""))
    schema = "chaek_test_" + uuid4().hex
    connections = []
    created = False
    control = None

    def attempt(stage, operation):
        try:
            result = operation()
            print(stage + ": PASS")
            return result
        except psycopg.Error as error:
            print(safe_error(error, stage))
            return None

    def connect(**kwargs):
        connection = psycopg.connect(url, connect_timeout=10, **kwargs)
        connections.append(connection)
        return connection

    try:
        control = attempt("A basic connection", lambda: connect(autocommit=True))
        attempt("B startup search_path before CREATE", lambda: connect(autocommit=True, options=f"-c search_path={schema}"))
        if control is None:
            return 1
        privilege = attempt("CREATE privilege", lambda: control.execute(
            "SELECT has_database_privilege(current_database(), 'CREATE')").fetchone())
        print("CREATE privilege granted:", bool(privilege and privilege[0]))
        cursor = attempt("C CREATE SCHEMA", lambda: control.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema))))
        created = cursor is not None
        if not created:
            return 1
        attempt("C startup search_path after CREATE", lambda: connect(autocommit=True, options=f"-c search_path={schema}"))
        connection = attempt("D basic session", lambda: connect(autocommit=True))
        if connection is not None:
            attempt("D SET search_path", lambda: connection.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(schema))))
            current = attempt("D effective schema read", lambda: connection.execute("SELECT current_schema()").fetchone())
            print("D effective schema matches:", bool(current and current[0] == schema))
            attempt("E SET lock_timeout", lambda: connection.execute("SET lock_timeout = '5s'"))
            attempt("E SET statement_timeout", lambda: connection.execute("SET statement_timeout = '30s'"))
        variants = {"row_factory": {"row_factory": row_factory}, "prepare_threshold": {"prepare_threshold": None},
                    "autocommit": {"autocommit": True},
                    "all adapter options": {"autocommit": True, "row_factory": row_factory, "prepare_threshold": None}}
        for name, options in variants.items():
            attempt("option " + name, lambda options=options: connect(**options))
        attempt("adapter timeout 5s", lambda: psycopg.connect(url, connect_timeout=5).close())
        return 0
    finally:
        for connection in connections:
            if connection is not control:
                connection.close()
        if created and control is not None:
            attempt("cleanup test schema", lambda: control.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema))))
        if control is not None:
            control.close()


if __name__ == "__main__":
    sys.exit(main())
