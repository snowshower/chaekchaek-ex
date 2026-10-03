from app.db_diagnostics import safe_error
import pytest
from contextlib import nullcontext

from app.db_backend import PostgreSQL, OperationalError


def test_diagnostics_explain_startup_failure_without_credentials():
    class DriverFailure(Exception):
        sqlstate = "08P01"

    error = DriverFailure('connection to server at "secret-host", user=secret-user password=secret-password failed: '
                          'unsupported startup parameter in options: search_path')
    message = safe_error(error, "connect")
    assert "DriverFailure" in message
    assert "08P01" in message
    assert "unsupported startup parameter: search_path" in message
    assert "secret" not in message


def test_unknown_error_details_are_suppressed():
    message = safe_error(RuntimeError("postgresql://username:password@hostname/database"), "connect")
    assert message == "connect: RuntimeError; SQLSTATE=unavailable; driver error; raw connection details suppressed"


@pytest.mark.parametrize("stage", ["connect", "SET LOCAL search_path", "SET LOCAL lock_timeout", "SET LOCAL statement_timeout"])
def test_adapter_diagnostics_identify_failure_stage(monkeypatch, stage):
    import psycopg

    class Connection:
        closed = False

        def pipeline(self):
            return nullcontext()

        def rollback(self):
            pass

        def execute(self, statement):
            text = statement.as_string() if isinstance(statement, psycopg.sql.Composable) else statement
            if text.startswith(stage):
                raise psycopg.OperationalError("private-host private-user private-password")

        def close(self):
            self.closed = True

    connection = Connection()

    def connect(*args, **kwargs):
        if stage == "connect":
            raise psycopg.OperationalError("private-host private-user private-password")
        return connection

    monkeypatch.setattr(psycopg, "connect", connect)
    with pytest.raises(OperationalError) as failure:
        db = PostgreSQL("postgresql://private-user:private-password@private-host/database", schema="chaek_test_example", diagnostics=True)
        from types import SimpleNamespace
        connection.info = SimpleNamespace(status=psycopg.pq.ConnStatus.OK, transaction_status=psycopg.pq.TransactionStatus.INTRANS)
        db.begin_write()
    assert stage + ": OperationalError;" in str(failure.value)
    assert "private" not in str(failure.value)
    assert not connection.closed


@pytest.mark.parametrize("schema", ["chaek_test_example", None])
def test_schema_is_configured_after_connect_without_startup_options(monkeypatch, schema):
    import psycopg

    calls = []

    class Connection:
        def pipeline(self):
            return nullcontext()

        def execute(self, statement):
            calls.append(statement)

    def connect(*args, **kwargs):
        assert "options" not in kwargs
        assert kwargs["autocommit"] is True
        assert kwargs["prepare_threshold"] is None
        calls.append("connect")
        return Connection()

    monkeypatch.setattr(psycopg, "connect", connect)
    db = PostgreSQL("postgresql://example.invalid/database", schema=schema)
    db.begin_write()
    assert calls[0] == "connect"
    if schema:
        assert isinstance(calls[2], psycopg.sql.Composed)
        assert calls[2].as_string() == 'SET LOCAL search_path TO "chaek_test_example"'
    assert calls[1] == "BEGIN ISOLATION LEVEL READ COMMITTED"
    assert calls[-3:-1] == ["SET LOCAL lock_timeout = '5s'", "SET LOCAL statement_timeout = '30s'"]
    assert "pg_advisory_xact_lock" in calls[-1]
    assert len(calls) == (6 if schema else 5)


def test_invalid_schema_is_rejected_before_connection(monkeypatch):
    import psycopg

    def connect(*args, **kwargs):
        pytest.fail("Invalid schema must not create a connection")

    monkeypatch.setattr(psycopg, "connect", connect)
    with pytest.raises(ValueError, match="Invalid database schema name"):
        PostgreSQL("postgresql://example.invalid/database", schema='public; DROP SCHEMA public')
