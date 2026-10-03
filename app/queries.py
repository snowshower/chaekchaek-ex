import json

from .db import get_db


def books():
    return [json.loads(row[0]) for row in get_db().execute("SELECT content_json FROM book_contents ORDER BY effective_at,content_version_id")]


def book(book_id, version=None):
    if version:
        row = get_db().execute("SELECT content_json FROM book_contents WHERE book_id=? AND content_version_id=?", (book_id, version)).fetchone()
    else:
        from .services.event_logging import utcnow
        row = get_db().execute("SELECT content_json FROM book_contents WHERE book_id=? AND effective_at<=? ORDER BY effective_at DESC,content_version_id DESC LIMIT 1", (book_id, utcnow())).fetchone()
    return json.loads(row[0]) if row else None


def first_event(visitor, book_id, event_type):
    return get_db().execute("SELECT * FROM events WHERE visitor_id=? AND book_id=? AND event_type=? ORDER BY timestamp,event_id LIMIT 1", (visitor, book_id, event_type)).fetchone()
