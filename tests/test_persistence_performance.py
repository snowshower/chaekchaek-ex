from flask import g

from app.db import get_db
from app.db_backend import SQLite
from app.services import participation
from app.services.event_logging import context, EXPOSURES
from conftest import Participant, rows
from time import perf_counter
from flask import request_started


def test_response_state_and_completed_retry_do_not_hold_write_lock(app, participant, monkeypatch):
    writes = []
    begin = SQLite.begin_write

    def begin_write(db):
        writes.append(1)
        db.write_active = True
        begin(db)

    def commit(db):
        db.connection.commit()
        db.write_active = False

    original_state = participation.state

    def state(*args):
        assert not getattr(get_db(), "write_active", False)
        return original_state(*args)

    monkeypatch.setattr(SQLite, "begin_write", begin_write)
    monkeypatch.setattr(SQLite, "commit", commit, raising=False)
    monkeypatch.setattr(participation, "state", state)
    payload = participant.payload("short", body="Once")
    assert participant.post(payload).status_code == 200
    assert participant.post(payload).status_code == 200
    assert participant.post({**payload, "body": "Different"}).status_code == 409
    assert len(writes) == 1
    assert len(rows(app, "reviews")) == 1
    assert len(rows(app, "events", "event_type='short_review_submit'")) == 1


def test_batched_exposure_context_preserves_exact_event_fields(app):
    person = Participant(app)
    person.action("observe", event_type="community_open")
    person.action("emoji", option_id="0")
    person.action("observe", event_type="emoji_results_reveal", active_tab=True, visibility_ratio=.5)
    person.open()
    visitor = person.visitor_id()
    page = person.bootstrap["page_view_id"]
    with app.test_request_context():
        g.visitor = {"visitor_id": visitor}
        expected = {}
        for kind in EXPOSURES:
            events = [dict(row) for row in get_db().execute(
                "SELECT event_id,page_view_id,timestamp,client_sequence FROM events WHERE visitor_id=? AND book_id=? AND event_type=? ORDER BY timestamp,event_id",
                (visitor, "metamorphosis", kind))]
            expected[kind] = {"current_page": [e for e in events if e["page_view_id"] == page],
                              "previous_pages": [e for e in events if e["page_view_id"] != page],
                              "observation": "confirmed" if events else "unknown"}
        assert context("metamorphosis", page) == expected


def test_fifty_visitor_workload_profile_counts(app, record_property):
    from test_reporting import test_fifty_test_visitors_do_not_satisfy_experiment_sample
    metrics = {}
    http_calls = []

    def observe(stage, seconds, count):
        old_count, old_seconds = metrics.get(stage, (0, 0.0))
        metrics[stage] = (old_count + count, old_seconds + seconds)

    def started(sender, **kwargs):
        http_calls.append(1)

    app.config["DATABASE_PROFILE_OBSERVER"] = observe
    request_started.connect(started, app, weak=False)
    begin = perf_counter()
    try:
        test_fifty_test_visitors_do_not_satisfy_experiment_sample(app)
    finally:
        request_started.disconnect(started, app)
    assert len(http_calls) == 300
    assert metrics["client.participant"][0] == 50
    assert metrics["client.api.book_view"][0] == 50
    assert metrics["client.api.emoji"][0] == 50
    assert metrics["client.api.short"][0] == 50
    record_property("sqlite.workload.wall", perf_counter() - begin)
    record_property("sqlite.workload.http", len(http_calls))
    for stage, (count, seconds) in metrics.items():
        record_property(stage + ".calls", count)
        record_property(stage + ".seconds", seconds)
