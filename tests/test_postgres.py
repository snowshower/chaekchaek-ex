"""Run the same application policy suite against an isolated PostgreSQL schema."""
import os
from uuid import uuid4

import pytest

from app import create_app
from app.db import get_db, init_db
from test_policies import *
from test_reporting import *
from test_local_community import *
from test_integrity import test_concurrent_retry_and_distinct_tab_submissions
from test_cleanup import *
from test_admin_dashboard import *

TEST_URL = os.getenv("TEST_DATABASE_URL", "").strip()
pytestmark = pytest.mark.skipif(not TEST_URL, reason="TEST_DATABASE_URL is not set; PostgreSQL integration requires a dedicated test DB")


@pytest.fixture
def app(request):
    import psycopg
    from psycopg import sql
    from threading import Lock
    from app.db_diagnostics import safe_error, connection_state
    from time import perf_counter
    from contextvars import ContextVar

    timing_lock = Lock()
    timings = {}
    profile = {}
    phase = "setup"
    body_started = None
    inside_http = ContextVar("postgres_profile_http", default=False)

    def measure(stage, seconds, count):
        with timing_lock:
            qualified = phase + "." + stage
            if stage.startswith(("db.", "sql.")):
                qualified = phase + (".http_db." if inside_http.get() else ".direct_db.") + stage
            for key in (stage, qualified):
                old_count, old_seconds = profile.get(key, (0, 0.0))
                profile[key] = (old_count + count, old_seconds + seconds)

    def switch_phase(value):
        nonlocal phase, body_started
        if value == "body":
            body_started = perf_counter()
        elif phase == "body" and body_started is not None:
            measure("test.body", perf_counter() - body_started, 1)
        phase = value

    request.node.postgres_profile_phase = switch_phase

    def observe(values):
        with timing_lock:
            for stage, (count, seconds) in values.items():
                old_count, old_seconds = timings.get(stage, (0, 0.0))
                timings[stage] = (old_count + count, old_seconds + seconds)

    def control_statement(stage, statement):
        connection = None
        started = perf_counter()
        try:
            with psycopg.connect(TEST_URL, autocommit=True, connect_timeout=10) as connection:
                connection.execute(statement)
        except psycopg.Error as error:
            raise RuntimeError(safe_error(error, stage) + "; " + connection_state(connection)) from None
        finally:
            measure(stage, perf_counter() - started, 1)

    if TEST_URL == os.getenv("DATABASE_URL", "").strip():
        pytest.fail("TEST_DATABASE_URL must differ from the application DATABASE_URL")
    schema = "chaek_test_" + uuid4().hex
    control_statement("setup CREATE SCHEMA", sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    try:
        application = create_app({"TESTING": True, "DATABASE_URL": TEST_URL, "DATABASE_SCHEMA": schema,
                "VERCEL": False, "LOCAL_DEVELOPMENT": True, "SECRET_KEY": "test-secret", "EXPOSURE_POLICY": "cards",
                "ADMIN_USERNAME": "admin", "ADMIN_PASSWORD": "test-password", "EXPERIMENT_START": "", "EXPERIMENT_END": "",
                "DATABASE_DIAGNOSTIC_OBSERVER": observe, "DATABASE_PROFILE_OBSERVER": measure})
        original_wsgi = application.wsgi_app

        def profiled_wsgi(environ, start_response):
            path = environ.get("PATH_INFO", "")
            label = "http.actions" if path == "/api/actions" else "http.bootstrap"
            started = perf_counter()
            token = inside_http.set(True)
            try:
                return original_wsgi(environ, start_response)
            finally:
                inside_http.reset(token)
                measure(label, perf_counter() - started, 1)
        application.wsgi_app = profiled_wsgi
        with application.app_context():
            for iteration in (1, 2):
                started = perf_counter()
                init_db()
                measure(f"setup.init_db.{iteration}", perf_counter() - started, 1)
        yield application
    finally:
        phase = "cleanup"
        # Cleanup gets a fresh connection, not a session left idle for the test.
        try:
            control_statement("cleanup DROP SCHEMA", sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))
        finally:
            lines = [f"{stage}: calls={count}, seconds={seconds:.3f}" for stage, (count, seconds) in sorted(timings.items())]
            request.node.add_report_section("teardown", "PostgreSQL timings", "\n".join(lines))
            for stage, (count, seconds) in sorted(timings.items()):
                request.node.user_properties.extend([(f"postgres.{stage}.calls", count), (f"postgres.{stage}.seconds", round(seconds, 3))])
            for stage, (count, seconds) in sorted(profile.items()):
                request.node.user_properties.extend([(f"profile.{stage}.calls", count), (f"profile.{stage}.seconds", round(seconds, 3))])
            request.node.add_report_section("teardown", "HTTP and DB wall profile", "\n".join(
                f"{stage}: calls={count}, seconds={seconds:.3f}" for stage, (count, seconds) in sorted(profile.items())))


def test_postgres_schema_constraints_and_row_access(app):
    from app.db import IntegrityError
    with app.app_context():
        db = get_db()
        row = db.execute("SELECT book_id FROM books ORDER BY book_id").fetchone()
        assert row[0] == row["book_id"]
        with pytest.raises(IntegrityError):
            db.execute("INSERT INTO book_contents VALUES (?,?,?,?)", ("invalid", "missing-book", "{}", "2026-01-01T00:00:00Z"))
        assert db.execute("SELECT COUNT(*) FROM book_contents WHERE content_version_id=?", ("invalid",)).fetchone()[0] == 0


def test_identical_fixture_reports_match_sqlite(app, tmp_path):
    from conftest import Participant
    from app.services.reporting import report, test_report

    local = create_app({**app.config, "DATABASE_URL": "", "DATABASE_SCHEMA": None,
                        "DATABASE": str(tmp_path / "parity.sqlite")})
    with local.app_context():
        init_db()
    writer, viewer = Participant(local), Participant(local)
    writer.action("emoji", option_id="0")
    writer.action("poll", option_id="1")
    writer.action("short", body="A scene")
    target = writer.state()["own_reviews"]["short"]["id"]
    viewer.action("observe", event_type="community_open")
    viewer.expose(target)
    viewer.action("like", target_id=target, active=True)
    viewer.action("reply", target_id=target, body="A reply")
    viewer.action("full", body="A longer thought")
    local.config["TESTING"] = False
    excluded = Participant(local)
    excluded.action("emoji", option_id="2")
    excluded.action("short", body="Test only")
    tables = ("visitors", "page_views", "emoji_reactions", "poll_votes", "reviews", "likes", "replies", "events", "requests")
    with local.app_context():
        fixture = {table: [dict(row) for row in get_db().execute(f"SELECT * FROM {table}")] for table in tables}
        expected, expected_test = report(), test_report()
    with app.app_context():
        db = get_db()
        db.begin_write()
        try:
            for table, records in fixture.items():
                for record in records:
                    columns = ",".join(record)
                    placeholders = ",".join("?" for _ in record)
                    db.execute(f"INSERT INTO {table} ({columns}) VALUES ({placeholders})", tuple(record.values()))
            db.commit()
        except Exception:
            db.rollback()
            raise
        actual, actual_test = report(), test_report()
        for result in (expected, expected_test, actual, actual_test):
            result.pop("generated_at", None)
        assert actual == expected
        assert actual_test == expected_test


def test_two_tabs_concurrently_preserve_first_success(app, participant):
    import json
    import re
    from html import unescape
    from concurrent.futures import ThreadPoolExecutor
    from conftest import rows

    token = participant.client.get_cookie("visitor_id").value
    second = app.test_client()
    second.set_cookie("visitor_id", token)
    response = second.get("/books/metamorphosis")
    bootstrap = json.loads(unescape(re.search(r"data-json='(.*?)'", response.get_data(as_text=True)).group(1)))
    first_payload = participant.payload("short", body="Two tabs")
    second_payload = {**first_payload, "event_id": str(uuid4()), "page_view_id": bootstrap["page_view_id"], "client_sequence": 2}

    def send(payload):
        client = app.test_client()
        client.set_cookie("visitor_id", token)
        return client.post("/api/actions", json=payload, headers={"X-CSRF-Token": bootstrap["csrf"]}).status_code

    # Each tab must record its own book_view before writing, as real browsers do.
    assert send({**second_payload, "event_id": str(uuid4()), "client_sequence": 1,
                 "operation": "observe", "event_type": "book_view"}) == 200
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert list(pool.map(send, [first_payload, second_payload])) == [200, 200]
    assert len(rows(app, "reviews")) == 1
    assert len(rows(app, "events", "event_type='short_review_submit'")) == 1
    assert send({**first_payload, "body": "Different payload"}) == 409
