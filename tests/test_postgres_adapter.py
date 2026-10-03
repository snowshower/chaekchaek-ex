from contextlib import contextmanager, nullcontext
from types import SimpleNamespace

import psycopg
import pytest

from app.db_backend import PostgreSQL, OperationalError


class PooledConnection:
    """Simulate a different server session after every transaction."""
    def __init__(self):
        self.closed = False
        self.info = SimpleNamespace(status=psycopg.pq.ConnStatus.OK,
                                    transaction_status=psycopg.pq.TransactionStatus.IDLE)
        self.schema = None
        self.calls = []

    def execute(self, statement, args=None):
        text = statement.as_string() if isinstance(statement, psycopg.sql.Composable) else statement
        self.calls.append(text)
        if text.startswith("BEGIN"):
            self.info.transaction_status = psycopg.pq.TransactionStatus.INTRANS
            self.schema = None
        elif text.startswith("SET LOCAL"):
            assert self.info.transaction_status == psycopg.pq.TransactionStatus.INTRANS
            if "search_path" in text:
                self.schema = "chaek_test_pool"
        else:
            assert self.schema == "chaek_test_pool", "Query must not inherit a previous pooled session"
        return SimpleNamespace(fetchone=lambda schema=self.schema: (schema,))

    def commit(self):
        self.info.transaction_status = psycopg.pq.TransactionStatus.IDLE
        self.schema = None

    def rollback(self):
        self.commit()

    def close(self):
        self.closed = True

    def pipeline(self):
        return nullcontext()

    @contextmanager
    def transaction(self):
        self.execute("BEGIN")
        try:
            yield
            self.commit()
        except Exception:
            self.rollback()
            raise


def adapter(monkeypatch, connection):
    monkeypatch.setattr(psycopg, "connect", lambda *args, **kwargs: connection)
    return PostgreSQL("postgresql://example.invalid/db", schema="chaek_test_pool", diagnostics=True)


def test_transaction_pool_schema_and_timeouts_apply_to_each_operation(monkeypatch):
    connection = PooledConnection()
    db = adapter(monkeypatch, connection)
    for _ in range(2):
        assert db.execute("SELECT current_schema()").fetchone() == ("chaek_test_pool",)
    db.execute("INSERT INTO visitors VALUES (?)", ("value",))
    db.begin_write()
    db.execute("SELECT current_schema()")
    db.commit()
    db.begin_read()
    db.execute("SELECT current_schema()")
    db.rollback()
    assert connection.calls.count('SET LOCAL search_path TO "chaek_test_pool"') == 5
    assert connection.calls.count("SET LOCAL lock_timeout = '5s'") == 5
    assert connection.calls.count("SET LOCAL statement_timeout = '30s'") == 5
    assert sum("pg_advisory_xact_lock" in statement for statement in connection.calls) == 2


def test_lost_connection_rollback_preserves_original_failure(monkeypatch):
    connection = PooledConnection()
    db = adapter(monkeypatch, connection)

    def lost():
        connection.info.status = psycopg.pq.ConnStatus.BAD
        raise psycopg.OperationalError("the connection is lost private-host private-user private-password")

    connection.rollback = lost
    original = OperationalError("original INSERT failure")
    with pytest.raises(OperationalError) as failure:
        try:
            raise original
        except OperationalError:
            db.rollback()
            raise
    assert failure.value is original
    assert connection.closed
    assert "ROLLBACK" in original.__notes__[0]
    assert "status=BAD" in original.__notes__[0]
    assert "private" not in original.__notes__[0]


def test_rollback_failure_without_original_is_not_suppressed(monkeypatch):
    connection = PooledConnection()
    db = adapter(monkeypatch, connection)
    connection.rollback = lambda: (_ for _ in ()).throw(psycopg.OperationalError("the connection is lost"))
    with pytest.raises(OperationalError, match="ROLLBACK"):
        db.rollback()
    assert connection.closed


def test_lock_timeout_rolls_back_inerror_before_any_reuse(monkeypatch):
    connection = PooledConnection()
    db = adapter(monkeypatch, connection)
    execute = connection.execute

    def timeout(statement, args=None):
        if isinstance(statement, str) and "pg_advisory_xact_lock" in statement:
            connection.info.transaction_status = psycopg.pq.TransactionStatus.INERROR
            raise psycopg.errors.LockNotAvailable("canceling statement due to lock timeout")
        return execute(statement, args)

    connection.execute = timeout
    with pytest.raises(OperationalError, match="55P03") as failure:
        db.begin_write()
    assert "transaction=INERROR" in failure.value.diagnostic
    assert connection.info.transaction_status == psycopg.pq.TransactionStatus.IDLE
    db.begin_read()
    db.rollback()
    db.close()
    assert connection.closed
