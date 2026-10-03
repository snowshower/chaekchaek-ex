"""Database dialects live here; application SQL keeps qmark parameters."""
import re
import sqlite3
import sys
from time import perf_counter
from pathlib import Path

OperationalError = sqlite3.OperationalError
IntegrityError = sqlite3.IntegrityError

# Keep quoted question marks and comments intact. Application SQL has no
# PostgreSQL JSON ? operators or dollar-quoted function bodies.
SQL_TOKEN = re.compile(r"""('(?:''|[^'])*'|"(?:[^"]|"")*"|--[^\n]*|/\*.*?\*/)|\?""", re.S)


def postgres_sql(statement):
    return SQL_TOKEN.sub(lambda match: match[1] if match[1] else "%s", statement.replace("%", "%%"))


class Row(dict):
    """Mapping access plus sqlite3.Row's existing integer access."""
    def __init__(self, names, values):
        super().__init__(zip(names, values))
        self._values = tuple(values)

    def __getitem__(self, key):
        return self._values[key] if isinstance(key, (int, slice)) else super().__getitem__(key)


def row_factory(cursor):
    names = [column.name for column in cursor.description] if cursor.description else []
    return lambda values: Row(names, values)


class SQLite:
    schema_file = "schema.sql"

    def __init__(self, database):
        Path(database).parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(database, timeout=5, isolation_level=None)
        self.connection.row_factory = sqlite3.Row
        self.execute("PRAGMA foreign_keys=ON")
        self.execute("PRAGMA busy_timeout=5000")

    def execute(self, statement, parameters=()):
        return self.connection.execute(statement, parameters)

    def execute_batch(self, statements):
        return [self.execute(sql, parameters) for sql, parameters in statements]

    def __getattr__(self, name):
        return getattr(self.connection, name)

    def begin_write(self):
        self.execute("BEGIN IMMEDIATE")

    def begin_read(self):
        self.execute("BEGIN")

    def initialize_schema(self, text):
        self.connection.executescript(text)
        self.execute("PRAGMA journal_mode=WAL")

    def columns(self, table):
        return [row[1] for row in self.execute(f'PRAGMA table_info("{table}")')]


class PostgreSQL:
    schema_file = "schema_postgres.sql"

    def __init__(self, url, schema=None, diagnostics=False):
        import psycopg
        self.driver = psycopg
        self.diagnostics = diagnostics
        self.schema = schema
        self.timings = {}
        self.write_started = None
        if schema:
            if not re.fullmatch(r"[a-z_][a-z0-9_]*", schema):
                raise ValueError("Invalid database schema name")
        stage = "connect"
        started = perf_counter()
        self.connection = None
        try:
            self.connection = psycopg.connect(url, autocommit=True, row_factory=row_factory,
                                             prepare_threshold=None, connect_timeout=5)
        except psycopg.Error as error:
            if self.connection is not None:
                self.connection.close()
            if diagnostics:
                from .db_diagnostics import safe_error
                message = safe_error(error, stage)
            else:
                message = "Database connection failed" if stage == "connect" else "Database session initialization failed"
            raise OperationalError(message) from None
        if diagnostics:
            self.timings["connect"] = (1, perf_counter() - started)

    def _send(self, statement, parameters=None):
        started = perf_counter()
        try:
            return (self.connection.execute(statement) if parameters is None
                    else self.connection.execute(statement, parameters))
        finally:
            if self.diagnostics:
                count, seconds = self.timings.get("SQL sent", (0, 0.0))
                self.timings["SQL sent"] = (count + 1, seconds + perf_counter() - started)

    def _call(self, function, *args, stage="execute"):
        from .db_diagnostics import safe_error, connection_state
        self.stage = stage
        started = perf_counter()
        try:
            return function(*args)
        except self.driver.Error as error:
            if isinstance(error, self.driver.IntegrityError):
                translated = IntegrityError("Database constraint conflict")
            elif error.sqlstate in ("55P03", "40P01", "40001", "57014"):
                translated = OperationalError("Database busy or locked; retry the same request")
            else:
                translated = OperationalError("Database operation failed")
            if self.diagnostics:
                translated.diagnostic = safe_error(error, self.stage) + "; " + connection_state(self.connection)
                translated.args = (str(translated) + "; " + translated.diagnostic,)
            raise translated from None
        finally:
            if self.diagnostics:
                count, seconds = self.timings.get(stage, (0, 0.0))
                self.timings[stage] = (count + 1, seconds + perf_counter() - started)

    def _configure_transaction(self):
        # PgBouncer transaction pooling can switch server sessions after COMMIT.
        # Never rely on SET executed by an earlier autocommit statement.
        from psycopg import sql
        if self.schema:
            self.stage = "SET LOCAL search_path"
            self._send(sql.SQL("SET LOCAL search_path TO {}").format(sql.Identifier(self.schema)))
        self.stage = "SET LOCAL lock_timeout"
        self._send("SET LOCAL lock_timeout = '5s'")
        self.stage = "SET LOCAL statement_timeout"
        self._send("SET LOCAL statement_timeout = '30s'")

    def _finish_write_hold(self):
        if self.write_started is not None:
            if self.diagnostics:
                count, seconds = self.timings.get("write lock held", (0, 0.0))
                self.timings["write lock held"] = (count + 1, seconds + perf_counter() - self.write_started)
            self.write_started = None

    def execute_batch(self, statements):
        statements = list(statements)
        def batch():
            cursors = []
            with self.connection.pipeline():
                for statement, parameters in statements:
                    cursors.append(self.execute(statement, parameters))
                self.stage = "pipeline sync"
            return cursors
        def run():
            if self.connection.info.transaction_status == self.driver.pq.TransactionStatus.IDLE:
                try:
                    with self.connection.transaction():
                        with self.connection.pipeline():
                            self._configure_transaction()
                        if any(re.match(r"\s*(INSERT|UPDATE|DELETE)\b", sql, re.I) for sql, _ in statements):
                            self._lock_writes()
                        return batch()
                finally:
                    self._finish_write_hold()
            return batch()
        return self._call(run, stage="batch roundtrip")

    def _lock_writes(self):
        # Database/schema-wide transaction lock deliberately matches SQLite's
        # single-writer behavior, including different visitors and tabs.
        self.stage = "advisory lock"
        started = perf_counter()
        try:
            self._send(
                "SELECT pg_advisory_xact_lock(hashtextextended(current_schema() || ':chaek-ex-write', 0))")
            self.write_started = perf_counter()
        finally:
            if self.diagnostics:
                count, seconds = self.timings.get("advisory lock", (0, 0.0))
                self.timings["advisory lock"] = (count + 1, seconds + perf_counter() - started)

    def execute(self, statement, parameters=()):
        sql = postgres_sql(statement) if parameters else statement
        args = tuple(parameters) if parameters else None

        def run():
            if self.connection.info.transaction_status == self.driver.pq.TransactionStatus.IDLE:
                try:
                    with self.connection.transaction():
                        with self.connection.pipeline():
                            self._configure_transaction()
                        if re.match(r"\s*(INSERT|UPDATE|DELETE)\b", statement, re.I):
                            self._lock_writes()
                        self.stage = operation
                        return self._send(sql, args)
                finally:
                    self._finish_write_hold()
            self.stage = operation
            return self._send(sql, args)
        verb = re.match(r"\s*([A-Za-z]+)", statement)
        operation = "execute " + (verb[1].upper() if verb else "statement")
        return self._call(run, stage=operation)

    def begin_write(self):
        def begin():
            with self.connection.pipeline():
                self._send("BEGIN ISOLATION LEVEL READ COMMITTED")
                self._configure_transaction()
            self._lock_writes()
        try:
            self._call(begin, stage="BEGIN write")
        except Exception:
            self.rollback()
            raise

    def begin_read(self):
        def begin():
            with self.connection.pipeline():
                self._send("BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY")
                self._configure_transaction()
        try:
            self._call(begin, stage="BEGIN read")
        except Exception:
            self.rollback()
            raise

    def initialize_schema(self, text):
        self.begin_write()
        try:
            self.execute_batch([(statement, ()) for statement in text.split(";") if statement.strip()])
            self.commit()
        except Exception:
            self.rollback()
            raise

    def columns(self, table):
        return [row[0] for row in self.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema=current_schema() AND table_name=? ORDER BY ordinal_position", (table,))]

    def commit(self):
        result = self._call(self.connection.commit, stage="COMMIT")
        self._finish_write_hold()
        return result

    def rollback(self):
        original = sys.exception()
        try:
            return self._call(self.connection.rollback, stage="ROLLBACK")
        except OperationalError as rollback_error:
            if original is None:
                self.connection.close()
                raise
            # Retain the operation failure; never retry/commit a broken request.
            # The lost connection is discarded, and rollback failure is evidence.
            if self.diagnostics:
                original.add_note(str(rollback_error))
                if hasattr(original, "diagnostic"):
                    original.diagnostic += "; rollback failed: " + getattr(rollback_error, "diagnostic", "unavailable")
            self.connection.close()
        finally:
            self._finish_write_hold()

    def close(self):
        self._call(self.connection.close, stage="close")
        self._finish_write_hold()
        observer = getattr(self, "diagnostic_observer", None)
        if self.diagnostics and observer:
            observer(self.timings)


def connect(config):
    if config.get("DATABASE_URL"):
        db = PostgreSQL(config["DATABASE_URL"], config.get("DATABASE_SCHEMA"),
                        diagnostics=bool(config.get("TESTING") or config.get("LOCAL_DEVELOPMENT")))
        db.diagnostic_observer = config.get("DATABASE_DIAGNOSTIC_OBSERVER")
        return db
    return SQLite(config["DATABASE"])


def validate_configuration(config):
    url = config.get("DATABASE_URL")
    if url and not url.startswith(("postgresql://", "postgres://")):
        raise RuntimeError("DATABASE_URL must be a PostgreSQL connection URL")
    if not url and (config.get("VERCEL") or not config["LOCAL_DEVELOPMENT"]):
        raise RuntimeError("Production requires DATABASE_URL; SQLite fallback is disabled")
