"""Opt-in test profiling; labels contain no SQL values or connection details."""
import re
from time import perf_counter


class ProfiledDB:
    def __init__(self, db, observe):
        self.db, self.observe = db, observe

    def execute(self, statement, parameters=()):
        verb = re.match(r"\s*([A-Za-z]+)", statement)
        label = "sql." + (verb[1].upper() if verb else "statement")
        started = perf_counter()
        try:
            return self.db.execute(statement, parameters)
        finally:
            self.observe(label, perf_counter() - started, 1)

    def execute_batch(self, statements):
        statements = list(statements)
        started = perf_counter()
        try:
            return self.db.execute_batch(statements)
        finally:
            self.observe("sql.batch", perf_counter() - started, len(statements))

    def __getattr__(self, name):
        value = getattr(self.db, name)
        if name not in ("begin_read", "begin_write", "commit", "rollback", "close", "initialize_schema", "columns"):
            return value

        def measured(*args, **kwargs):
            started = perf_counter()
            try:
                return value(*args, **kwargs)
            finally:
                self.observe("db." + name, perf_counter() - started, 1)
                if name == "initialize_schema":
                    self.observe("sql.schema", 0.0, sum(bool(s.strip()) for s in args[0].split(";")))
        return measured
