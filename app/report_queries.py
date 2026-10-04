from flask import current_app

from .db import get_db
from .cohorts import non_seed


def period_events(include_test=False):
    rows = get_db().execute("SELECT e.*,v.is_test,v.exclusion_reason FROM events e JOIN visitors v ON v.visitor_id=e.visitor_id WHERE " + non_seed('v') + " ORDER BY e.timestamp,e.event_id").fetchall()
    start, end = current_app.config["EXPERIMENT_START"], current_app.config["EXPERIMENT_END"]
    return [dict(r, in_period=int((not start or r["timestamp"] >= start) and (not end or r["timestamp"] < end))) for r in rows if include_test or not r["is_test"]]


def precedes(first, second):
    if first["page_view_id"] == second["page_view_id"]:
        return first["client_sequence"] < second["client_sequence"]
    return first["timestamp"] < second["timestamp"]


def test_period_events():
    """Separate test-only source, never used by experiment reporting."""
    rows = get_db().execute("SELECT e.*,v.is_test,v.exclusion_reason FROM events e JOIN visitors v ON v.visitor_id=e.visitor_id WHERE v.is_test=1 AND " + non_seed('v') + " ORDER BY e.timestamp,e.event_id").fetchall()
    start, end = current_app.config["EXPERIMENT_START"], current_app.config["EXPERIMENT_END"]
    return [dict(r, in_period=int((not start or r["timestamp"] >= start) and (not end or r["timestamp"] < end))) for r in rows]
