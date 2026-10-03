"""Database dialects live here; application SQL keeps qmark parameters."""
import re
import sqlite3
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

    def __init__(self, url, schema=None):
        import psycopg
        self.driver = psycopg
        options = {}
        if schema:
            if not re.fullmatch(r"[a-z_][a-z0-9_]*", schema):
                raise ValueError("Invalid database schema name")
            options["options"] = f"-c search_path={schema}"
        try:
            self.connection = psycopg.connect(url, autocommit=True, row_factory=row_factory,
                                             prepare_threshold=None, connect_timeout=5, **options)
            self.connection.execute("SET lock_timeout = '5s'")
            self.connection.execute("SET statement_timeout = '30s'")
        except psycopg.Error:
            raise OperationalError("Database connection failed") from None

    def _call(self, function, *args):
        try:
            return function(*args)
        except self.driver.IntegrityError:
            raise IntegrityError("Database constraint conflict") from None
        except self.driver.Error as error:
            if error.sqlstate in ("55P03", "40P01", "40001", "57014"):
                raise OperationalError("Database busy or locked; retry the same request") from None
            raise OperationalError("Database operation failed") from None

    def _lock_writes(self):
        # Database/schema-wide transaction lock deliberately matches SQLite's
        # single-writer behavior, including different visitors and tabs.
        self.connection.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(current_schema() || ':chaek-ex-write', 0))")

    def execute(self, statement, parameters=()):
        sql = postgres_sql(statement) if parameters else statement
        args = tuple(parameters) if parameters else None

        def run():
            # Single-statement writes outside an explicit transaction also
            # participate in the same serialization (identity/admin/CLI).
            if (self.connection.info.transaction_status == self.driver.pq.TransactionStatus.IDLE
                    and re.match(r"\s*(INSERT|UPDATE|DELETE)\b", statement, re.I)):
                with self.connection.transaction():
                    self._lock_writes()
                    return self.connection.execute(sql, args)
            return self.connection.execute(sql, args)
        return self._call(run)

    def begin_write(self):
        def begin():
            self.connection.execute("BEGIN ISOLATION LEVEL READ COMMITTED")
            self._lock_writes()
        try:
            self._call(begin)
        except Exception:
            self.connection.rollback()
            raise

    def begin_read(self):
        self.execute("BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY")

    def initialize_schema(self, text):
        self.begin_write()
        try:
            for statement in text.split(";"):
                if statement.strip():
                    self.execute(statement)
            self.commit()
        except Exception:
            self.rollback()
            raise

    def columns(self, table):
        return [row[0] for row in self.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema=current_schema() AND table_name=? ORDER BY ordinal_position", (table,))]

    def commit(self):
        return self._call(self.connection.commit)

    def rollback(self):
        return self.connection.rollback()

    def close(self):
        self.connection.close()


def connect(config):
    if config.get("DATABASE_URL"):
        return PostgreSQL(config["DATABASE_URL"], config.get("DATABASE_SCHEMA"))
    return SQLite(config["DATABASE"])


def validate_configuration(config):
    url = config.get("DATABASE_URL")
    if url and not url.startswith(("postgresql://", "postgres://")):
        raise RuntimeError("DATABASE_URL must be a PostgreSQL connection URL")
    if not url and (config.get("VERCEL") or not config["LOCAL_DEVELOPMENT"]):
        raise RuntimeError("Production requires DATABASE_URL; SQLite fallback is disabled")