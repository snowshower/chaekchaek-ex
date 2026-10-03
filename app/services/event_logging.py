import json
from datetime import datetime, timezone
from uuid import UUID, uuid4

from flask import g

from ..db import get_db
from ..queries import first_event

EXPOSURES = ("emoji_results_reveal", "poll_results_reveal", "short_reviews_reveal", "community_open", "others_reveal")
EVENT_TYPES = (
    "landing_view", "book_select", "book_view", "excerpt_view", "emoji_reaction", "emoji_cancel",
    "poll_vote", "poll_cancel", "short_review_start", "short_review_submit", "short_review_update",
    "short_review_delete", "like", "like_cancel", "reply_start", "reply_submit", "reply_update",
    "reply_delete", "full_review_start", "full_review_submit", "full_review_update", "full_review_delete",
    *EXPOSURES,
)


class PolicyError(Exception):
    def __init__(self, message, status=400):
        self.message, self.status = message, status


def utcnow():
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def validate_utc(value):
    try:
        date = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if date.utcoffset() is None or date.utcoffset().total_seconds() != 0:
            raise ValueError()
        return date.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")
    except (ValueError, TypeError, AttributeError):
        raise PolicyError("UTC 시각 형식이 올바르지 않습니다.")


def uuid(value):
    try:
        parsed = UUID(value)
        if str(parsed) != value:
            raise ValueError()
        return value
    except (ValueError, TypeError, AttributeError):
        raise PolicyError("UUID 형식이 올바르지 않습니다.")


def context(book_id, page_id):
    result = {}
    for kind in EXPOSURES:
        rows = get_db().execute("SELECT event_id,page_view_id,timestamp,client_sequence FROM events WHERE visitor_id=? AND book_id=? AND event_type=? ORDER BY timestamp,event_id", (g.visitor["visitor_id"], book_id, kind)).fetchall()
        result[kind] = {"current_page": [dict(r) for r in rows if r["page_view_id"] == page_id], "previous_pages": [dict(r) for r in rows if r["page_view_id"] != page_id], "observation": "confirmed" if rows else "unknown"}
    return result


def record(payload, kind, **fields):
    db = get_db()
    page = db.execute("SELECT * FROM page_views WHERE page_view_id=? AND visitor_id=?", (payload["page_view_id"], g.visitor["visitor_id"])).fetchone()
    if not page:
        raise PolicyError("현재 페이지 식별자를 확인할 수 없습니다.", 403)
    event = {
        "event_id": payload["event_id"], "visitor_id": g.visitor["visitor_id"], "event_type": kind,
        "timestamp": utcnow(), "page_view_id": page["page_view_id"], "book_id": page["book_id"],
        "content_version_id": page["content_version_id"], "client_occurred_at": payload["client_occurred_at"],
        "client_sequence": payload["client_sequence"], "exposure_context": json.dumps(context(page["book_id"], page["page_view_id"])),
        "short_submitted_before": int(bool(first_event(g.visitor["visitor_id"], page["book_id"], "short_review_submit"))),
    }
    event.update(fields)
    columns = list(event)
    db.execute(f"INSERT INTO events ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})", list(event.values()))
    return event["event_id"]


def observed_once(payload, kind, **fields):
    extra, args = "", [payload["page_view_id"], kind]
    if kind == "short_reviews_reveal":
        extra = " AND reveal_source=?"
        args.append(fields["reveal_source"])
    elif kind == "reply_start":
        extra = " AND target_id=?"
        args.append(fields["target_id"])
    row = get_db().execute("SELECT event_id FROM events WHERE page_view_id=? AND event_type=?" + extra, args).fetchone()
    return row[0] if row else record(payload, kind, **fields)


def new_id():
    return str(uuid4())
