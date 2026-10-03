from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import sqlite3

import pytest

from app.db import get_db


def test_worker_requests_have_independent_connections_and_close(app):
    barrier = Barrier(4)
    connections = []

    def worker(_):
        with app.test_request_context("/"):
            db = get_db()
            assert get_db() is db
            connections.append(db)
            barrier.wait(timeout=10)
        # Check on the creating thread so thread-affinity cannot mask a leak.
        with pytest.raises(sqlite3.ProgrammingError, match="closed database"):
            db.execute("SELECT 1")
        return db

    with ThreadPoolExecutor(max_workers=4) as pool:
        returned = list(pool.map(worker, range(4)))
    assert len({id(db) for db in returned}) == 4


def test_two_tab_policy_without_postgres_failure(app, participant):
    from test_postgres import test_two_tabs_concurrently_preserve_first_success
    test_two_tabs_concurrently_preserve_first_success(app, participant)
